"""Event emitter implementations for pipeline observability.

This module provides the event emission infrastructure for the agent pipeline.
It defines an abstract EventEmitter interface and concrete implementations
for different event sinks:

- LoggingEventEmitter: Emits events as structured log entries
- CompositeEventEmitter: Emits to multiple sinks simultaneously

The emitter abstraction allows the pipeline to emit events without coupling
to specific monitoring infrastructure. Events can be routed to logs, metrics,
Kubernetes events, or message queues based on configuration.

Requirements:
- 9.1: Emit events for: state transitions, errors, completions, timeouts
- 9.3: Emit events to a configurable event sink (Kubernetes events, metrics,
       or message queue)

Source:
- src/pipeline/events/models.py (PipelineEvent, EventType)
"""

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional

from src.pipeline.events.models import EventType, PipelineEvent


logger = logging.getLogger(__name__)


class EventSinkType(str, Enum):
    """Types of event sinks supported by the pipeline.

    The pipeline can emit events to multiple sink types simultaneously.
    Each sink type has different characteristics:

    - LOGGING: Structured log entries for debugging and audit trails
    - METRICS: Prometheus metrics for dashboards and alerting
    - KUBERNETES: Kubernetes events for cluster-native observability

    Attributes:
        LOGGING: Emit events as structured log entries.
        METRICS: Emit events as Prometheus metrics (counters, histograms).
        KUBERNETES: Emit events as Kubernetes Event resources.
    """

    LOGGING = "logging"
    METRICS = "metrics"
    KUBERNETES = "kubernetes"


class EventEmitter(ABC):
    """Abstract base class for pipeline event emitters.

    Event emitters are responsible for publishing pipeline events to
    external systems for monitoring, alerting, and debugging. The
    abstract interface allows different implementations for different
    event sinks (logs, metrics, Kubernetes events, message queues).

    Implementations should be:
    - Async-safe: emit() is called from async contexts
    - Non-blocking: emit() should not block pipeline processing
    - Fault-tolerant: emit() failures should not crash the pipeline

    Example:
        >>> class MyEmitter(EventEmitter):
        ...     async def emit(self, event: PipelineEvent) -> None:
        ...         # Send event to external system
        ...         pass
        ...
        ...     async def close(self) -> None:
        ...         # Cleanup resources
        ...         pass
    """

    @abstractmethod
    async def emit(self, event: PipelineEvent) -> None:
        """Emit a pipeline event.

        This method publishes the event to the configured sink. It should
        be non-blocking and fault-tolerant - failures should be logged
        but not propagated to the caller.

        Args:
            event: The pipeline event to emit.
        """
        pass

    async def close(self) -> None:
        """Close the emitter and release resources.

        Override this method to perform cleanup when the emitter is
        no longer needed. The default implementation does nothing.
        """
        pass


class LoggingEventEmitter(EventEmitter):
    """Event emitter that logs events using structured logging.

    This emitter writes pipeline events as structured log entries,
    suitable for log aggregation systems like ELK, Loki, or CloudWatch.
    Events are logged at different levels based on event type:

    - STATE_TRANSITION: INFO level
    - COMPLETION: INFO level
    - ERROR: ERROR level
    - TIMEOUT: WARNING level

    The emitter uses the standard Python logging module with extra
    fields for structured logging. Log aggregators can parse these
    fields for filtering and dashboards.

    Attributes:
        logger: The logger instance used for event emission.
        log_level_map: Mapping from event type to log level.

    Example:
        >>> emitter = LoggingEventEmitter()
        >>> event = PipelineEvent(
        ...     event_type=EventType.STATE_TRANSITION,
        ...     issue_id="org/repo#123",
        ...     repository="org/repo",
        ...     details={"from_stage": "intake", "to_stage": "provisioning"}
        ... )
        >>> await emitter.emit(event)
        # Logs: INFO - Pipeline event: state_transition for org/repo#123
    """

    def __init__(self, logger_name: Optional[str] = None):
        """Initialize the logging event emitter.

        Args:
            logger_name: Optional logger name. If not provided, uses
                         the module logger.
        """
        self._logger = (
            logging.getLogger(logger_name)
            if logger_name
            else logger
        )
        self._log_level_map = {
            EventType.STATE_TRANSITION: logging.INFO,
            EventType.COMPLETION: logging.INFO,
            EventType.ERROR: logging.ERROR,
            EventType.TIMEOUT: logging.WARNING,
        }

    async def emit(self, event: PipelineEvent) -> None:
        """Emit event as a structured log entry.

        The event is logged with all fields available as extra context
        for structured logging. The log level is determined by the
        event type.

        Args:
            event: The pipeline event to log.
        """
        log_level = self._log_level_map.get(event.event_type, logging.INFO)
        log_dict = event.to_log_dict()

        self._logger.log(
            log_level,
            "Pipeline event: %s for %s",
            event.event_type.value,
            event.issue_id,
            extra=log_dict,
        )


