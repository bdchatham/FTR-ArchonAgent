"""FastAPI application entry point for Agent Pipeline.

This module provides the main FastAPI application for the agent orchestration
pipeline. It handles GitHub webhooks, manages pipeline state, and coordinates
the autonomous development workflow.

Requirements:
- 9.6: Metrics SHALL be exposed in Prometheus format at `/metrics` endpoint
- 10.7: Log configuration values (redacting secrets) on startup
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from .classifier.agent import IssueClassifier
from .classifier.clarification import ClarificationManager
from .config import PipelineSettings, get_settings
from .events.emitter import LoggingEventEmitter
from .github.client import GitHubClient
from .github.pr_creator import PRCreator
from .orchestrator import PipelineOrchestrator
from .provisioner.workspace import WorkspaceConfig, WorkspaceProvisioner
from .runner.kiro import KiroRunner
from .state.machine import PipelineStateMachine
from .webhook.handler import WebhookHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global instances, initialized during lifespan startup
settings: PipelineSettings
orchestrator: Optional[PipelineOrchestrator] = None
webhook_handler: Optional[WebhookHandler] = None
github_client: Optional[GitHubClient] = None


def _redact_secret(value: str, visible_chars: int = 4) -> str:
    """Redact a secret value, showing only the first few characters.

    Args:
        value: The secret value to redact.
        visible_chars: Number of characters to show at the start.

    Returns:
        Redacted string with asterisks replacing hidden characters.
    """
    if len(value) <= visible_chars:
        return "*" * len(value)
    return value[:visible_chars] + "*" * (len(value) - visible_chars)


def _log_configuration(settings: PipelineSettings) -> None:
    """Log configuration values with secrets redacted.

    Requirement 10.7: Log configuration values (redacting secrets) on startup.

    Args:
        settings: The pipeline settings to log.
    """
    logger.info("Pipeline configuration:")
    logger.info(f"  GitHub Base URL: {settings.github_base_url}")
    logger.info(f"  GitHub Token: {_redact_secret(settings.github_token)}")
    logger.info(
        f"  GitHub Webhook Secret: {_redact_secret(settings.github_webhook_secret)}"
    )
    logger.info(f"  Workspace Base Path: {settings.workspace_base_path}")
    logger.info(f"  Workspace Retention Days: {settings.workspace_retention_days}")
    logger.info(f"  Kiro CLI Path: {settings.kiro_cli_path}")
    logger.info(f"  Kiro Timeout Seconds: {settings.kiro_timeout_seconds}")
    logger.info(f"  LLM URL: {settings.llm_url}")
    logger.info(f"  LLM Model: {settings.llm_model}")
    logger.info(f"  Knowledge Base Namespace: {settings.knowledge_base_namespace}")
    logger.info(f"  Knowledge Base Name: {settings.knowledge_base_name}")
    logger.info(f"  Database URL: {_redact_secret(settings.database_url)}")
    logger.info(f"  Host: {settings.host}")
    logger.info(f"  Port: {settings.port}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown.

    Handles:
    - Configuration loading and validation
    - Logging configuration (with secrets redacted)
    - Dependency wiring for the pipeline orchestrator
    - Graceful shutdown and cleanup
    """
    global settings, orchestrator, webhook_handler, github_client

    logger.info("Agent Pipeline starting up...")

    settings = get_settings()
    _log_configuration(settings)

    webhook_handler = WebhookHandler(secret=settings.github_webhook_secret)
    github_client = GitHubClient(
        token=settings.github_token,
        base_url=settings.github_base_url,
    )
    orchestrator = _build_orchestrator(settings, github_client)

    logger.info("Agent Pipeline started successfully")

    yield

    logger.info("Agent Pipeline shutting down...")

    if github_client is not None:
        await github_client.close()

    logger.info("Agent Pipeline shutdown complete")


