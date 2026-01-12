"""Metrics collection for document monitor."""

from prometheus_client import Counter, Histogram


class MonitorMetrics:
    """Prometheus metrics for document monitor."""
    
    def __init__(self):
        self.executions_total = Counter(
            'archon_monitor_executions_total', 
            'Total monitor executions', 
            ['status']
        )
        self.duration_seconds = Histogram(
            'archon_monitor_duration_seconds', 
            'Monitor execution duration'
        )
        self.documents_processed_total = Counter(
            'archon_documents_processed_total', 
            'Documents processed'
        )
        self.documents_changed_total = Counter(
            'archon_documents_changed_total', 
            'Documents detected as changed'
        )
        self.errors_total = Counter(
            'archon_monitor_errors_total', 
            'Monitor errors', 
            ['error_type']
        )
    
    def record_execution_success(self, duration: float):
        """Record successful execution."""
        self.executions_total.labels(status="success").inc()
        self.duration_seconds.observe(duration)
    
    def record_execution_failure(self, error_type: str):
        """Record failed execution."""
        self.executions_total.labels(status="error").inc()
        self.errors_total.labels(error_type=error_type).inc()
    
    def record_documents_processed(self, count: int):
        """Record number of documents processed."""
        self.documents_processed_total.inc(count)
    
    def record_documents_changed(self, count: int):
        """Record number of documents changed."""
        self.documents_changed_total.inc(count)
