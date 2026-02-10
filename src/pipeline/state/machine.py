"""Pipeline state machine implementation.

This module implements the PipelineStateMachine class that manages issue
progression through pipeline stages with validation, timestamp recording,
and error handling.

Requirements:
- 7.2: Enforce valid state transitions
- 7.3: Record timestamps for each state transition
- 7.4: Store error details when transitioning to `failed` state
- 7.6: Support manual state transitions for recovery

The state machine depends on a StateRepository interface for persistence,
which is implemented separately in repository.py (task 4.2).
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from src.pipeline.state.models import (
    PipelineStage,
    PipelineState,
    StateTransition,
    is_valid_transition,
)


logger = logging.getLogger(__name__)


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted.

    This exception is raised when the state machine rejects a transition
    that violates the valid transitions map.

    Attributes:
        from_stage: The current stage.
        to_stage: The attempted target stage.
        message: Human-readable error message.
    """

    def __init__(
        self,
        from_stage: PipelineStage,
        to_stage: PipelineStage,
        message: Optional[str] = None,
    ):
        self.from_stage = from_stage
        self.to_stage = to_stage
        self.message = message or (
            f"Invalid transition from {from_stage.value} to {to_stage.value}"
        )
        super().__init__(self.message)


class StateNotFoundError(Exception):
    """Raised when a pipeline state is not found.

    This exception is raised when attempting to transition or retrieve
    a state that doesn't exist in the repository.

    Attributes:
        issue_id: The issue ID that was not found.
    """

    def __init__(self, issue_id: str):
        self.issue_id = issue_id
        super().__init__(f"Pipeline state not found for issue: {issue_id}")


class VersionConflictError(Exception):
    """Raised when optimistic locking detects a concurrent update.

    This exception is raised when attempting to update a state that has
    been modified by another process since it was read.

    Attributes:
        issue_id: The issue ID with the conflict.
        expected_version: The version that was expected.
        actual_version: The actual version in the database.
    """

    def __init__(
        self,
        issue_id: str,
        expected_version: int,
        actual_version: Optional[int] = None,
    ):
        self.issue_id = issue_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        message = f"Version conflict for issue {issue_id}: expected {expected_version}"
        if actual_version is not None:
            message += f", found {actual_version}"
        super().__init__(message)


@runtime_checkable
class StateRepository(Protocol):
    """Protocol defining the interface for pipeline state persistence.

    This protocol defines the contract that any state repository implementation
    must fulfill. The actual PostgreSQL implementation is in repository.py.

    The repository is responsible for:
    - Persisting pipeline states to storage
    - Retrieving states by issue ID or stage
    - Implementing optimistic locking via version field
    """

    async def save(self, state: PipelineState) -> None:
        """Save or create a new pipeline state.

        Args:
            state: The pipeline state to save.

        Raises:
            Exception: If the save operation fails.
        """
        ...

    async def get(self, issue_id: str) -> Optional[PipelineState]:
        """Get pipeline state by issue ID.

        Args:
            issue_id: The canonical issue identifier.

        Returns:
            The pipeline state if found, None otherwise.
        """
        ...

    async def list_by_stage(self, stage: PipelineStage) -> List[PipelineState]:
        """List all pipeline states in a given stage.

        Args:
            stage: The pipeline stage to filter by.

        Returns:
            List of pipeline states in the specified stage.
        """
        ...

    async def update_with_version(self, state: PipelineState) -> bool:
        """Update state with optimistic locking.

        This method updates the state only if the version matches,
        preventing concurrent update conflicts.

        Args:
            state: The pipeline state to update (with incremented version).

        Returns:
            True if update succeeded, False if version conflict.

        Raises:
            Exception: If the update operation fails for reasons other
                       than version conflict.
        """
        ...


