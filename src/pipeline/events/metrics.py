"""Prometheus metrics for pipeline observability.

This module provides Prometheus metrics for the agent pipeline, enabling
monitoring, alerting, and dashboards. Metrics are exposed at the `/metrics`
endpoint in Prometheus format.

Metrics Defined:
- pipeline_issues_processed_total: Counter of total issues processed
- pipeline_issues_failed_total: Counter of failed issues
- pipeline_processing_duration_seconds: Histogram of processing time
- pipeline_issues_by_stage: Gauge of current issues per stage

The MetricsEventEmitter integrates with the event emission system to
automatically update metrics based on pipeline events.

Requirements:
- 9.5: Emit metrics: issues_processed, issues_failed, average_processing_time,
       issues_by_state
- 9.6: Metrics SHALL be exposed in Prometheus format at `/metrics` endpoint

Source:
- src/pipeline/events/models.py (PipelineEvent, EventType)
- src/pipeline/state/models.py (PipelineStage)
"""

import logging
from typing import Optional

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from src.pipeline.events.emitter import EventEmitter
from src.pipeline.events.models import EventType, PipelineEvent


logger = logging.getLogger(__name__)


# Default bucket boundaries for processing duration histogram
# Covers range from 1 second to 1 hour with exponential growth
DEFAULT_DURATION_BUCKETS = (
    1.0,      # 1 second
    5.0,      # 5 seconds
    10.0,     # 10 seconds
    30.0,     # 30 seconds
    60.0,     # 1 minute
    120.0,    # 2 minutes
    300.0,    # 5 minutes
    600.0,    # 10 minutes
    1800.0,   # 30 minutes
    3600.0,   # 1 hour
)


# Pipeline stages for the gauge metric
# These match PipelineStage enum values from state/models.py
PIPELINE_STAGES = (
    "pending",
    "intake",
    "clarification",
    "provisioning",
    "implementation",
    "pr_creation",
    "completed",
    "failed",
)


