"""Property-based tests for pipeline state persistence.

This module contains property-based tests using Hypothesis to verify that
the state repository correctly handles state persistence, queries, and
optimistic locking.

**Validates: Requirements 7.5, 8.1, 8.2, 8.3, 8.5**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>

Note: These tests use InMemoryStateRepository to test the repository interface
contract. The PostgresStateRepository will be tested in integration tests.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, settings, strategies as st, assume, HealthCheck

from src.pipeline.state import (
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
    repository interface contract.
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
    """Generate a valid GitHub username."""
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
def valid_classification(draw: st.DrawFn) -> Optional[Dict[str, Any]]:
    """Generate a valid classification dictionary or None."""
    include = draw(st.booleans())
    if not include:
        return None
    
    return {
        "issue_type": draw(st.sampled_from(["feature", "bug", "documentation", "infrastructure", "unknown"])),
        "requirements": draw(st.lists(st.text(min_size=1, max_size=100), min_size=0, max_size=5)),
        "affected_packages": draw(st.lists(st.text(min_size=1, max_size=50), min_size=0, max_size=3)),
        "completeness_score": draw(st.integers(min_value=1, max_value=5)),
    }


@st.composite
def valid_workspace_path(draw: st.DrawFn) -> Optional[str]:
    """Generate a valid workspace path or None."""
    include = draw(st.booleans())
    if not include:
        return None
    
    path_parts = draw(st.lists(
        st.text(
            alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-_"),
            min_size=1,
            max_size=20,
        ),
        min_size=1,
        max_size=5,
    ))
    return "/var/lib/archon/workspaces/" + "/".join(path_parts)


@st.composite
def valid_pr_number(draw: st.DrawFn) -> Optional[int]:
    """Generate a valid PR number or None."""
    include = draw(st.booleans())
    if not include:
        return None
    return draw(st.integers(min_value=1, max_value=100000))


@st.composite
def valid_error_message(draw: st.DrawFn) -> Optional[str]:
    """Generate a valid error message or None."""
    include = draw(st.booleans())
    if not include:
        return None
    return draw(st.text(min_size=1, max_size=500).filter(lambda x: x.strip()))


@st.composite
def valid_pipeline_state(draw: st.DrawFn) -> PipelineState:
    """Generate a valid PipelineState with all fields populated."""
    issue_id = draw(valid_issue_id())
    repository = draw(valid_repository())
    stage = draw(st.sampled_from(list(PipelineStage)))
    
    # Generate state history based on stage
    state_history = []
    if stage != PipelineStage.PENDING:
        # Create a plausible history leading to current stage
        now = datetime.now(timezone.utc)
        if stage == PipelineStage.INTAKE:
            state_history = [
                StateTransition(
                    from_stage=PipelineStage.PENDING,
                    to_stage=PipelineStage.INTAKE,
                    timestamp=now,
                    details={},
                )
            ]
        elif stage == PipelineStage.FAILED:
            state_history = [
                StateTransition(
                    from_stage=PipelineStage.PENDING,
                    to_stage=PipelineStage.INTAKE,
                    timestamp=now,
                    details={},
                ),
                StateTransition(
                    from_stage=PipelineStage.INTAKE,
                    to_stage=PipelineStage.FAILED,
                    timestamp=now,
                    details={"error": "Test error"},
                ),
            ]
    
    classification = draw(valid_classification())
    workspace_path = draw(valid_workspace_path())
    pr_number = draw(valid_pr_number())
    error = draw(valid_error_message()) if stage == PipelineStage.FAILED else None
    
    now = datetime.now(timezone.utc)
    version = draw(st.integers(min_value=1, max_value=100))
    
    return PipelineState(
        issue_id=issue_id,
        repository=repository,
        current_stage=stage,
        state_history=state_history,
        classification=classification,
        workspace_path=workspace_path,
        pr_number=pr_number,
        error=error,
        created_at=now,
        updated_at=now,
        version=version,
    )


@st.composite
def unique_issue_ids(draw: st.DrawFn, min_size: int = 1, max_size: int = 10) -> List[str]:
    """Generate a list of unique issue IDs efficiently."""
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    # Use simple sequential IDs to avoid uniqueness generation overhead
    base_owner = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz",
        min_size=3,
        max_size=8,
    ))
    base_repo = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz",
        min_size=3,
        max_size=8,
    ))
    # Generate unique IDs by using sequential numbers
    return [f"{base_owner}/{base_repo}#{i}" for i in range(1, count + 1)]


# =============================================================================
# Helper Functions
# =============================================================================


def run_async(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


def states_are_equivalent(state1: PipelineState, state2: PipelineState) -> bool:
    """Check if two pipeline states are equivalent.
    
    This compares all fields except for minor timestamp differences
    that might occur due to serialization.
    """
    if state1.issue_id != state2.issue_id:
        return False
    if state1.repository != state2.repository:
        return False
    if state1.current_stage != state2.current_stage:
        return False
    if state1.classification != state2.classification:
        return False
    if state1.workspace_path != state2.workspace_path:
        return False
    if state1.pr_number != state2.pr_number:
        return False
    if state1.error != state2.error:
        return False
    if state1.version != state2.version:
        return False
    if len(state1.state_history) != len(state2.state_history):
        return False
    
    # Compare state history
    for t1, t2 in zip(state1.state_history, state2.state_history):
        if t1.from_stage != t2.from_stage:
            return False
        if t1.to_stage != t2.to_stage:
            return False
        if t1.details != t2.details:
            return False
    
    return True


# =============================================================================
# Property Tests
# =============================================================================


class TestStateQueryCorrectness:
    """Property tests for state query correctness.

    Feature: agent-orchestration, Property 10: State Query Correctness

    *For any* set of pipeline states, querying by stage SHALL return exactly
    the states with that current stage, with no false positives or negatives.

    **Validates: Requirement 7.5**
    """

    @given(
        issue_ids=unique_issue_ids(min_size=3, max_size=10),
        target_stage=st.sampled_from(list(PipelineStage)),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.large_base_example, HealthCheck.too_slow])
    def test_list_by_stage_returns_exact_matches(
        self,
        issue_ids: List[str],
        target_stage: PipelineStage,
    ) -> None:
        """Property 10: list_by_stage returns exactly matching states.

        *For any* set of pipeline states with various stages, querying by
        a specific stage SHALL return exactly the states with that stage,
        with no false positives or negatives.

        **Validates: Requirement 7.5**
        """
        repo = InMemoryStateRepository()
        
        async def test():
            # Create states with different stages
            created_states = []
            stages = list(PipelineStage)
            
            for i, issue_id in enumerate(issue_ids):
                # Assign stages in a round-robin fashion
                stage = stages[i % len(stages)]
                
                now = datetime.now(timezone.utc)
                state = PipelineState(
                    issue_id=issue_id,
                    repository=f"owner/repo{i}",
                    current_stage=stage,
                    state_history=[],
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
                await repo.save(state)
                created_states.append(state)
            
            # Query by target stage
            results = await repo.list_by_stage(target_stage)
            
            # Calculate expected results
            expected_ids = {
                s.issue_id for s in created_states
                if s.current_stage == target_stage
            }
            actual_ids = {s.issue_id for s in results}
            
            # No false positives: all returned states have the target stage
            for result in results:
                assert result.current_stage == target_stage, (
                    f"False positive: {result.issue_id} has stage "
                    f"{result.current_stage.value}, expected {target_stage.value}"
                )
            
            # No false negatives: all states with target stage are returned
            assert actual_ids == expected_ids, (
                f"Missing states: {expected_ids - actual_ids}, "
                f"Extra states: {actual_ids - expected_ids}"
            )
        
        run_async(test())


    @given(
        issue_ids=unique_issue_ids(min_size=5, max_size=15),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.large_base_example, HealthCheck.too_slow])
    def test_list_by_stage_empty_for_unused_stage(
        self,
        issue_ids: List[str],
    ) -> None:
        """Property 10: list_by_stage returns empty for unused stages.

        *For any* set of pipeline states that don't include a particular
        stage, querying by that stage SHALL return an empty list.

        **Validates: Requirement 7.5**
        """
        repo = InMemoryStateRepository()
        
        async def test():
            # Create states only in PENDING and INTAKE stages
            used_stages = [PipelineStage.PENDING, PipelineStage.INTAKE]
            
            for i, issue_id in enumerate(issue_ids):
                stage = used_stages[i % len(used_stages)]
                now = datetime.now(timezone.utc)
                state = PipelineState(
                    issue_id=issue_id,
                    repository=f"owner/repo{i}",
                    current_stage=stage,
                    state_history=[],
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
                await repo.save(state)
            
            # Query for stages that weren't used
            unused_stages = [
                PipelineStage.PROVISIONING,
                PipelineStage.IMPLEMENTATION,
                PipelineStage.PR_CREATION,
                PipelineStage.COMPLETED,
            ]
            
            for stage in unused_stages:
                results = await repo.list_by_stage(stage)
                assert len(results) == 0, (
                    f"Expected empty list for {stage.value}, got {len(results)} results"
                )
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_list_by_stage_reflects_transitions(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 10: list_by_stage reflects state transitions.

        *For any* state that transitions between stages, list_by_stage
        SHALL correctly reflect the current stage after each transition.

        **Validates: Requirement 7.5**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state in PENDING
            await machine.create(issue_id, repository)
            
            # Verify it appears in PENDING query
            pending_states = await repo.list_by_stage(PipelineStage.PENDING)
            assert any(s.issue_id == issue_id for s in pending_states)
            
            # Transition to INTAKE
            await machine.transition(issue_id, PipelineStage.INTAKE)
            
            # Verify it no longer appears in PENDING
            pending_states = await repo.list_by_stage(PipelineStage.PENDING)
            assert not any(s.issue_id == issue_id for s in pending_states)
            
            # Verify it now appears in INTAKE
            intake_states = await repo.list_by_stage(PipelineStage.INTAKE)
            assert any(s.issue_id == issue_id for s in intake_states)
        
        run_async(test())


class TestStatePersistenceRoundTrip:
    """Property tests for state persistence round-trip.

    Feature: agent-orchestration, Property 11: State Persistence Round-Trip

    *For any* pipeline state saved to the database, retrieving it by issue ID
    SHALL return an equivalent state with all fields preserved.

    **Validates: Requirements 8.1, 8.2**
    """

    @given(state=valid_pipeline_state())
    @settings(max_examples=100)
    def test_save_get_preserves_all_fields(
        self,
        state: PipelineState,
    ) -> None:
        """Property 11: Save and get preserves all fields.

        *For any* pipeline state saved to the repository, retrieving it
        by issue ID SHALL return an equivalent state with all fields
        preserved.

        **Validates: Requirements 8.1, 8.2**
        """
        repo = InMemoryStateRepository()
        
        async def test():
            # Save the state
            await repo.save(state)
            
            # Retrieve it
            retrieved = await repo.get(state.issue_id)
            
            # Verify it was retrieved
            assert retrieved is not None, "State should be retrievable after save"
            
            # Verify all fields are preserved
            assert states_are_equivalent(state, retrieved), (
                f"Retrieved state differs from saved state:\n"
                f"Saved: {state}\n"
                f"Retrieved: {retrieved}"
            )
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        classification=valid_classification(),
        workspace_path=valid_workspace_path(),
        pr_number=valid_pr_number(),
    )
    @settings(max_examples=100)
    def test_round_trip_preserves_optional_fields(
        self,
        issue_id: str,
        repository: str,
        classification: Optional[Dict[str, Any]],
        workspace_path: Optional[str],
        pr_number: Optional[int],
    ) -> None:
        """Property 11: Round-trip preserves optional fields.

        *For any* pipeline state with optional fields (classification,
        workspace_path, pr_number), saving and retrieving SHALL preserve
        these fields exactly.

        **Validates: Requirements 8.1, 8.2**
        """
        repo = InMemoryStateRepository()
        
        async def test():
            now = datetime.now(timezone.utc)
            state = PipelineState(
                issue_id=issue_id,
                repository=repository,
                current_stage=PipelineStage.PENDING,
                state_history=[],
                classification=classification,
                workspace_path=workspace_path,
                pr_number=pr_number,
                created_at=now,
                updated_at=now,
                version=1,
            )
            
            await repo.save(state)
            retrieved = await repo.get(issue_id)
            
            assert retrieved is not None
            assert retrieved.classification == classification
            assert retrieved.workspace_path == workspace_path
            assert retrieved.pr_number == pr_number
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_round_trip_preserves_state_history(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 11: Round-trip preserves state history.

        *For any* pipeline state with state history, saving and retrieving
        SHALL preserve the complete history with all transition details.

        **Validates: Requirements 8.1, 8.2**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and perform transitions to build history
            await machine.create(issue_id, repository)
            await machine.transition(issue_id, PipelineStage.INTAKE)
            await machine.transition(
                issue_id,
                PipelineStage.CLARIFICATION,
                details={"reason": "needs more info"},
            )
            await machine.transition(
                issue_id,
                PipelineStage.INTAKE,
                details={"reason": "re-evaluation"},
            )
            
            # Get the state with history
            state = await machine.get(issue_id)
            assert state is not None
            
            # Verify history is preserved
            assert len(state.state_history) == 3
            
            # Verify transition details are preserved
            assert state.state_history[0].from_stage == PipelineStage.PENDING
            assert state.state_history[0].to_stage == PipelineStage.INTAKE
            
            assert state.state_history[1].from_stage == PipelineStage.INTAKE
            assert state.state_history[1].to_stage == PipelineStage.CLARIFICATION
            assert state.state_history[1].details.get("reason") == "needs more info"
            
            assert state.state_history[2].from_stage == PipelineStage.CLARIFICATION
            assert state.state_history[2].to_stage == PipelineStage.INTAKE
            assert state.state_history[2].details.get("reason") == "re-evaluation"
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        error_msg=st.text(min_size=1, max_size=500).filter(lambda x: x.strip()),
    )
    @settings(max_examples=100)
    def test_round_trip_preserves_error_field(
        self,
        issue_id: str,
        repository: str,
        error_msg: str,
    ) -> None:
        """Property 11: Round-trip preserves error field.

        *For any* pipeline state in FAILED stage with an error message,
        saving and retrieving SHALL preserve the error message exactly.

        **Validates: Requirements 8.1, 8.2**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and transition to FAILED
            await machine.create(issue_id, repository)
            await machine.transition(issue_id, PipelineStage.INTAKE)
            await machine.transition(
                issue_id,
                PipelineStage.FAILED,
                details={"error": error_msg},
            )
            
            # Retrieve and verify error is preserved
            state = await machine.get(issue_id)
            assert state is not None
            assert state.error == error_msg
        
        run_async(test())


