"""Pipeline orchestrator connecting all stages of the agent workflow.

Receives webhook events and drives them through the full pipeline:
webhook → classifier → provisioner → kiro → PR creation.

Each stage is a separate method with error handling that transitions
to the failed state on exceptions. The orchestrator delegates all
work to injected dependencies and uses the state machine for
transitions and the event emitter for observability.

Requirements:
- All pipeline flow requirements (1-6, 7, 9)

Source:
- src/pipeline/webhook/handler.py (WebhookHandler)
- src/pipeline/state/machine.py (PipelineStateMachine)
- src/pipeline/classifier/agent.py (IssueClassifier)
- src/pipeline/classifier/clarification.py (ClarificationManager)
- src/pipeline/provisioner/workspace.py (WorkspaceProvisioner)
- src/pipeline/provisioner/context.py (generate_workspace_files)
- src/pipeline/runner/kiro.py (KiroRunner)
- src/pipeline/github/pr_creator.py (PRCreator)
- src/pipeline/events/emitter.py (EventEmitter)
- src/pipeline/knowledge/provider.py (KnowledgeProvider)
"""

import logging
from typing import Optional

from src.pipeline.classifier.agent import IssueClassifier
from src.pipeline.classifier.clarification import ClarificationManager
from src.pipeline.classifier.models import IssueClassification
from src.pipeline.events.emitter import EventEmitter
from src.pipeline.events.models import EventType, PipelineEvent
from src.pipeline.github.client import GitHubClient
from src.pipeline.github.pr_creator import PRCreator
from src.pipeline.knowledge.provider import KnowledgeProvider
from src.pipeline.provisioner.context import generate_workspace_files
from src.pipeline.provisioner.workspace import WorkspaceProvisioner
from src.pipeline.runner.kiro import KiroRunner
from src.pipeline.state.machine import PipelineStateMachine
from src.pipeline.state.models import PipelineStage
from src.pipeline.webhook.models import GitHubIssueEvent

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Orchestrates the full issue-to-PR pipeline.

    Accepts all dependencies via constructor injection and drives a
    GitHubIssueEvent through classification, optional clarification,
    workspace provisioning, Kiro CLI execution, and PR creation.

    Attributes:
        state_machine: Manages pipeline state transitions.
        classifier: LLM-based issue classifier.
        clarification_manager: Handles clarification label/comment workflow.
        provisioner: Creates workspaces with cloned packages.
        kiro_runner: Executes Kiro CLI in provisioned workspaces.
        pr_creator: Creates PRs from Kiro output.
        github_client: GitHub API client for comments and labels.
        event_emitter: Emits pipeline events for observability.
        knowledge_provider: Two-layer knowledge retrieval (optional).
    """

    def __init__(
        self,
        state_machine: PipelineStateMachine,
        classifier: IssueClassifier,
        clarification_manager: ClarificationManager,
        provisioner: WorkspaceProvisioner,
        kiro_runner: KiroRunner,
        pr_creator: PRCreator,
        github_client: GitHubClient,
        event_emitter: EventEmitter,
        knowledge_provider: Optional[KnowledgeProvider] = None,
    ):
        self.state_machine = state_machine
        self.classifier = classifier
        self.clarification_manager = clarification_manager
        self.provisioner = provisioner
        self.kiro_runner = kiro_runner
        self.pr_creator = pr_creator
        self.github_client = github_client
        self.event_emitter = event_emitter
        self.knowledge_provider = knowledge_provider

    async def process_issue(self, event: GitHubIssueEvent) -> None:
        """Drive an issue through the full pipeline.

        Creates pipeline state, then progresses through intake,
        classification, optional clarification, provisioning,
        implementation, and PR creation. Errors at any stage
        transition the pipeline to the failed state.

        Args:
            event: Parsed GitHub issue webhook event.
        """
        issue_id = event.issue_id
        repository = event.full_repository

        logger.info(
            "Starting pipeline for issue",
            extra={"issue_id": issue_id, "action": event.action.value},
        )

        state = await self._create_pipeline_state(issue_id, repository)
        if state is None:
            return

        try:
            await self._run_intake(event)
        except Exception:
            return

    async def _create_pipeline_state(
        self, issue_id: str, repository: str
    ):
        """Create initial pipeline state in PENDING stage.

        Returns the created state, or None if creation fails.
        """
        try:
            state = await self.state_machine.create(issue_id, repository)
            await self._emit_transition_event(
                issue_id, repository, "created", PipelineStage.PENDING.value
            )
            return state
        except Exception as exc:
            logger.exception(
                "Failed to create pipeline state",
                extra={"issue_id": issue_id},
            )
            await self._emit_error_event(
                issue_id, repository, "state_creation", str(exc)
            )
            return None

    async def _run_intake(self, event: GitHubIssueEvent) -> None:
        """Transition to intake, classify, then continue or clarify."""
        issue_id = event.issue_id
        repository = event.full_repository

        await self._transition(issue_id, repository, PipelineStage.INTAKE)

        classification = await self._classify_issue(event)

        await self.state_machine.set_classification(
            issue_id, classification.to_dict()
        )

        if classification.needs_clarification:
            await self._handle_clarification(event, classification)
            return

        await self._run_provisioning(event, classification)

    async def _classify_issue(
        self, event: GitHubIssueEvent
    ) -> IssueClassification:
        """Classify the issue using the LLM classifier.

        Raises on failure so the caller can transition to failed.
        """
        issue_id = event.issue_id
        repository = event.full_repository

        try:
            classification = await self.classifier.classify(
                title=event.title,
                body=event.body,
                labels=event.labels,
            )
            logger.info(
                "Issue classified",
                extra={
                    "issue_id": issue_id,
                    "issue_type": classification.issue_type.value,
                    "completeness": classification.completeness_score,
                },
            )
            return classification
        except Exception as exc:
            await self._fail(issue_id, repository, "classification", exc)
            raise

    async def _handle_clarification(
        self,
        event: GitHubIssueEvent,
        classification: IssueClassification,
    ) -> None:
        """Transition to clarification, post comment, add label."""
        issue_id = event.issue_id
        repository = event.full_repository

        try:
            await self._transition(
                issue_id, repository, PipelineStage.CLARIFICATION
            )
            await self.clarification_manager.update_clarification_state(
                owner=event.owner,
                repo=event.repository,
                issue_number=event.issue_number,
                classification=classification,
            )
            logger.info(
                "Issue sent to clarification",
                extra={"issue_id": issue_id},
            )
        except Exception as exc:
            await self._fail(issue_id, repository, "clarification", exc)

    async def _run_provisioning(
        self,
        event: GitHubIssueEvent,
        classification: IssueClassification,
    ) -> None:
        """Provision workspace, generate context files, then run Kiro."""
        issue_id = event.issue_id
        repository = event.full_repository

        try:
            await self._transition(
                issue_id, repository, PipelineStage.PROVISIONING
            )

            issue_details = {
                "repository": event.repository,
                "owner": event.owner,
                "title": event.title,
                "body": event.body,
                "labels": event.labels,
            }

            workspace = await self.provisioner.provision(
                issue_id=issue_id,
                classification=classification,
                issue_details=issue_details,
            )

            await generate_workspace_files(
                workspace_path=workspace.path,
                issue_title=event.title,
                issue_body=event.body,
                classification=classification,
                knowledge_provider=self.knowledge_provider,
            )

            await self.state_machine.set_workspace_path(
                issue_id, str(workspace.path)
            )

            logger.info(
                "Workspace provisioned",
                extra={
                    "issue_id": issue_id,
                    "workspace": str(workspace.path),
                },
            )
        except Exception as exc:
            await self._fail(issue_id, repository, "provisioning", exc)
            return

        await self._run_implementation(event, classification, workspace)

    async def _run_implementation(
        self, event, classification, workspace
    ) -> None:
        """Run Kiro CLI in the provisioned workspace."""
        issue_id = event.issue_id
        repository = event.full_repository

        try:
            await self._transition(
                issue_id, repository, PipelineStage.IMPLEMENTATION
            )

            kiro_result = await self.kiro_runner.run(
                workspace_path=workspace.path,
                task_file=workspace.task_file,
            )

            if not kiro_result.success:
                await self._fail(
                    issue_id,
                    repository,
                    "implementation",
                    RuntimeError(
                        f"kiro-cli exited with code {kiro_result.exit_code}: "
                        f"{kiro_result.stderr[:500]}"
                    ),
                )
                return

            logger.info(
                "Kiro CLI completed",
                extra={
                    "issue_id": issue_id,
                    "duration": kiro_result.duration_seconds,
                },
            )
        except Exception as exc:
            await self._fail(issue_id, repository, "implementation", exc)
            return

        await self._run_pr_creation(event, classification, kiro_result)

    async def _run_pr_creation(
        self, event, classification, kiro_result
    ) -> None:
        """Create a PR from the Kiro output and complete the pipeline."""
        issue_id = event.issue_id
        repository = event.full_repository

        try:
            await self._transition(
                issue_id, repository, PipelineStage.PR_CREATION
            )

            head_branch = f"archon/{event.owner}/{event.repository}/{event.issue_number}"

            pr_result = await self.pr_creator.create_pr_for_issue(
                owner=event.owner,
                repo=event.repository,
                issue_number=event.issue_number,
                issue_title=event.title,
                head_branch=head_branch,
                kiro_result=kiro_result,
                classification=classification,
            )

            await self.state_machine.set_pr_number(
                issue_id, pr_result.pr_number
            )

            await self._transition(
                issue_id, repository, PipelineStage.COMPLETED
            )

            await self._emit_completion_event(
                issue_id, repository, pr_result.pr_number, pr_result.pr_url
            )

            logger.info(
                "Pipeline completed",
                extra={
                    "issue_id": issue_id,
                    "pr_number": pr_result.pr_number,
                },
            )
        except Exception as exc:
            await self._fail(issue_id, repository, "pr_creation", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _transition(
        self,
        issue_id: str,
        repository: str,
        to_stage: PipelineStage,
        details: Optional[dict] = None,
    ) -> None:
        """Transition state and emit a state-transition event."""
        state = await self.state_machine.transition(
            issue_id, to_stage, details
        )
        await self._emit_transition_event(
            issue_id,
            repository,
            state.state_history[-1].from_stage.value
            if state.state_history
            else "unknown",
            to_stage.value,
        )

    async def _fail(
        self,
        issue_id: str,
        repository: str,
        stage: str,
        exc: Exception,
    ) -> None:
        """Transition to FAILED and emit an error event."""
        error_message = f"{stage}: {exc}"
        logger.exception(
            "Pipeline stage failed",
            extra={"issue_id": issue_id, "stage": stage},
        )

        try:
            await self.state_machine.transition(
                issue_id,
                PipelineStage.FAILED,
                details={"error": error_message},
            )
        except Exception:
            logger.exception(
                "Failed to transition to FAILED state",
                extra={"issue_id": issue_id},
            )

        await self._emit_error_event(issue_id, repository, stage, str(exc))

    async def _emit_transition_event(
        self,
        issue_id: str,
        repository: str,
        from_stage: str,
        to_stage: str,
    ) -> None:
        """Emit a STATE_TRANSITION event."""
        await self._safe_emit(
            PipelineEvent(
                event_type=EventType.STATE_TRANSITION,
                issue_id=issue_id,
                repository=repository,
                details={"from_stage": from_stage, "to_stage": to_stage},
            )
        )

    async def _emit_error_event(
        self,
        issue_id: str,
        repository: str,
        stage: str,
        error_message: str,
    ) -> None:
        """Emit an ERROR event."""
        await self._safe_emit(
            PipelineEvent(
                event_type=EventType.ERROR,
                issue_id=issue_id,
                repository=repository,
                details={"stage": stage, "error_message": error_message},
            )
        )

    async def _emit_completion_event(
        self,
        issue_id: str,
        repository: str,
        pr_number: int,
        pr_url: str,
    ) -> None:
        """Emit a COMPLETION event."""
        await self._safe_emit(
            PipelineEvent(
                event_type=EventType.COMPLETION,
                issue_id=issue_id,
                repository=repository,
                details={"pr_number": pr_number, "pr_url": pr_url},
            )
        )

    async def _safe_emit(self, event: PipelineEvent) -> None:
        """Emit an event, swallowing exceptions to avoid disrupting the pipeline."""
        try:
            await self.event_emitter.emit(event)
        except Exception:
            logger.exception(
                "Failed to emit pipeline event",
                extra={
                    "event_type": event.event_type.value,
                    "issue_id": event.issue_id,
                },
            )
