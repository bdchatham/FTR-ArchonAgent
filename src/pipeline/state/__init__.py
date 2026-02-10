"""Pipeline state machine and persistence.

This module manages issue progression through pipeline stages:
- pending → intake → clarification → provisioning
- → implementation → pr_creation → completed

State is persisted to PostgreSQL with optimistic locking for
concurrent update protection.
"""

from src.pipeline.state.models import (
    PipelineStage,
    PipelineState,
    StateTransition,
    VALID_TRANSITIONS,
    is_terminal_stage,
    is_valid_transition,
)
from src.pipeline.state.machine import (
    InvalidTransitionError,
    PipelineStateMachine,
    StateNotFoundError,
    StateRepository,
    VersionConflictError,
)
from src.pipeline.state.repository import (
    DatabaseError,
    PostgresStateRepository,
)

__all__ = [
    # Models
    "PipelineStage",
    "PipelineState",
    "StateTransition",
    "VALID_TRANSITIONS",
    "is_terminal_stage",
    "is_valid_transition",
    # State machine
    "InvalidTransitionError",
    "PipelineStateMachine",
    "StateNotFoundError",
    "StateRepository",
    "VersionConflictError",
    # Repository
    "DatabaseError",
    "PostgresStateRepository",
]