class PipelineMetrics:
    """Container for all pipeline Prometheus metrics.

    This class encapsulates all Prometheus metrics used by the pipeline.
    It provides a clean interface for metric operations and supports
    custom registries for testing.

    Metrics:
        issues_processed_total: Counter tracking total issues processed.
            Labels: repository, result (success/failure)

        issues_failed_total: Counter tracking failed issues.
            Labels: repository, stage (where failure occurred)

        processing_duration_seconds: Histogram tracking processing time.
            Labels: repository

        issues_by_stage: Gauge tracking current count of issues per stage.
            Labels: stage

    Attributes:
        registry: The Prometheus registry for these metrics.
        issues_processed_total: Counter for processed issues.
        issues_failed_total: Counter for failed issues.
        processing_duration_seconds: Histogram for processing duration.
        issues_by_stage: Gauge for issues per stage.

    Example:
        >>> metrics = PipelineMetrics()
        >>> metrics.issues_processed_total.labels(
        ...     repository="org/repo",
        ...     result="success"
        ... ).inc()
        >>> metrics.processing_duration_seconds.labels(
        ...     repository="org/repo"
        ... ).observe(45.5)
    """

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        """Initialize pipeline metrics.

        Args:
            registry: Optional Prometheus registry. If None, uses the
                      default REGISTRY. Pass a custom registry for testing.
        """
        self.registry = registry or REGISTRY

        # Counter: Total issues processed
        # Tracks all issues that have completed processing (success or failure)
        self.issues_processed_total = Counter(
            "pipeline_issues_processed_total",
            "Total number of issues processed by the pipeline",
            labelnames=["repository", "result"],
            registry=self.registry,
        )

        # Counter: Total issues failed
        # Tracks issues that failed, with the stage where failure occurred
        self.issues_failed_total = Counter(
            "pipeline_issues_failed_total",
            "Total number of issues that failed during processing",
            labelnames=["repository", "stage"],
            registry=self.registry,
        )

        # Histogram: Processing duration
        # Tracks how long issues take to process from start to completion
        self.processing_duration_seconds = Histogram(
            "pipeline_processing_duration_seconds",
            "Time spent processing issues in seconds",
            labelnames=["repository"],
            buckets=DEFAULT_DURATION_BUCKETS,
            registry=self.registry,
        )

        # Gauge: Issues by stage
        # Tracks current count of issues in each pipeline stage
        self.issues_by_stage = Gauge(
            "pipeline_issues_by_stage",
            "Current number of issues in each pipeline stage",
            labelnames=["stage"],
            registry=self.registry,
        )

        # Initialize gauge values to 0 for all stages
        for stage in PIPELINE_STAGES:
            self.issues_by_stage.labels(stage=stage).set(0)

    def record_issue_processed(
        self,
        repository: str,
        success: bool,
    ) -> None:
        """Record that an issue was processed.

        Args:
            repository: The repository in format "{owner}/{repo}".
            success: Whether processing completed successfully.
        """
        result = "success" if success else "failure"
        self.issues_processed_total.labels(
            repository=repository,
            result=result,
        ).inc()

    def record_issue_failed(
        self,
        repository: str,
        stage: str,
    ) -> None:
        """Record that an issue failed at a specific stage.

        Args:
            repository: The repository in format "{owner}/{repo}".
            stage: The pipeline stage where failure occurred.
        """
        self.issues_failed_total.labels(
            repository=repository,
            stage=stage,
        ).inc()

    def record_processing_duration(
        self,
        repository: str,
        duration_seconds: float,
    ) -> None:
        """Record the processing duration for an issue.

        Args:
            repository: The repository in format "{owner}/{repo}".
            duration_seconds: Time taken to process the issue.
        """
        self.processing_duration_seconds.labels(
            repository=repository,
        ).observe(duration_seconds)

    def update_stage_count(
        self,
        stage: str,
        delta: int,
    ) -> None:
        """Update the count of issues in a stage.

        Args:
            stage: The pipeline stage to update.
            delta: The change in count (+1 for entering, -1 for leaving).
        """
        if stage in PIPELINE_STAGES:
            current = self.issues_by_stage.labels(stage=stage)._value.get()
            new_value = max(0, current + delta)  # Prevent negative counts
            self.issues_by_stage.labels(stage=stage).set(new_value)

    def set_stage_count(
        self,
        stage: str,
        count: int,
    ) -> None:
        """Set the absolute count of issues in a stage.

        Args:
            stage: The pipeline stage to update.
            count: The new count value.
        """
        if stage in PIPELINE_STAGES:
            self.issues_by_stage.labels(stage=stage).set(max(0, count))


# Global metrics instance for the default registry
# This is used by MetricsEventEmitter and generate_metrics_output()
_default_metrics: Optional[PipelineMetrics] = None


def get_metrics(registry: Optional[CollectorRegistry] = None) -> PipelineMetrics:
    """Get or create the pipeline metrics instance.

    This function provides access to the global metrics instance for the
    default registry, or creates a new instance for a custom registry.

    Args:
        registry: Optional Prometheus registry. If None, returns the
                  global metrics instance for the default registry.

    Returns:
        PipelineMetrics: The metrics instance.

    Example:
        >>> metrics = get_metrics()
        >>> metrics.record_issue_processed("org/repo", success=True)
    """
    global _default_metrics

    if registry is not None:
        # Custom registry requested, create new instance
        return PipelineMetrics(registry=registry)

    if _default_metrics is None:
        _default_metrics = PipelineMetrics()

    return _default_metrics


def generate_metrics_output(registry: Optional[CollectorRegistry] = None) -> bytes:
    """Generate Prometheus metrics output for the /metrics endpoint.

    This function generates the metrics output in Prometheus text format,
    suitable for scraping by Prometheus server.

    Args:
        registry: Optional Prometheus registry. If None, uses the
                  default REGISTRY.

    Returns:
        bytes: Prometheus metrics in text format.

    Example:
        >>> output = generate_metrics_output()
        >>> # Returns bytes like:
        >>> # b'# HELP pipeline_issues_processed_total Total number of...
        >>> # # TYPE pipeline_issues_processed_total counter
        >>> # pipeline_issues_processed_total{repository="org/repo",...
    """
    target_registry = registry or REGISTRY
    return generate_latest(target_registry)


