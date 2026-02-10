"""Pipeline event models for observability.

This module defines the data models for pipeline events, including:
- EventType: Enum of all event types emitted by the pipeline
- PipelineEvent: Structured event with all required metadata

Events are emitted for monitoring, alerting, and debugging purposes.
They provide visibility into pipeline health and issue progression.

Requirements:
- 9.1: Emit events for: state transitions, errors, completions, timeouts
- 9.2: Events SHALL include: event_type, issue_id, repository, timestamp, details

The models use Pydantic for validation, consistent with the pipeline's
approach in state/models.py and webhook/models.py.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Types of events emitted by the agent pipeline.

    The pipeline emits events at key points during issue processing
    to enable monitoring, alerting, and debugging. Each event type
    represents a distinct category of pipeline activity.

    Event Categories:
        STATE_TRANSITION: Emitted when an issue moves between pipeline stages.
            Used for tracking issue progression and identifying bottlenecks.

        ERROR: Emitted when an error occurs during processing.
            Used for alerting and debugging failed operations.

        COMPLETION: Emitted when an issue successfully completes the pipeline.
            Used for success metrics and workflow completion tracking.

        TIMEOUT: Emitted when an operation exceeds its time limit.
            Used for identifying slow operations and resource issues.

    Attributes:
        STATE_TRANSITION: Issue moved from one pipeline stage to another.
        ERROR: An error occurred during pipeline processing.
        COMPLETION: Issue successfully completed the entire pipeline.
        TIMEOUT: An operation timed out (e.g., Kiro CLI, LLM call).
    """

    STATE_TRANSITION = "state_transition"
    ERROR = "error"
    COMPLETION = "completion"
    TIMEOUT = "timeout"


class PipelineEvent(BaseModel):
    """Structured event emitted by the agent pipeline.

    Pipeline events provide observability into issue processing. Each event
    captures the event type, affected issue, and contextual details. Events
    are designed for easy parsing by monitoring tools and can be emitted
    to various sinks (Kubernetes events, metrics, message queues).

    The event structure supports:
    - Filtering by event_type for targeted alerting
    - Grouping by repository for per-repo dashboards
    - Correlation by issue_id for end-to-end tracing
    - Rich context via the details field for debugging

    Attributes:
        event_type: The category of event (state transition, error, etc.).
        issue_id: Canonical identifier in format "{owner}/{repo}#{number}".
        repository: Full repository path in format "{owner}/{repo}".
        timestamp: When the event occurred (UTC timezone).
        details: Additional context specific to the event type.

    Example:
        >>> event = PipelineEvent(
        ...     event_type=EventType.STATE_TRANSITION,
        ...     issue_id="org/repo#123",
        ...     repository="org/repo",
        ...     details={
        ...         "from_stage": "intake",
        ...         "to_stage": "provisioning",
        ...         "classification": {"issue_type": "feature"}
        ...     }
        ... )

    Details Field Conventions:
        For STATE_TRANSITION events:
            - from_stage: Previous pipeline stage
            - to_stage: New pipeline stage
            - classification: Classification results (if transitioning from intake)

        For ERROR events:
            - error_message: Human-readable error description
            - error_type: Exception class name or error category
            - stage: Pipeline stage where error occurred
            - stack_trace: Optional stack trace for debugging

        For COMPLETION events:
            - pr_number: Created pull request number
            - pr_url: URL to the pull request
            - duration_seconds: Total processing time

        For TIMEOUT events:
            - operation: Name of the operation that timed out
            - timeout_seconds: Configured timeout value
            - stage: Pipeline stage where timeout occurred
    """

    event_type: EventType = Field(
        ...,
        description="The category of event being emitted",
    )

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

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the event occurred (UTC timezone)",
    )

    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context specific to the event type",
    )

    class Config:
        """Pydantic model configuration."""

        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    def to_log_dict(self) -> Dict[str, Any]:
        """Convert event to a dictionary suitable for structured logging.

        Returns a flat dictionary with all event fields, suitable for
        JSON logging or metrics emission. The timestamp is converted
        to ISO format string.

        Returns:
            Dict[str, Any]: Flat dictionary representation of the event.

        Example:
            >>> event = PipelineEvent(
            ...     event_type=EventType.ERROR,
            ...     issue_id="org/repo#123",
            ...     repository="org/repo",
            ...     details={"error_message": "LLM timeout"}
            ... )
            >>> log_dict = event.to_log_dict()
            >>> log_dict["event_type"]
            'error'
        """
        return {
            "event_type": self.event_type.value,
            "issue_id": self.issue_id,
            "repository": self.repository,
            "timestamp": self.timestamp.isoformat(),
            **self.details,
        }