class TestStateTransactionalAtomicity:
    """Property tests for state transactional atomicity.

    Feature: agent-orchestration, Property 12: State Transactional Atomicity

    *For any* state update operation, either all changes (state, history,
    timestamps) are persisted together, or none are persisted (no partial
    updates).

    **Validates: Requirement 8.3**
    """

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_transition_updates_all_fields_atomically(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 12: Transition updates all fields atomically.

        *For any* state transition, the current_stage, state_history,
        updated_at, and version SHALL all be updated together.

        **Validates: Requirement 8.3**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create initial state
            initial_state = await machine.create(issue_id, repository)
            initial_version = initial_state.version
            initial_updated_at = initial_state.updated_at
            initial_history_len = len(initial_state.state_history)
            
            # Perform transition
            new_state = await machine.transition(issue_id, PipelineStage.INTAKE)
            
            # Verify all fields were updated together
            assert new_state.current_stage == PipelineStage.INTAKE
            assert new_state.version == initial_version + 1
            assert new_state.updated_at >= initial_updated_at
            assert len(new_state.state_history) == initial_history_len + 1
            
            # Verify the persisted state matches
            persisted = await repo.get(issue_id)
            assert persisted is not None
            assert persisted.current_stage == new_state.current_stage
            assert persisted.version == new_state.version
            assert len(persisted.state_history) == len(new_state.state_history)
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_failed_update_leaves_state_unchanged(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 12: Failed update leaves state unchanged.

        *For any* state update that fails (e.g., version conflict),
        the original state SHALL remain unchanged with no partial updates.

        **Validates: Requirement 8.3**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create initial state
            await machine.create(issue_id, repository)
            await machine.transition(issue_id, PipelineStage.INTAKE)
            
            # Get current state
            current_state = await repo.get(issue_id)
            assert current_state is not None
            original_version = current_state.version
            original_stage = current_state.current_stage
            original_history_len = len(current_state.state_history)
            
            # Create a stale state with wrong version
            stale_state = PipelineState(
                issue_id=issue_id,
                repository=repository,
                current_stage=PipelineStage.PROVISIONING,
                state_history=current_state.state_history + [
                    StateTransition(
                        from_stage=PipelineStage.INTAKE,
                        to_stage=PipelineStage.PROVISIONING,
                        timestamp=datetime.now(timezone.utc),
                        details={},
                    )
                ],
                created_at=current_state.created_at,
                updated_at=datetime.now(timezone.utc),
                version=original_version,  # Wrong version - should be original_version + 1
            )
            
            # Attempt update with wrong version
            success = await repo.update_with_version(stale_state)
            assert not success, "Update with wrong version should fail"
            
            # Verify state is unchanged
            after_state = await repo.get(issue_id)
            assert after_state is not None
            assert after_state.version == original_version
            assert after_state.current_stage == original_stage
            assert len(after_state.state_history) == original_history_len
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_history_and_stage_always_consistent(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 12: History and stage are always consistent.

        *For any* persisted state, the current_stage SHALL match the
        to_stage of the last transition in state_history (if any).

        **Validates: Requirement 8.3**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state and perform multiple transitions
            await machine.create(issue_id, repository)
            
            transitions = [
                PipelineStage.INTAKE,
                PipelineStage.PROVISIONING,
                PipelineStage.IMPLEMENTATION,
            ]
            
            for stage in transitions:
                await machine.transition(issue_id, stage)
                
                # After each transition, verify consistency
                state = await repo.get(issue_id)
                assert state is not None
                
                if state.state_history:
                    last_transition = state.state_history[-1]
                    assert state.current_stage == last_transition.to_stage, (
                        f"Inconsistency: current_stage={state.current_stage.value}, "
                        f"last transition to_stage={last_transition.to_stage.value}"
                    )
        
        run_async(test())


class TestStateOptimisticLocking:
    """Property tests for state optimistic locking.

    Feature: agent-orchestration, Property 14: State Optimistic Locking

    *For any* concurrent update attempts on the same pipeline state, exactly
    one SHALL succeed and others SHALL fail with a version conflict error.

    **Validates: Requirement 8.5**
    """

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_version_mismatch_causes_update_failure(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 14: Version mismatch causes update failure.

        *For any* update attempt with a version that doesn't match the
        current version + 1, the update SHALL fail.

        **Validates: Requirement 8.5**
        """
        repo = InMemoryStateRepository()
        
        async def test():
            # Create initial state
            now = datetime.now(timezone.utc)
            state = PipelineState(
                issue_id=issue_id,
                repository=repository,
                current_stage=PipelineStage.PENDING,
                state_history=[],
                created_at=now,
                updated_at=now,
                version=1,
            )
            await repo.save(state)
            
            # Try to update with wrong version (version 3 when current is 1)
            wrong_version_state = PipelineState(
                issue_id=issue_id,
                repository=repository,
                current_stage=PipelineStage.INTAKE,
                state_history=[
                    StateTransition(
                        from_stage=PipelineStage.PENDING,
                        to_stage=PipelineStage.INTAKE,
                        timestamp=now,
                        details={},
                    )
                ],
                created_at=now,
                updated_at=now,
                version=3,  # Wrong - should be 2
            )
            
            success = await repo.update_with_version(wrong_version_state)
            assert not success, "Update with wrong version should fail"
            
            # Verify original state is unchanged
            current = await repo.get(issue_id)
            assert current is not None
            assert current.version == 1
            assert current.current_stage == PipelineStage.PENDING
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_correct_version_allows_update(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 14: Correct version allows update.

        *For any* update attempt with the correct version (current + 1),
        the update SHALL succeed.

        **Validates: Requirement 8.5**
        """
        repo = InMemoryStateRepository()
        
        async def test():
            # Create initial state
            now = datetime.now(timezone.utc)
            state = PipelineState(
                issue_id=issue_id,
                repository=repository,
                current_stage=PipelineStage.PENDING,
                state_history=[],
                created_at=now,
                updated_at=now,
                version=1,
            )
            await repo.save(state)
            
            # Update with correct version
            correct_version_state = PipelineState(
                issue_id=issue_id,
                repository=repository,
                current_stage=PipelineStage.INTAKE,
                state_history=[
                    StateTransition(
                        from_stage=PipelineStage.PENDING,
                        to_stage=PipelineStage.INTAKE,
                        timestamp=now,
                        details={},
                    )
                ],
                created_at=now,
                updated_at=now,
                version=2,  # Correct - current (1) + 1
            )
            
            success = await repo.update_with_version(correct_version_state)
            assert success, "Update with correct version should succeed"
            
            # Verify state was updated
            current = await repo.get(issue_id)
            assert current is not None
            assert current.version == 2
            assert current.current_stage == PipelineStage.INTAKE
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
        num_concurrent=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=100)
    def test_concurrent_updates_exactly_one_succeeds(
        self,
        issue_id: str,
        repository: str,
        num_concurrent: int,
    ) -> None:
        """Property 14: Concurrent updates - exactly one succeeds.

        *For any* set of concurrent update attempts on the same pipeline
        state, exactly one SHALL succeed and all others SHALL fail.

        **Validates: Requirement 8.5**
        """
        repo = InMemoryStateRepository()
        
        async def test():
            # Create initial state
            now = datetime.now(timezone.utc)
            state = PipelineState(
                issue_id=issue_id,
                repository=repository,
                current_stage=PipelineStage.PENDING,
                state_history=[],
                created_at=now,
                updated_at=now,
                version=1,
            )
            await repo.save(state)
            
            # Simulate concurrent updates by creating multiple update attempts
            # all based on the same initial version
            update_results = []
            
            for i in range(num_concurrent):
                updated_state = PipelineState(
                    issue_id=issue_id,
                    repository=repository,
                    current_stage=PipelineStage.INTAKE,
                    state_history=[
                        StateTransition(
                            from_stage=PipelineStage.PENDING,
                            to_stage=PipelineStage.INTAKE,
                            timestamp=now,
                            details={"attempt": i},
                        )
                    ],
                    created_at=now,
                    updated_at=now,
                    version=2,  # All attempts use version 2
                )
                
                success = await repo.update_with_version(updated_state)
                update_results.append(success)
            
            # Exactly one should succeed
            success_count = sum(1 for r in update_results if r)
            assert success_count == 1, (
                f"Expected exactly 1 success, got {success_count} "
                f"out of {num_concurrent} attempts"
            )
            
            # Final version should be 2
            final_state = await repo.get(issue_id)
            assert final_state is not None
            assert final_state.version == 2
        
        run_async(test())


    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_sequential_updates_all_succeed(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 14: Sequential updates with correct versions succeed.

        *For any* sequence of updates where each uses the correct version,
        all updates SHALL succeed.

        **Validates: Requirement 8.5**
        """
        repo = InMemoryStateRepository()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state
            state = await machine.create(issue_id, repository)
            assert state.version == 1
            
            # Perform sequential transitions
            state = await machine.transition(issue_id, PipelineStage.INTAKE)
            assert state.version == 2
            
            state = await machine.transition(issue_id, PipelineStage.PROVISIONING)
            assert state.version == 3
            
            state = await machine.transition(issue_id, PipelineStage.IMPLEMENTATION)
            assert state.version == 4
            
            state = await machine.transition(issue_id, PipelineStage.PR_CREATION)
            assert state.version == 5
            
            state = await machine.transition(issue_id, PipelineStage.COMPLETED)
            assert state.version == 6
            
            # Verify final state
            final = await repo.get(issue_id)
            assert final is not None
            assert final.version == 6
            assert final.current_stage == PipelineStage.COMPLETED
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_update_nonexistent_state_fails(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 14: Update on nonexistent state fails.

        *For any* update attempt on a state that doesn't exist,
        the update SHALL fail (return False).

        **Validates: Requirement 8.5**
        """
        repo = InMemoryStateRepository()
        
        async def test():
            # Try to update a state that doesn't exist
            now = datetime.now(timezone.utc)
            state = PipelineState(
                issue_id=issue_id,
                repository=repository,
                current_stage=PipelineStage.INTAKE,
                state_history=[],
                created_at=now,
                updated_at=now,
                version=2,
            )
            
            success = await repo.update_with_version(state)
            assert not success, "Update on nonexistent state should fail"
        
        run_async(test())

    @given(
        issue_id=valid_issue_id(),
        repository=valid_repository(),
    )
    @settings(max_examples=100)
    def test_version_conflict_error_raised_by_machine(
        self,
        issue_id: str,
        repository: str,
    ) -> None:
        """Property 14: State machine raises VersionConflictError.

        *For any* concurrent modification detected by the state machine,
        a VersionConflictError SHALL be raised.

        **Validates: Requirement 8.5**
        """
        from src.pipeline.state.machine import VersionConflictError
        
        # Create a custom repository that simulates concurrent modification
        class ConcurrentModificationRepo(InMemoryStateRepository):
            """Repository that simulates concurrent modification."""
            
            def __init__(self):
                super().__init__()
                self._update_count = 0
            
            async def update_with_version(self, state: PipelineState) -> bool:
                """Simulate concurrent modification by always failing."""
                # First call succeeds to set up state, subsequent calls fail
                self._update_count += 1
                if self._update_count > 1:
                    # Simulate version conflict
                    return False
                return await super().update_with_version(state)
        
        repo = ConcurrentModificationRepo()
        machine = PipelineStateMachine(repo)
        
        async def test():
            # Create state
            await machine.create(issue_id, repository)
            
            # First transition succeeds
            await machine.transition(issue_id, PipelineStage.INTAKE)
            
            # Second transition should fail with version conflict
            with pytest.raises(VersionConflictError) as exc_info:
                await machine.transition(issue_id, PipelineStage.PROVISIONING)
            
            assert exc_info.value.issue_id == issue_id
        
        run_async(test())
