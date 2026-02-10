"""Pipeline state machine models.

This module defines the data models for the pipeline state machine, including:
- PipelineStage: Enum of all pipeline stages
- StateTransition: Record of a state transition with timestamp and details
- PipelineState: Complete state of an issue in the pipeline
- VALID_TRANSITIONS: Map defining allowed state transitions

Requirements:
- 7.1: Track issues through stages: pending, intake, clarification,
       provisioning, implementation, pr_creation, completed, failed
- 7.2: Enforce valid state transitions

The models use Pydantic for validation, consistent with the pipeline's
approach in webhook/models.py and config.py.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PipelineStage(str, Enum):
    """Pipeline stages that an issue progresses through.

    The pipeline follows a linear progression with branching for clarification
    and failure handling. Each stage represents a discrete step in the
    autonomous development workflow.

    Stage Flow:
        pending → intake → [clarification ↔ intake] → provisioning
        → implementation → pr_creation → completed

    Any stage can transition to 'failed'. The 'failed' stage can transition
    back to 'pending' for manual recovery.

    Attributes:
        PENDING: Issue received, awaiting intake processing.
        INTAKE: Issue being classified and analyzed by LLM.
        CLARIFICATION: Issue needs more detail; waiting for user response.
        PROVISIONING: Creating workspace with required packages and context.
        IMPLEMENTATION: Kiro CLI executing implementation task.
        PR_CREATION: Creating pull request with implementation results.
        COMPLETED: Pipeline finished successfully; PR created.
        FAILED: Pipeline encountered an error; requires manual intervention.
    """

    PENDING = "pending"
    INTAKE = "intake"
    CLARIFICATION = "clarification"
    PROVISIONING = "provisioning"
    IMPLEMENTATION = "implementation"
    PR_CREATION = "pr_creation"
    COMPLETED = "completed"
    FAILED = "failed"


class StateTransition(BaseModel):
    """Record of a state transition in the pipeline.

    Each transition captures the movement from one stage to another,
    along with a timestamp and optional details about the transition.
    This provides an audit trail for debugging and observability.

    Attributes:
        from_stage: The stage before the transition.
        to_stage: The stage after the transition.
        timestamp: When the transition occurred (UTC).
        details: Optional metadata about the transition (e.g., error info,
                 classification results, PR number).
    """

    from_stage: PipelineStage = Field(
        ...,
        description="The pipeline stage before this transition",
    )

    to_stage: PipelineStage = Field(
        ...,
        description="The pipeline stage after this transition",
    )

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the transition occurred (UTC timezone)",
    )

    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata about the transition",
    )


class PipelineState(BaseModel):
    """Complete state of an issue in the agent pipeline.

    This model represents the full state of an issue as it progresses
    through the pipeline. It includes the current stage, history of
    transitions, and associated data like classification results and
    workspace paths.

    The state is persisted to PostgreSQL and uses optimistic locking
    via the version field to prevent concurrent update conflicts.

    Attributes:
        issue_id: Canonical identifier in format "{owner}/{repo}#{number}".
        repository: Full repository path in format "{owner}/{repo}".
        current_stage: The current pipeline stage.
        state_history: Ordered list of all state transitions.
        classification: LLM classification results (issue type, requirements, etc.).
        workspace_path: Filesystem path to the provisioned workspace.
        pr_number: Pull request number if PR was created.
        error: Error message if pipeline failed.
        created_at: When the pipeline state was created (UTC).
        updated_at: When the pipeline state was last updated (UTC).
        version: Optimistic locking version for concurrent update protection.
    """

    issue_id: str = Field(
        ...,
        min_length=1,
        description='Canonical issue identifier in format "{owner}/{repo}#{number}"',
    )

    repository: str = Field(
        ...,
        min_length=1,
        description='Full repository path in format "{owner}/{repo}"',
    )

    current_stage: PipelineStage = Field(
        default=PipelineStage.PENDING,
        description="The current stage of the pipeline",
    )

    state_history: List[StateTransition] = Field(
        default_factory=list,
        description="Ordered list of all state transitions",
    )

    classification: Optional[Dict[str, Any]] = Field(
        default=None,
        description="LLM classification results (issue type, requirements, etc.)",
    )

    workspace_path: Optional[str] = Field(
        default=None,
        description="Filesystem path to the provisioned workspace",
    )

    pr_number: Optional[int] = Field(
        default=None,
        gt=0,
        description="Pull request number if PR was created",
    )

    error: Optional[str] = Field(
        default=None,
        description="Error message if pipeline failed",
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the pipeline state was created (UTC)",
    )

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the pipeline state was last updated (UTC)",
    )

    version: int = Field(
        default=1,
        ge=1,
        description="Optimistic locking version for concurrent update protection",
    )


# Valid state transitions map
#
# This map defines which stage transitions are allowed. The state machine
# enforces these transitions to ensure pipeline integrity.
#
# Key design decisions:
# - Any stage can transition to FAILED (error handling)
# - FAILED can only transition to PENDING (manual recovery)
# - COMPLETED is a terminal state (no outgoing transitions)
# - CLARIFICATION can loop back to INTAKE (re-evaluation after user response)
# - INTAKE can skip CLARIFICATION if issue is complete enough
#
# Requirements:
# - 7.1: Track issues through all defined stages
# - 7.2: Enforce valid state transitions
VALID_TRANSITIONS: Dict[PipelineStage, List[PipelineStage]] = {
    # PENDING: Initial state, can start intake or fail immediately
    PipelineStage.PENDING: [
        PipelineStage.INTAKE,
        PipelineStage.FAILED,
    ],
    # INTAKE: After classification, may need clarification, proceed to
    # provisioning, or fail
    PipelineStage.INTAKE: [
        PipelineStage.CLARIFICATION,
        PipelineStage.PROVISIONING,
        PipelineStage.FAILED,
    ],
    # CLARIFICATION: After user responds, re-evaluate (back to intake),
    # proceed if complete, or fail
    PipelineStage.CLARIFICATION: [
        PipelineStage.INTAKE,
        PipelineStage.PROVISIONING,
        PipelineStage.FAILED,
    ],
    # PROVISIONING: After workspace created, proceed to implementation or fail
    PipelineStage.PROVISIONING: [
        PipelineStage.IMPLEMENTATION,
        PipelineStage.FAILED,
    ],
    # IMPLEMENTATION: After Kiro completes, create PR or fail
    PipelineStage.IMPLEMENTATION: [
        PipelineStage.PR_CREATION,
        PipelineStage.FAILED,
    ],
    # PR_CREATION: After PR created, complete or fail
    PipelineStage.PR_CREATION: [
        PipelineStage.COMPLETED,
        PipelineStage.FAILED,
    ],
    # COMPLETED: Terminal state, no outgoing transitions
    PipelineStage.COMPLETED: [],
    # FAILED: Can only recover to PENDING for manual retry
    PipelineStage.FAILED: [
        PipelineStage.PENDING,
    ],
}


def is_valid_transition(from_stage: PipelineStage, to_stage: PipelineStage) -> bool:
    """Check if a state transition is valid.

    This function validates whether transitioning from one stage to another
    is allowed according to the VALID_TRANSITIONS map.

    Args:
        from_stage: The current pipeline stage.
        to_stage: The target pipeline stage.

    Returns:
        bool: True if the transition is valid, False otherwise.

    Example:
        >>> is_valid_transition(PipelineStage.PENDING, PipelineStage.INTAKE)
        True
        >>> is_valid_transition(PipelineStage.COMPLETED, PipelineStage.PENDING)
        False
    """
    valid_targets = VALID_TRANSITIONS.get(from_stage, [])
    return to_stage in valid_targets


def is_terminal_stage(stage: PipelineStage) -> bool:
    """Check if a stage is terminal (has no outgoing transitions).

    Terminal stages are end states where the pipeline has finished
    processing, either successfully (COMPLETED) or unsuccessfully
    (FAILED, though FAILED can recover to PENDING).

    Args:
        stage: The pipeline stage to check.

    Returns:
        bool: True if the stage has no valid outgoing transitions.

    Example:
        >>> is_terminal_stage(PipelineStage.COMPLETED)
        True
        >>> is_terminal_stage(PipelineStage.INTAKE)
        False
    """
    return len(VALID_TRANSITIONS.get(stage, [])) == 0
