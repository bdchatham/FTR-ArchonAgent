"""Property-based tests for pipeline state machine transitions.

This module contains property-based tests using Hypothesis to verify that
the pipeline state machine correctly handles state transitions, timestamps,
and error storage.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, settings, strategies as st, assume

from src.pipeline.state import (
    InvalidTransitionError,
    PipelineStage,
    PipelineState,
    PipelineStateMachine,
    StateRepository,
    StateTransition,
    VALID_TRANSITIONS,
)


# =============================================================================
# In-Memory State Repository for Testing
# =============================================================================


class InMemoryStateRepository(StateRepository):
    """In-memory implementation of StateRepository for testing.
    
    This repository stores pipeline states in memory, allowing tests to
    run without a database connection while still exercising the full
    state machine logic.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory repository."""
        self._states: Dict[str, PipelineState] = {}

    async def save(self, state: PipelineState) -> None:
        """Save or create a new pipeline state.
        
        Args:
            state: The pipeline state to save.
        """
        self._states[state.issue_id] = state

    async def get(self, issue_id: str) -> Optional[PipelineState]:
        """Get pipeline state by issue ID.
        
        Args:
            issue_id: The canonical issue identifier.
            
        Returns:
            The pipeline state if found, None otherwise.
        """
        return self._states.get(issue_id)

    async def list_by_stage(self, stage: PipelineStage) -> List[PipelineState]:
        """List all pipeline states in a given stage.
        
        Args:
            stage: The pipeline stage to filter by.
            
        Returns:
            List of pipeline states in the specified stage.
        """
        return [
            state for state in self._states.values()
            if state.current_stage == stage
        ]

    async def update_with_version(self, state: PipelineState) -> bool:
        """Update state with optimistic locking.
        
        Args:
            state: The pipeline state to update (with incremented version).
            
        Returns:
            True if update succeeded, False if version conflict.
        """
        existing = self._states.get(state.issue_id)
        if existing is None:
            return False
        
        # Check version for optimistic locking
        if existing.version != state.version - 1:
            return False
        
        self._states[state.issue_id] = state
        return True

    def clear(self) -> None:
        """Clear all states from the repository."""
        self._states.clear()


# =============================================================================
# Hypothesis Strategies for Generating Test Data
# =============================================================================


@st.composite
def valid_github_username(draw: st.DrawFn) -> str:
    """Generate a valid GitHub username.
    
    GitHub usernames:
    - Can contain alphanumeric characters and hyphens
    - Cannot start or end with a hyphen
    - Cannot have consecutive hyphens
    - Are 1-39 characters long
    """
    username = draw(
        st.text(
            alphabet=st.sampled_from(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            ),
            min_size=1,
            max_size=20,
        )
    )
    return username


@st.composite
def valid_repo_name(draw: st.DrawFn) -> str:
    """Generate a valid GitHub repository name."""
    name = draw(
        st.text(
            alphabet=st.sampled_from(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            ),
            min_size=1,
            max_size=50,
        ).filter(lambda x: x.strip() and not x.startswith("-"))
    )
    return name


@st.composite
def valid_issue_id(draw: st.DrawFn) -> str:
    """Generate a valid issue ID in format '{owner}/{repo}#{number}'."""
    owner = draw(valid_github_username())
    repo = draw(valid_repo_name())
    number = draw(st.integers(min_value=1, max_value=1000000))
    return f"{owner}/{repo}#{number}"


@st.composite
def valid_repository(draw: st.DrawFn) -> str:
    """Generate a valid repository path in format '{owner}/{repo}'."""
    owner = draw(valid_github_username())
    repo = draw(valid_repo_name())
    return f"{owner}/{repo}"


@st.composite
def valid_transition_pair(draw: st.DrawFn) -> tuple[PipelineStage, PipelineStage]:
    """Generate a valid (from_stage, to_stage) transition pair.
    
    This strategy only generates transitions that are defined in
    VALID_TRANSITIONS, ensuring the transition will succeed.
    """
    # Get all stages that have valid outgoing transitions
    stages_with_transitions = [
        stage for stage, targets in VALID_TRANSITIONS.items()
        if len(targets) > 0
    ]
    
    from_stage = draw(st.sampled_from(stages_with_transitions))
    to_stage = draw(st.sampled_from(VALID_TRANSITIONS[from_stage]))
    
    return (from_stage, to_stage)


@st.composite
def invalid_transition_pair(draw: st.DrawFn) -> tuple[PipelineStage, PipelineStage]:
    """Generate an invalid (from_stage, to_stage) transition pair.
    
    This strategy generates transitions that are NOT defined in
    VALID_TRANSITIONS, ensuring the transition will be rejected.
    """
    all_stages = list(PipelineStage)
    from_stage = draw(st.sampled_from(all_stages))
    
    # Get stages that are NOT valid targets from this stage
    valid_targets = set(VALID_TRANSITIONS.get(from_stage, []))
    invalid_targets = [s for s in all_stages if s not in valid_targets]
    
    # Skip if there are no invalid targets (shouldn't happen with current map)
    assume(len(invalid_targets) > 0)
    
    to_stage = draw(st.sampled_from(invalid_targets))
    
    return (from_stage, to_stage)


@st.composite
def error_message(draw: st.DrawFn) -> str:
    """Generate a non-empty error message."""
    message = draw(
        st.text(min_size=1, max_size=500).filter(lambda x: x.strip())
    )
    return message


@st.composite
def transition_details(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate optional transition details."""
    include_details = draw(st.booleans())
    if not include_details:
        return {}
    
    return {
        "reason": draw(st.text(min_size=1, max_size=100).filter(lambda x: x.strip())),
        "timestamp_extra": draw(st.integers(min_value=0, max_value=1000)),
    }