class CompositeEventEmitter(EventEmitter):
    """Event emitter that delegates to multiple child emitters.

    This emitter allows events to be sent to multiple sinks simultaneously.
    For example, events can be logged AND sent to metrics at the same time.
    Failures in one emitter do not affect others - each emitter is called
    independently and errors are logged but not propagated.

    The composite pattern enables flexible event routing without modifying
    the pipeline code. New sinks can be added by adding emitters to the
    composite.

    Attributes:
        emitters: List of child emitters to delegate to.

    Example:
        >>> logging_emitter = LoggingEventEmitter()
        >>> metrics_emitter = MetricsEventEmitter()  # From metrics.py
        >>> composite = CompositeEventEmitter([logging_emitter, metrics_emitter])
        >>> await composite.emit(event)  # Emits to both sinks
    """

    def __init__(self, emitters: Optional[List[EventEmitter]] = None):
        """Initialize the composite emitter with child emitters.

        Args:
            emitters: List of child emitters. If None, creates an empty list.
        """
        self._emitters: List[EventEmitter] = emitters or []

    def add_emitter(self, emitter: EventEmitter) -> None:
        """Add a child emitter to the composite.

        Args:
            emitter: The emitter to add.
        """
        self._emitters.append(emitter)

    def remove_emitter(self, emitter: EventEmitter) -> bool:
        """Remove a child emitter from the composite.

        Args:
            emitter: The emitter to remove.

        Returns:
            True if the emitter was found and removed, False otherwise.
        """
        try:
            self._emitters.remove(emitter)
            return True
        except ValueError:
            return False

    @property
    def emitters(self) -> List[EventEmitter]:
        """Get the list of child emitters.

        Returns:
            List of child emitters (read-only copy).
        """
        return list(self._emitters)

    async def emit(self, event: PipelineEvent) -> None:
        """Emit event to all child emitters.

        Each child emitter is called independently. Failures in one
        emitter do not affect others - errors are logged but not
        propagated. This ensures that a failing sink does not block
        event emission to other sinks.

        Args:
            event: The pipeline event to emit.
        """
        for emitter in self._emitters:
            try:
                await emitter.emit(event)
            except Exception as e:
                logger.error(
                    "Failed to emit event to %s: %s",
                    type(emitter).__name__,
                    str(e),
                    extra={
                        "emitter_type": type(emitter).__name__,
                        "event_type": event.event_type.value,
                        "issue_id": event.issue_id,
                        "error": str(e),
                    },
                )

    async def close(self) -> None:
        """Close all child emitters.

        Each child emitter's close() method is called. Failures are
        logged but do not prevent other emitters from being closed.
        """
        for emitter in self._emitters:
            try:
                await emitter.close()
            except Exception as e:
                logger.error(
                    "Failed to close emitter %s: %s",
                    type(emitter).__name__,
                    str(e),
                )


class NullEventEmitter(EventEmitter):
    """Event emitter that discards all events.

    This emitter is useful for testing or when event emission should
    be disabled. It implements the EventEmitter interface but does
    nothing with the events.

    Example:
        >>> emitter = NullEventEmitter()
        >>> await emitter.emit(event)  # Does nothing
    """

    async def emit(self, event: PipelineEvent) -> None:
        """Discard the event without any action.

        Args:
            event: The pipeline event (ignored).
        """
        pass


def create_event_emitter(
    sink_types: Optional[List[EventSinkType]] = None,
    logger_name: Optional[str] = None,
) -> EventEmitter:
    """Factory function to create event emitters based on configuration.

    This function creates an appropriate event emitter based on the
    requested sink types. If multiple sink types are requested, a
    CompositeEventEmitter is returned that delegates to all of them.

    Args:
        sink_types: List of event sink types to enable. If None or empty,
                    returns a LoggingEventEmitter as the default.
        logger_name: Optional logger name for the LoggingEventEmitter.

    Returns:
        An EventEmitter configured for the requested sinks.

    Example:
        >>> # Single sink
        >>> emitter = create_event_emitter([EventSinkType.LOGGING])
        >>> isinstance(emitter, LoggingEventEmitter)
        True

        >>> # Multiple sinks
        >>> emitter = create_event_emitter([
        ...     EventSinkType.LOGGING,
        ...     EventSinkType.METRICS
        ... ])
        >>> isinstance(emitter, CompositeEventEmitter)
        True

        >>> # Default (no sinks specified)
        >>> emitter = create_event_emitter()
        >>> isinstance(emitter, LoggingEventEmitter)
        True

    Note:
        The METRICS sink type requires the MetricsEventEmitter from
        metrics.py. The KUBERNETES sink type is not yet implemented.
    """
    if not sink_types:
        return LoggingEventEmitter(logger_name=logger_name)

    emitters: List[EventEmitter] = []

    for sink_type in sink_types:
        if sink_type == EventSinkType.LOGGING:
            emitters.append(LoggingEventEmitter(logger_name=logger_name))
        elif sink_type == EventSinkType.METRICS:
            # Import here to avoid circular dependency and allow
            # metrics.py to import from this module
            try:
                from src.pipeline.events.metrics import MetricsEventEmitter
                emitters.append(MetricsEventEmitter())
            except ImportError:
                logger.warning(
                    "MetricsEventEmitter not available, skipping metrics sink"
                )
        elif sink_type == EventSinkType.KUBERNETES:
            logger.warning(
                "Kubernetes event sink not yet implemented, skipping"
            )
        else:
            logger.warning(
                "Unknown event sink type: %s, skipping",
                sink_type,
            )

    if not emitters:
        return LoggingEventEmitter(logger_name=logger_name)

    if len(emitters) == 1:
        return emitters[0]

    return CompositeEventEmitter(emitters)

