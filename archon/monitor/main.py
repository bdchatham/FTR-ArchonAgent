"""Document monitor main entrypoint for CronJob execution."""

import asyncio
import time
import structlog
from prometheus_client import push_to_gateway

from archon.monitor.workflow import DocumentMonitorWorkflow
from archon.monitor.metrics import MonitorMetrics
from archon.common.config import load_config

logger = structlog.get_logger()


class DocumentMonitor:
    """Main document monitor application."""
    
    def __init__(self):
        self.metrics = MonitorMetrics()
        self.config = load_config()
        self.workflow = DocumentMonitorWorkflow(self.config)
    
    async def run(self):
        """Execute monitor workflow with metrics and error handling."""
        start_time = time.time()
        
        try:
            logger.info("Starting document monitor execution")
            
            # Execute workflow
            results = await self.workflow.execute()
            
            # Record success metrics
            execution_time = time.time() - start_time
            self.metrics.record_execution_success(execution_time)
            self.metrics.record_documents_processed(results["documents_processed"])
            self.metrics.record_documents_changed(results["documents_changed"])
            
            # Push metrics if configured
            await self._push_metrics()
            
            # Log results
            logger.info("Monitor execution completed",
                       execution_time=execution_time,
                       **results)
            
            # Exit with error if there were processing errors
            if results.get("errors", 0) > 0:
                logger.warning("Monitor completed with errors", error_count=results["errors"])
                return 1
            
            return 0
            
        except Exception as e:
            self.metrics.record_execution_failure(type(e).__name__)
            logger.error("Monitor execution failed", error=str(e), exc_info=True)
            return 1
    
    async def _push_metrics(self):
        """Push metrics to Prometheus gateway if configured."""
        gateway_url = self.config.get("prometheus_gateway_url")
        if gateway_url:
            try:
                push_to_gateway(gateway_url, job="archon-monitor", registry=None)
                logger.debug("Metrics pushed to gateway", gateway_url=gateway_url)
            except Exception as e:
                logger.warning("Failed to push metrics", error=str(e))


async def main():
    """Main entrypoint."""
    # Configure structured logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    monitor = DocumentMonitor()
    exit_code = await monitor.run()
    exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