# =============================================================================
# Helper Functions
# =============================================================================


def run_async(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


async def setup_state_at_stage(
    machine: PipelineStateMachine,
    issue_id: str,
    repository: str,
    target_stage: PipelineStage,
) -> PipelineState:
    """Set up a pipeline state at a specific stage.
    
    This helper creates a state and transitions it through the valid
    path to reach the target stage.
    
    Args:
        machine: The state machine instance.
        issue_id: The issue identifier.
        repository: The repository path.
        target_stage: The stage to reach.
        
    Returns:
        The pipeline state at the target stage.
    """
    # Create initial state (starts at PENDING)
    state = await machine.create(issue_id, repository)
    
    if target_stage == PipelineStage.PENDING:
        return state
    
    # Define a path to reach each stage
    paths = {
        PipelineStage.INTAKE: [PipelineStage.INTAKE],
        PipelineStage.CLARIFICATION: [PipelineStage.INTAKE, PipelineStage.CLARIFICATION],
        PipelineStage.PROVISIONING: [PipelineStage.INTAKE, PipelineStage.PROVISIONING],
        PipelineStage.IMPLEMENTATION: [
            PipelineStage.INTAKE,
            PipelineStage.PROVISIONING,
            PipelineStage.IMPLEMENTATION,
        ],
        PipelineStage.PR_CREATION: [
            PipelineStage.INTAKE,
            PipelineStage.PROVISIONING,
            PipelineStage.IMPLEMENTATION,
            PipelineStage.PR_CREATION,
        ],
        PipelineStage.COMPLETED: [
            PipelineStage.INTAKE,
            PipelineStage.PROVISIONING,
            PipelineStage.IMPLEMENTATION,
            PipelineStage.PR_CREATION,
            PipelineStage.COMPLETED,
        ],
        PipelineStage.FAILED: [PipelineStage.FAILED],
    }
    
    path = paths.get(target_stage, [])
    for stage in path:
        if stage == PipelineStage.FAILED:
            state = await machine.transition(
                issue_id, stage, details={"error": "Test error"}
            )
        else:
            state = await machine.transition(issue_id, stage)
    
    return state


# =============================================================================
# Property Tests
# =============================================================================


class TestStateTransitionValidation:
    """Property tests for state transition validation.

    Feature: agent-orchestration, Property 7: State Transition Validation

    *For any* state transition request, the state machine SHALL only allow
    transitions defined in the valid transitions map, rejecting invalid
    transitions with an error.

    **Validates: Requirements 7.1, 7.2**
    """

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        transition=valid_transition_pair(),
        details=transition_details(),
    )
    @settings(max_examples=100)
    def test_valid_transitions_succeed(
        self,
        issue_id: str,
        repository: str,
        transition: tuple[PipelineStage, PipelineStage],
        details: Dict[str, Any],
    ) -> None:
        """Property 7: Valid transitions defined in VALID_TRANSITIONS succeed.

        *For any* state transition request where the transition is defined
        in VALID_TRANSITIONS, the state machine SHALL successfully complete
        the transition.

        **Validates: Requirements 7.1, 7.2**
        """
        from_stage, to_stage = transition
        
        # Set up repository and machine
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Set up state at the from_stage
            state = await setup_state_at_stage(
                machine, issue_id, repository, from_stage
            )
            assert state.current_stage == from_stage
            
            # Prepare details for FAILED transitions
            if to_stage == PipelineStage.FAILED:
                details["error"] = details.get("error", "Test error message")
            
            # Perform the transition
            new_state = await machine.transition(issue_id, to_stage, details)
            
            # Verify transition succeeded
            assert new_state.current_stage == to_stage
            assert new_state.issue_id == issue_id
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        transition=invalid_transition_pair(),
    )
    @settings(max_examples=100)
    def test_invalid_transitions_raise_error(
        self,
        issue_id: str,
        repository: str,
        transition: tuple[PipelineStage, PipelineStage],
    ) -> None:
        """Property 7: Invalid transitions raise InvalidTransitionError.

        *For any* state transition request where the transition is NOT
        defined in VALID_TRANSITIONS, the state machine SHALL reject the
        transition with an InvalidTransitionError.

        **Validates: Requirements 7.1, 7.2**
        """
        from_stage, to_stage = transition
        
        # Set up repository and machine
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Set up state at the from_stage
            state = await setup_state_at_stage(
                machine, issue_id, repository, from_stage
            )
            assert state.current_stage == from_stage
            
            # Attempt invalid transition - should raise error
            with pytest.raises(InvalidTransitionError) as exc_info:
                await machine.transition(issue_id, to_stage)
            
            # Verify error contains correct information
            assert exc_info.value.from_stage == from_stage
            assert exc_info.value.to_stage == to_stage
            
            # Verify state was not changed
            current_state = await machine.get(issue_id)
            assert current_state is not None
            assert current_state.current_stage == from_stage
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_completed_state_has_no_valid_transitions(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 7 edge case: COMPLETED is a terminal state.

        The COMPLETED state should have no valid outgoing transitions,
        making it a terminal state in the pipeline.

        **Validates: Requirements 7.1, 7.2**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Set up state at COMPLETED
            state = await setup_state_at_stage(
                machine, issue_id, repository, PipelineStage.COMPLETED
            )
            assert state.current_stage == PipelineStage.COMPLETED
            
            # Try all possible transitions - all should fail
            for target_stage in PipelineStage:
                if target_stage == PipelineStage.COMPLETED:
                    continue  # Skip same-stage transition
                
                with pytest.raises(InvalidTransitionError):
                    await machine.transition(issue_id, target_stage)
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_failed_state_can_recover_to_pending(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 7 edge case: FAILED can recover to PENDING.

        The FAILED state should be able to transition back to PENDING
        for manual recovery, but no other transitions should be valid.

        **Validates: Requirements 7.1, 7.2, 7.6**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Set up state at FAILED
            state = await setup_state_at_stage(
                machine, issue_id, repository, PipelineStage.FAILED
            )
            assert state.current_stage == PipelineStage.FAILED
            
            # Recovery to PENDING should succeed
            recovered_state = await machine.transition(
                issue_id,
                PipelineStage.PENDING,
                details={"recovery_reason": "Manual retry requested"},
            )
            assert recovered_state.current_stage == PipelineStage.PENDING
            
            # Error should be cleared after recovery
            assert recovered_state.error is None
        
        run_async(test())


class TestStateTransitionTimestamps:
    """Property tests for state transition timestamps.

    Feature: agent-orchestration, Property 8: State Transition Timestamps

    *For any* successful state transition, the state machine SHALL record
    a timestamp in the state history that is greater than or equal to the
    previous transition timestamp.

    **Validates: Requirement 7.3**
    """

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        transition=valid_transition_pair(),
    )
    @settings(max_examples=100)
    def test_transition_records_timestamp(
        self,
        issue_id: str,
        repository: str,
        transition: tuple[PipelineStage, PipelineStage],
    ) -> None:
        """Property 8: Each transition records a timestamp in state_history.

        *For any* successful state transition, the state machine SHALL
        record a timestamp in the state history.

        **Validates: Requirement 7.3**
        """
        from_stage, to_stage = transition
        
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Set up state at from_stage
            state = await setup_state_at_stage(
                machine, issue_id, repository, from_stage
            )
            history_len_before = len(state.state_history)
            
            # Prepare details for FAILED transitions
            details = {}
            if to_stage == PipelineStage.FAILED:
                details["error"] = "Test error message"
            
            # Perform transition
            new_state = await machine.transition(issue_id, to_stage, details)
            
            # Verify a new transition was recorded
            assert len(new_state.state_history) == history_len_before + 1
            
            # Verify the transition has a timestamp
            last_transition = new_state.state_history[-1]
            assert last_transition.timestamp is not None
            assert isinstance(last_transition.timestamp, datetime)
            assert last_transition.timestamp.tzinfo is not None  # Has timezone
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_timestamps_are_monotonically_increasing(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 8: Timestamps are monotonically increasing.

        *For any* sequence of successful state transitions, each timestamp
        in the state history SHALL be greater than or equal to the previous
        transition timestamp.

        **Validates: Requirement 7.3**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and perform multiple transitions
            state = await machine.create(issue_id, repository)
            
            # Perform a sequence of valid transitions
            transitions = [
                PipelineStage.INTAKE,
                PipelineStage.PROVISIONING,
                PipelineStage.IMPLEMENTATION,
                PipelineStage.PR_CREATION,
                PipelineStage.COMPLETED,
            ]
            
            for stage in transitions:
                state = await machine.transition(issue_id, stage)
            
            # Verify timestamps are monotonically increasing
            history = state.state_history
            assert len(history) == len(transitions)
            
            for i in range(1, len(history)):
                prev_ts = history[i - 1].timestamp
                curr_ts = history[i].timestamp
                assert curr_ts >= prev_ts, (
                    f"Timestamp at index {i} ({curr_ts}) is less than "
                    f"timestamp at index {i-1} ({prev_ts})"
                )
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_transition_records_from_and_to_stages(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 8: Transition records include from and to stages.

        Each state transition record SHALL include both the source stage
        and the target stage.

        **Validates: Requirement 7.3**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and perform a transition
            state = await machine.create(issue_id, repository)
            assert state.current_stage == PipelineStage.PENDING
            
            # Transition to INTAKE
            new_state = await machine.transition(issue_id, PipelineStage.INTAKE)
            
            # Verify the transition record
            assert len(new_state.state_history) == 1
            transition = new_state.state_history[0]
            assert transition.from_stage == PipelineStage.PENDING
            assert transition.to_stage == PipelineStage.INTAKE
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_rapid_transitions_maintain_timestamp_order(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 8 edge case: Rapid transitions maintain timestamp order.

        Even when transitions happen very quickly in succession, timestamps
        SHALL remain monotonically increasing (or equal).

        **Validates: Requirement 7.3**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state
            state = await machine.create(issue_id, repository)
            
            # Perform rapid transitions without any delay
            state = await machine.transition(issue_id, PipelineStage.INTAKE)
            state = await machine.transition(issue_id, PipelineStage.PROVISIONING)
            state = await machine.transition(issue_id, PipelineStage.IMPLEMENTATION)
            
            # Verify timestamps are still ordered
            history = state.state_history
            for i in range(1, len(history)):
                assert history[i].timestamp >= history[i - 1].timestamp
        
        run_async(test())


class TestFailedStateErrorStorage:
    """Property tests for failed state error storage.

    Feature: agent-orchestration, Property 9: Failed State Error Storage

    *For any* transition to the `failed` state, the pipeline state SHALL
    contain a non-empty error message describing the failure.

    **Validates: Requirement 7.4**
    """

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        error_msg=error_message(),
    )
    @settings(max_examples=100)
    def test_failed_transition_stores_error_message(
        self,
        issue_id: str,
        repository: str,
        error_msg: str,
    ) -> None:
        """Property 9: Transition to FAILED stores error message.

        *For any* transition to the `failed` state with an error message
        provided, the pipeline state SHALL contain that error message.

        **Validates: Requirement 7.4**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and transition to INTAKE
            await machine.create(issue_id, repository)
            await machine.transition(issue_id, PipelineStage.INTAKE)
            
            # Transition to FAILED with error message
            failed_state = await machine.transition(
                issue_id,
                PipelineStage.FAILED,
                details={"error": error_msg},
            )
            
            # Verify error is stored
            assert failed_state.error is not None
            assert failed_state.error == error_msg
            assert len(failed_state.error) > 0
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_failed_transition_without_error_gets_default(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 9: FAILED transition without error gets default message.

        *For any* transition to the `failed` state without an explicit
        error message, the pipeline state SHALL contain a non-empty
        default error message.

        **Validates: Requirement 7.4**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and transition to INTAKE
            await machine.create(issue_id, repository)
            await machine.transition(issue_id, PipelineStage.INTAKE)
            
            # Transition to FAILED without error message
            failed_state = await machine.transition(
                issue_id,
                PipelineStage.FAILED,
                details={},  # No error key
            )
            
            # Verify a default error message is stored
            assert failed_state.error is not None
            assert len(failed_state.error) > 0
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        from_stage=st.sampled_from([
            PipelineStage.PENDING,
            PipelineStage.INTAKE,
            PipelineStage.CLARIFICATION,
            PipelineStage.PROVISIONING,
            PipelineStage.IMPLEMENTATION,
            PipelineStage.PR_CREATION,
        ]),
        error_msg=error_message(),
    )
    @settings(max_examples=100)
    def test_failed_from_any_stage_stores_error(
        self,
        issue_id: str,
        repository: str,
        from_stage: PipelineStage,
        error_msg: str,
    ) -> None:
        """Property 9: FAILED from any stage stores error message.

        *For any* stage that can transition to FAILED, the error message
        SHALL be stored in the pipeline state.

        **Validates: Requirement 7.4**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Set up state at the from_stage
            state = await setup_state_at_stage(
                machine, issue_id, repository, from_stage
            )
            assert state.current_stage == from_stage
            
            # Transition to FAILED
            failed_state = await machine.transition(
                issue_id,
                PipelineStage.FAILED,
                details={"error": error_msg},
            )
            
            # Verify error is stored
            assert failed_state.current_stage == PipelineStage.FAILED
            assert failed_state.error == error_msg
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        error_msg=error_message(),
    )
    @settings(max_examples=100)
    def test_error_cleared_on_recovery(
        self,
        issue_id: str,
        repository: str,
        error_msg: str,
    ) -> None:
        """Property 9 edge case: Error is cleared on recovery to PENDING.

        When recovering from FAILED to PENDING, the error message SHALL
        be cleared from the pipeline state.

        **Validates: Requirement 7.4**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and transition to FAILED
            await machine.create(issue_id, repository)
            await machine.transition(issue_id, PipelineStage.INTAKE)
            failed_state = await machine.transition(
                issue_id,
                PipelineStage.FAILED,
                details={"error": error_msg},
            )
            
            # Verify error is stored
            assert failed_state.error == error_msg
            
            # Recover to PENDING
            recovered_state = await machine.transition(
                issue_id,
                PipelineStage.PENDING,
                details={"recovery_reason": "Manual retry"},
            )
            
            # Verify error is cleared
            assert recovered_state.error is None
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        error_msg=error_message(),
    )
    @settings(max_examples=100)
    def test_error_in_transition_details(
        self,
        issue_id: str,
        repository: str,
        error_msg: str,
    ) -> None:
        """Property 9: Error is also recorded in transition details.

        The error message SHALL be accessible both in the state's error
        field and in the transition details for the FAILED transition.

        **Validates: Requirement 7.4**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and transition to FAILED
            await machine.create(issue_id, repository)
            await machine.transition(issue_id, PipelineStage.INTAKE)
            failed_state = await machine.transition(
                issue_id,
                PipelineStage.FAILED,
                details={"error": error_msg, "extra_info": "test"},
            )
            
            # Find the FAILED transition in history
            failed_transition = None
            for t in failed_state.state_history:
                if t.to_stage == PipelineStage.FAILED:
                    failed_transition = t
                    break
            
            assert failed_transition is not None
            assert failed_transition.details.get("error") == error_msg
        
        run_async(test())


class TestEdgeCases:
    """Edge case tests for state machine behavior.

    These tests verify that the state machine handles edge cases correctly,
    including rapid transitions, recovery from failed state, and state
    history preservation.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4**
    """

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_state_history_preserved_through_transitions(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Edge case: State history is preserved through all transitions.

        The complete state history SHALL be preserved as the pipeline
        progresses through multiple stages.

        **Validates: Requirements 7.1, 7.3**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and perform multiple transitions
            await machine.create(issue_id, repository)
            
            transitions = [
                (PipelineStage.INTAKE, {}),
                (PipelineStage.CLARIFICATION, {}),
                (PipelineStage.INTAKE, {"reason": "re-evaluation"}),
                (PipelineStage.PROVISIONING, {}),
                (PipelineStage.IMPLEMENTATION, {}),
                (PipelineStage.PR_CREATION, {}),
                (PipelineStage.COMPLETED, {}),
            ]
            
            for stage, details in transitions:
                await machine.transition(issue_id, stage, details)
            
            # Get final state
            final_state = await machine.get(issue_id)
            assert final_state is not None
            
            # Verify all transitions are recorded
            assert len(final_state.state_history) == len(transitions)
            
            # Verify transition sequence
            expected_stages = [t[0] for t in transitions]
            actual_stages = [t.to_stage for t in final_state.state_history]
            assert actual_stages == expected_stages
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_multiple_failures_and_recoveries(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Edge case: Multiple failure and recovery cycles.

        The state machine SHALL correctly handle multiple cycles of
        failure and recovery.

        **Validates: Requirements 7.1, 7.2, 7.4**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state
            await machine.create(issue_id, repository)
            
            # First attempt: fail at INTAKE
            await machine.transition(issue_id, PipelineStage.INTAKE)
            state = await machine.transition(
                issue_id,
                PipelineStage.FAILED,
                details={"error": "First failure"},
            )
            assert state.error == "First failure"
            
            # Recover
            state = await machine.transition(issue_id, PipelineStage.PENDING)
            assert state.error is None
            
            # Second attempt: fail at PROVISIONING
            await machine.transition(issue_id, PipelineStage.INTAKE)
            await machine.transition(issue_id, PipelineStage.PROVISIONING)
            state = await machine.transition(
                issue_id,
                PipelineStage.FAILED,
                details={"error": "Second failure"},
            )
            assert state.error == "Second failure"
            
            # Recover again
            state = await machine.transition(issue_id, PipelineStage.PENDING)
            assert state.error is None
            
            # Third attempt: succeed
            await machine.transition(issue_id, PipelineStage.INTAKE)
            await machine.transition(issue_id, PipelineStage.PROVISIONING)
            await machine.transition(issue_id, PipelineStage.IMPLEMENTATION)
            await machine.transition(issue_id, PipelineStage.PR_CREATION)
            state = await machine.transition(issue_id, PipelineStage.COMPLETED)
            
            assert state.current_stage == PipelineStage.COMPLETED
            assert state.error is None
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_clarification_loop(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Edge case: Clarification loop back to intake.

        The state machine SHALL correctly handle the clarification loop
        where CLARIFICATION transitions back to INTAKE for re-evaluation.

        **Validates: Requirements 7.1, 7.2**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state
            await machine.create(issue_id, repository)
            
            # First classification - needs clarification
            await machine.transition(issue_id, PipelineStage.INTAKE)
            await machine.transition(issue_id, PipelineStage.CLARIFICATION)
            
            # User responds - re-evaluate
            await machine.transition(issue_id, PipelineStage.INTAKE)
            
            # Still needs clarification
            await machine.transition(issue_id, PipelineStage.CLARIFICATION)
            
            # User responds again - now complete enough
            await machine.transition(issue_id, PipelineStage.INTAKE)
            
            # Proceed to provisioning
            state = await machine.transition(issue_id, PipelineStage.PROVISIONING)
            
            assert state.current_stage == PipelineStage.PROVISIONING
            
            # Verify the clarification loop is recorded in history
            clarification_count = sum(
                1 for t in state.state_history
                if t.to_stage == PipelineStage.CLARIFICATION
            )
            assert clarification_count == 2
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_version_increments_on_transition(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Edge case: Version increments on each transition.

        The state version SHALL increment with each successful transition
        for optimistic locking support.

        **Validates: Requirements 7.2, 8.5**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state - version starts at 1
            state = await machine.create(issue_id, repository)
            assert state.version == 1
            
            # Each transition increments version
            state = await machine.transition(issue_id, PipelineStage.INTAKE)
            assert state.version == 2
            
            state = await machine.transition(issue_id, PipelineStage.PROVISIONING)
            assert state.version == 3
            
            state = await machine.transition(issue_id, PipelineStage.IMPLEMENTATION)
            assert state.version == 4
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_updated_at_changes_on_transition(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Edge case: updated_at timestamp changes on transition.

        The updated_at field SHALL be updated with each state transition.

        **Validates: Requirement 7.3**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state
            state = await machine.create(issue_id, repository)
            created_at = state.created_at
            updated_at_1 = state.updated_at
            
            # Transition
            state = await machine.transition(issue_id, PipelineStage.INTAKE)
            updated_at_2 = state.updated_at
            
            # created_at should not change
            assert state.created_at == created_at
            
            # updated_at should be >= previous
            assert updated_at_2 >= updated_at_1
        
        run_async(test())
