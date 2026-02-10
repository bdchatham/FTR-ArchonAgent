"""Pipeline event emission and metrics.

This module provides observability for the agent pipeline:
- Event emission for state transitions, errors, completions, timeouts
- Prometheus metrics: issues_processed, issues_failed, processing_time
- Structured events for monitoring and alerting

Event Emitters:
- EventEmitter: Abstract base class for event emission
- LoggingEventEmitter: Emits events as structured log entries
- CompositeEventEmitter: Emits to multiple sinks simultaneously
- MetricsEventEmitter: Emits events as Prometheus metrics
- NullEventEmitter: Discards events (for testing)

Metrics:
- PipelineMetrics: Container for all Prometheus metrics
- get_metrics: Get or create the metrics instance
- generate_metrics_output: Generate Prometheus format output for /metrics

Factory:
- create_event_emitter: Creates emitters based on configuration
- EventSinkType: Enum of supported event sink types
"""

from src.pipeline.events.emitter import (
    CompositeEventEmitter,
    EventEmitter,
    EventSinkType,
    LoggingEventEmitter,
    NullEventEmitter,
    create_event_emitter,
)
from src.pipeline.events.metrics import (
    MetricsEventEmitter,
    PipelineMetrics,
    generate_metrics_output,
    get_metrics,
)
from src.pipeline.events.models import EventType, PipelineEvent

__all__ = [
    # Event models
    "EventType",
    "PipelineEvent",
    # Event emitters
    "EventEmitter",
    "LoggingEventEmitter",
    "CompositeEventEmitter",
    "MetricsEventEmitter",
    "NullEventEmitter",
    # Metrics
    "PipelineMetrics",
    "get_metrics",
    "generate_metrics_output",
    # Factory and configuration
    "EventSinkType",
    "create_event_emitter",
]