def _build_orchestrator(
    cfg: PipelineSettings,
    gh_client: GitHubClient,
) -> PipelineOrchestrator:
    """Wire all pipeline dependencies into a PipelineOrchestrator.

    Args:
        cfg: Validated pipeline settings.
        gh_client: Authenticated GitHub API client.

    Returns:
        Fully wired PipelineOrchestrator.
    """
    from .state.machine import PipelineStateMachine

    state_machine = PipelineStateMachine(repository=_create_state_repository())

    classifier = IssueClassifier(
        llm_url=cfg.llm_url,
        model_name=cfg.llm_model,
    )

    clarification_manager = ClarificationManager(github_client=gh_client)

    workspace_config = WorkspaceConfig(
        base_path=Path(cfg.workspace_base_path),
        retention_days=cfg.workspace_retention_days,
    )
    provisioner = WorkspaceProvisioner(config=workspace_config)

    kiro_runner = KiroRunner(
        kiro_path=cfg.kiro_cli_path,
        timeout_seconds=cfg.kiro_timeout_seconds,
    )

    pr_creator = PRCreator(github_client=gh_client)
    event_emitter = LoggingEventEmitter()

    return PipelineOrchestrator(
        state_machine=state_machine,
        classifier=classifier,
        clarification_manager=clarification_manager,
        provisioner=provisioner,
        kiro_runner=kiro_runner,
        pr_creator=pr_creator,
        github_client=gh_client,
        event_emitter=event_emitter,
        knowledge_provider=None,
    )


def _create_state_repository():
    """Create a state repository instance.

    Returns an in-memory stub that satisfies the StateRepository protocol.
    The PostgreSQL implementation is wired when database persistence is
    configured (task 4.2).
    """
    from .state.models import PipelineStage, PipelineState

    class InMemoryStateRepository:
        """Minimal in-memory state repository for local development."""

        def __init__(self):
            self._states: dict[str, PipelineState] = {}

        async def save(self, state: PipelineState) -> None:
            self._states[state.issue_id] = state

        async def get(self, issue_id: str):
            return self._states.get(issue_id)

        async def list_by_stage(self, stage: PipelineStage):
            return [
                s for s in self._states.values()
                if s.current_stage == stage
            ]

        async def update_with_version(self, state: PipelineState) -> bool:
            existing = self._states.get(state.issue_id)
            if existing is None:
                return False
            if existing.version != state.version - 1:
                return False
            self._states[state.issue_id] = state
            return True

    return InMemoryStateRepository()


app = FastAPI(
    title="Archon Agent Pipeline",
    description="Autonomous development workflow orchestration for GitHub issues",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Liveness probe endpoint.

    Returns 200 OK if the application is running. This endpoint is used
    by Kubernetes liveness probes to determine if the container should
    be restarted.

    Returns:
        dict: Status indicating the application is healthy.
    """
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    """Readiness probe endpoint.

    Checks if the application is ready to receive traffic by verifying
    connectivity to required dependencies (database, etc.).

    Returns:
        dict: Status and dependency health information.

    Raises:
        HTTPException: 503 if critical dependencies are unavailable.
    """
    # TODO: Implement actual database connectivity check (task 4.2)
    # For now, return ready status as placeholder
    database_status = "healthy"

    status = "ready" if database_status == "healthy" else "not_ready"

    return {
        "status": status,
        "dependencies": {
            "database": database_status,
        },
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint.

    Requirement 9.6: Metrics SHALL be exposed in Prometheus format at `/metrics`.

    Returns:
        str: Prometheus-formatted metrics text.
    """
    # TODO: Implement actual Prometheus metrics (task 5.3)
    # Placeholder returns empty metrics for now
    return "# Prometheus metrics placeholder\n"


@app.post("/webhooks/github")
async def github_webhook(request: Request):
    """GitHub webhook receiver endpoint.

    Receives GitHub webhook events forwarded from the Tekton EventListener.
    The EventListener handles signature validation, so this endpoint trusts
    that incoming requests are authentic.

    Requirement 1.1: Expose HTTP POST endpoint at `/webhooks/github`
    Requirement 1.2: Trust signature validation performed by EventListener
    Requirement 1.6: Acknowledge within 10 seconds

    Returns:
        dict: Acknowledgment of webhook receipt.
    """
    payload = await request.json()

    if webhook_handler is None or orchestrator is None:
        logger.error("Pipeline not initialized")
        return {"status": "error", "message": "Pipeline not initialized"}

    event = webhook_handler.parse_issue_event(payload)
    if event is None:
        return {"status": "ignored", "message": "Unsupported or invalid event"}

    import asyncio
    asyncio.create_task(orchestrator.process_issue(event))

    return {"status": "accepted", "issue_id": event.issue_id}


if __name__ == "__main__":
    import uvicorn

    # For local development, load settings to get host/port
    dev_settings = get_settings()
    uvicorn.run(
        "src.pipeline.main:app",
        host=dev_settings.host,
        port=dev_settings.port,
        reload=True,
    )