class PipelineStateMachine:
    """State machine for managing pipeline issue progression.

    This class implements the core state machine logic for the agent
    orchestration pipeline. It validates transitions, records timestamps,
    stores error details, and supports manual recovery.

    The state machine enforces the following invariants:
    - Only valid transitions (as defined in VALID_TRANSITIONS) are allowed
    - Every transition is recorded with a timestamp in state_history
    - Transitions to FAILED must include error details
    - The FAILED state can transition to PENDING for manual recovery
    - Each state update increments the version for optimistic locking

    Attributes:
        repository: The state repository for persistence.

    Example:
        >>> repository = PostgresStateRepository(connection_string)
        >>> machine = PipelineStateMachine(repository)
        >>> state = await machine.create("owner/repo#123", "owner/repo")
        >>> state = await machine.transition(
        ...     "owner/repo#123",
        ...     PipelineStage.INTAKE,
        ...     details={"started_by": "webhook"}
        ... )
    """

    def __init__(self, repository: StateRepository):
        """Initialize the state machine with a repository.

        Args:
            repository: The state repository for persistence.
        """
        self.repository = repository

    async def create(self, issue_id: str, repository: str) -> PipelineState:
        """Create a new pipeline state for an issue.

        Creates a new pipeline state in the PENDING stage. The state is
        immediately persisted to the repository.

        Args:
            issue_id: Canonical issue identifier in format "{owner}/{repo}#{number}".
            repository: Full repository path in format "{owner}/{repo}".

        Returns:
            The newly created pipeline state.

        Raises:
            ValueError: If issue_id or repository is empty.
            Exception: If persistence fails.

        Example:
            >>> state = await machine.create("owner/repo#123", "owner/repo")
            >>> assert state.current_stage == PipelineStage.PENDING
        """
        if not issue_id:
            raise ValueError("issue_id cannot be empty")
        if not repository:
            raise ValueError("repository cannot be empty")

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

        logger.info(
            "Creating pipeline state",
            extra={
                "issue_id": issue_id,
                "repository": repository,
                "stage": PipelineStage.PENDING.value,
            },
        )

        await self.repository.save(state)

        return state

    async def transition(
        self,
        issue_id: str,
        to_stage: PipelineStage,
        details: Optional[Dict[str, Any]] = None,
    ) -> PipelineState:
        """Transition an issue to a new pipeline stage.

        This method validates the transition, records a timestamp in the
        state history, handles error storage for FAILED transitions, and
        persists the updated state with optimistic locking.

        Args:
            issue_id: The canonical issue identifier.
            to_stage: The target pipeline stage.
            details: Optional metadata about the transition. For FAILED
                     transitions, should include an "error" key with the
                     error message.

        Returns:
            The updated pipeline state.

        Raises:
            StateNotFoundError: If the issue doesn't exist.
            InvalidTransitionError: If the transition is not valid.
            VersionConflictError: If a concurrent update occurred.

        Example:
            >>> # Normal transition
            >>> state = await machine.transition(
            ...     "owner/repo#123",
            ...     PipelineStage.INTAKE
            ... )
            >>>
            >>> # Transition to failed with error
            >>> state = await machine.transition(
            ...     "owner/repo#123",
            ...     PipelineStage.FAILED,
            ...     details={"error": "LLM timeout after 30s"}
            ... )
            >>>
            >>> # Manual recovery from failed
            >>> state = await machine.transition(
            ...     "owner/repo#123",
            ...     PipelineStage.PENDING,
            ...     details={"recovery_reason": "Manual retry requested"}
            ... )
        """
        details = details or {}

        # Retrieve current state
        state = await self.repository.get(issue_id)
        if state is None:
            raise StateNotFoundError(issue_id)

        from_stage = state.current_stage

        # Validate transition
        if not is_valid_transition(from_stage, to_stage):
            logger.warning(
                "Invalid state transition attempted",
                extra={
                    "issue_id": issue_id,
                    "from_stage": from_stage.value,
                    "to_stage": to_stage.value,
                },
            )
            raise InvalidTransitionError(from_stage, to_stage)

        # Record timestamp for transition
        now = datetime.now(timezone.utc)

        # Create transition record
        transition = StateTransition(
            from_stage=from_stage,
            to_stage=to_stage,
            timestamp=now,
            details=details,
        )

        # Handle FAILED state - store error details
        error_message: Optional[str] = None
        if to_stage == PipelineStage.FAILED:
            error_message = details.get("error")
            if not error_message:
                # Require error message for FAILED transitions
                error_message = "Unknown error (no details provided)"
                logger.warning(
                    "Transition to FAILED without error details",
                    extra={"issue_id": issue_id},
                )

        # Handle recovery from FAILED - clear error
        if from_stage == PipelineStage.FAILED and to_stage == PipelineStage.PENDING:
            error_message = None
            logger.info(
                "Manual recovery initiated",
                extra={
                    "issue_id": issue_id,
                    "recovery_reason": details.get("recovery_reason", "Not specified"),
                },
            )

        # Update state
        # Create a new state with updated fields
        updated_state = PipelineState(
            issue_id=state.issue_id,
            repository=state.repository,
            current_stage=to_stage,
            state_history=state.state_history + [transition],
            classification=state.classification,
            workspace_path=state.workspace_path,
            pr_number=state.pr_number,
            error=error_message if to_stage == PipelineStage.FAILED else state.error
            if to_stage != PipelineStage.PENDING
            else None,
            created_at=state.created_at,
            updated_at=now,
            version=state.version + 1,
        )

        logger.info(
            "Transitioning pipeline state",
            extra={
                "issue_id": issue_id,
                "from_stage": from_stage.value,
                "to_stage": to_stage.value,
                "version": updated_state.version,
            },
        )

        # Persist with optimistic locking
        success = await self.repository.update_with_version(updated_state)
        if not success:
            raise VersionConflictError(issue_id, state.version)

        return updated_state

    async def get(self, issue_id: str) -> Optional[PipelineState]:
        """Get the current state for an issue.

        Args:
            issue_id: The canonical issue identifier.

        Returns:
            The pipeline state if found, None otherwise.

        Example:
            >>> state = await machine.get("owner/repo#123")
            >>> if state:
            ...     print(f"Current stage: {state.current_stage.value}")
        """
        return await self.repository.get(issue_id)

    async def list_by_stage(self, stage: PipelineStage) -> List[PipelineState]:
        """List all issues in a given pipeline stage.

        This method is useful for monitoring and for finding issues
        that need processing (e.g., all PENDING issues).

        Args:
            stage: The pipeline stage to filter by.

        Returns:
            List of pipeline states in the specified stage.

        Example:
            >>> pending = await machine.list_by_stage(PipelineStage.PENDING)
            >>> print(f"Found {len(pending)} pending issues")
        """
        return await self.repository.list_by_stage(stage)

    async def set_classification(
        self,
        issue_id: str,
        classification: Dict[str, Any],
    ) -> PipelineState:
        """Update the classification data for an issue.

        This is a convenience method for storing LLM classification results
        without changing the pipeline stage.

        Args:
            issue_id: The canonical issue identifier.
            classification: The classification data from the LLM.

        Returns:
            The updated pipeline state.

        Raises:
            StateNotFoundError: If the issue doesn't exist.
            VersionConflictError: If a concurrent update occurred.
        """
        state = await self.repository.get(issue_id)
        if state is None:
            raise StateNotFoundError(issue_id)

        now = datetime.now(timezone.utc)

        updated_state = PipelineState(
            issue_id=state.issue_id,
            repository=state.repository,
            current_stage=state.current_stage,
            state_history=state.state_history,
            classification=classification,
            workspace_path=state.workspace_path,
            pr_number=state.pr_number,
            error=state.error,
            created_at=state.created_at,
            updated_at=now,
            version=state.version + 1,
        )

        success = await self.repository.update_with_version(updated_state)
        if not success:
            raise VersionConflictError(issue_id, state.version)

        return updated_state

    async def set_workspace_path(
        self,
        issue_id: str,
        workspace_path: str,
    ) -> PipelineState:
        """Update the workspace path for an issue.

        This is a convenience method for storing the provisioned workspace
        path without changing the pipeline stage.

        Args:
            issue_id: The canonical issue identifier.
            workspace_path: The filesystem path to the workspace.

        Returns:
            The updated pipeline state.

        Raises:
            StateNotFoundError: If the issue doesn't exist.
            VersionConflictError: If a concurrent update occurred.
        """
        state = await self.repository.get(issue_id)
        if state is None:
            raise StateNotFoundError(issue_id)

        now = datetime.now(timezone.utc)

        updated_state = PipelineState(
            issue_id=state.issue_id,
            repository=state.repository,
            current_stage=state.current_stage,
            state_history=state.state_history,
            classification=state.classification,
            workspace_path=workspace_path,
            pr_number=state.pr_number,
            error=state.error,
            created_at=state.created_at,
            updated_at=now,
            version=state.version + 1,
        )

        success = await self.repository.update_with_version(updated_state)
        if not success:
            raise VersionConflictError(issue_id, state.version)

        return updated_state

    async def set_pr_number(
        self,
        issue_id: str,
        pr_number: int,
    ) -> PipelineState:
        """Update the PR number for an issue.

        This is a convenience method for storing the created PR number
        without changing the pipeline stage.

        Args:
            issue_id: The canonical issue identifier.
            pr_number: The pull request number.

        Returns:
            The updated pipeline state.

        Raises:
            StateNotFoundError: If the issue doesn't exist.
            VersionConflictError: If a concurrent update occurred.
            ValueError: If pr_number is not positive.
        """
        if pr_number <= 0:
            raise ValueError("pr_number must be positive")

        state = await self.repository.get(issue_id)
        if state is None:
            raise StateNotFoundError(issue_id)

        now = datetime.now(timezone.utc)

        updated_state = PipelineState(
            issue_id=state.issue_id,
            repository=state.repository,
            current_stage=state.current_stage,
            state_history=state.state_history,
            classification=state.classification,
            workspace_path=state.workspace_path,
            pr_number=pr_number,
            error=state.error,
            created_at=state.created_at,
            updated_at=now,
            version=state.version + 1,
        )

        success = await self.repository.update_with_version(updated_state)
        if not success:
            raise VersionConflictError(issue_id, state.version)

        return updated_state