class MetricsEventEmitter(EventEmitter):
    """Event emitter that updates Prometheus metrics.

    This emitter integrates with the pipeline event system to automatically
    update Prometheus metrics based on pipeline events. It handles:

    - STATE_TRANSITION: Updates issues_by_stage gauge
    - ERROR: Increments issues_failed counter
    - COMPLETION: Increments issues_processed counter, records duration
    - TIMEOUT: Increments issues_failed counter with timeout stage

    The emitter extracts relevant information from event details to
    populate metric labels appropriately.

    Attributes:
        metrics: The PipelineMetrics instance to update.

    Example:
        >>> emitter = MetricsEventEmitter()
        >>> event = PipelineEvent(
        ...     event_type=EventType.COMPLETION,
        ...     issue_id="org/repo#123",
        ...     repository="org/repo",
        ...     details={"duration_seconds": 120.5}
        ... )
        >>> await emitter.emit(event)
        # Updates issues_processed_total and processing_duration_seconds
    """

    def __init__(
        self,
        metrics: Optional[PipelineMetrics] = None,
        registry: Optional[CollectorRegistry] = None,
    ):
        """Initialize the metrics event emitter.

        Args:
            metrics: Optional PipelineMetrics instance. If None, uses
                     the global metrics instance.
            registry: Optional Prometheus registry. Only used if metrics
                      is None.
        """
        if metrics is not None:
            self._metrics = metrics
        else:
            self._metrics = get_metrics(registry)

    @property
    def metrics(self) -> PipelineMetrics:
        """Get the metrics instance.

        Returns:
            PipelineMetrics: The metrics instance used by this emitter.
        """
        return self._metrics

    async def emit(self, event: PipelineEvent) -> None:
        """Update metrics based on the pipeline event.

        This method dispatches to specific handlers based on event type:
        - STATE_TRANSITION: Updates stage gauge
        - ERROR: Records failure
        - COMPLETION: Records success and duration
        - TIMEOUT: Records timeout failure

        Args:
            event: The pipeline event to process.
        """
        try:
            if event.event_type == EventType.STATE_TRANSITION:
                await self._handle_state_transition(event)
            elif event.event_type == EventType.ERROR:
                await self._handle_error(event)
            elif event.event_type == EventType.COMPLETION:
                await self._handle_completion(event)
            elif event.event_type == EventType.TIMEOUT:
                await self._handle_timeout(event)
        except Exception as e:
            logger.error(
                "Failed to update metrics for event %s: %s",
                event.event_type.value,
                str(e),
                extra={
                    "event_type": event.event_type.value,
                    "issue_id": event.issue_id,
                    "error": str(e),
                },
            )

    async def _handle_state_transition(self, event: PipelineEvent) -> None:
        """Handle state transition events.

        Updates the issues_by_stage gauge by decrementing the count for
        the previous stage and incrementing for the new stage.

        Args:
            event: The state transition event.
        """
        from_stage = event.details.get("from_stage")
        to_stage = event.details.get("to_stage")

        if from_stage:
            self._metrics.update_stage_count(from_stage, -1)

        if to_stage:
            self._metrics.update_stage_count(to_stage, +1)

    async def _handle_error(self, event: PipelineEvent) -> None:
        """Handle error events.

        Increments the issues_failed counter with the stage where the
        error occurred.

        Args:
            event: The error event.
        """
        stage = event.details.get("stage", "unknown")
        self._metrics.record_issue_failed(
            repository=event.repository,
            stage=stage,
        )

    async def _handle_completion(self, event: PipelineEvent) -> None:
        """Handle completion events.

        Increments the issues_processed counter and records the
        processing duration if available.

        Args:
            event: The completion event.
        """
        self._metrics.record_issue_processed(
            repository=event.repository,
            success=True,
        )

        duration = event.details.get("duration_seconds")
        if duration is not None:
            self._metrics.record_processing_duration(
                repository=event.repository,
                duration_seconds=float(duration),
            )

    async def _handle_timeout(self, event: PipelineEvent) -> None:
        """Handle timeout events.

        Records the timeout as a failure at the stage where it occurred.

        Args:
            event: The timeout event.
        """
        stage = event.details.get("stage", "unknown")
        self._metrics.record_issue_failed(
            repository=event.repository,
            stage=stage,
        )

