"""Metrics collection for query service."""

from prometheus_client import Counter, Histogram


class QueryMetrics:
    """Prometheus metrics for query service."""
    
    def __init__(self):
        self.requests_total = Counter(
            'archon_query_requests_total', 
            'Total query requests', 
            ['status']
        )
        self.duration_seconds = Histogram(
            'archon_query_duration_seconds', 
            'Query duration'
        )
        self.vector_search_duration_seconds = Histogram(
            'archon_vector_search_duration_seconds', 
            'Vector search duration'
        )
        self.llm_generation_duration_seconds = Histogram(
            'archon_llm_generation_duration_seconds', 
            'LLM generation duration'
        )
    
    def record_request_success(self, duration: float):
        """Record successful request."""
        self.requests_total.labels(status="success").inc()
        self.duration_seconds.observe(duration)
    
    def record_request_error(self):
        """Record failed request."""
        self.requests_total.labels(status="error").inc()
    
    def record_vector_search_duration(self, duration: float):
        """Record vector search timing."""
        self.vector_search_duration_seconds.observe(duration)
    
    def record_llm_generation_duration(self, duration: float):
        """Record LLM generation timing."""
        self.llm_generation_duration_seconds.observe(duration)
