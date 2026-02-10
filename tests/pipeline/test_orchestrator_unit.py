"""Unit tests for the PipelineOrchestrator.

Verifies the orchestration flow by mocking all dependencies and
asserting that the correct methods are called in the correct order
for each pipeline path (happy path, clarification, and failures).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.pipeline.classifier.models import IssueClassification, IssueType
from src.pipeline.events.models import EventType
from src.pipeline.github.pr_creator import PRCreationResult
from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.provisioner.workspace import ProvisionedWorkspace
from src.pipeline.runner.kiro import KiroResult
from src.pipeline.state.models import PipelineStage, PipelineState
from src.pipeline.webhook.models import GitHubIssueEvent, IssueAction


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_event(
    issue_number: int = 42,
    title: str = "Add feature X",
    body: str = "Implement feature X for module Y",
    labels: Optional[List[str]] = None,
    owner: str = "acme",
    repo: str = "widgets",
    author: str = "dev1",
    action: IssueAction = IssueAction.OPENED,
) -> GitHubIssueEvent:
    return GitHubIssueEvent(
        action=action,
        issue_number=issue_number,
        title=title,
        body=body,
        labels=labels or ["archon-automate"],
        repository=repo,
        owner=owner,
        author=author,
    )


def _make_classification(
    completeness: int = 4,
    issue_type: IssueType = IssueType.FEATURE,
) -> IssueClassification:
    return IssueClassification(
        issue_type=issue_type,
        requirements=["Implement feature X"],
        affected_packages=["widgets"],
        completeness_score=completeness,
        clarification_questions=(
            ["What is the expected behavior?"] if completeness < 3 else []
        ),
    )


def _make_pipeline_state(
    issue_id: str = "acme/widgets#42",
    stage: PipelineStage = PipelineStage.PENDING,
    version: int = 1,
) -> PipelineState:
    return PipelineState(
        issue_id=issue_id,
        repository="acme/widgets",
        current_stage=stage,
        state_history=[],
        version=version,
    )


def _make_workspace(tmp_path: Optional[Path] = None) -> ProvisionedWorkspace:
    base = tmp_path or Path("/tmp/workspace")
    return ProvisionedWorkspace(
        path=base,
        packages=["widgets"],
        context_file=base / "context.md",
        task_file=base / "task.md",
    )


def _make_kiro_result(success: bool = True) -> KiroResult:
    return KiroResult(
        success=success,
        exit_code=0 if success else 1,
        stdout="Implementation complete" if success else "",
        stderr="" if success else "Error occurred",
        duration_seconds=10.0,
    )


def _make_pr_creation_result() -> PRCreationResult:
    return PRCreationResult(
        pr_number=99,
        pr_url="https://github.com/acme/widgets/pull/99",
        comment_posted=True,
    )


@pytest.fixture
def deps():
    """Create a dict of mocked dependencies for the orchestrator."""
    state_machine = AsyncMock()
    state_machine.create.return_value = _make_pipeline_state()
    state_machine.transition.return_value = _make_pipeline_state(
        stage=PipelineStage.INTAKE, version=2
    )
    state_machine.set_classification.return_value = _make_pipeline_state(version=3)
    state_machine.set_workspace_path.return_value = _make_pipeline_state(version=4)
    state_machine.set_pr_number.return_value = _make_pipeline_state(version=5)

    classifier = AsyncMock()
    classifier.classify.return_value = _make_classification(completeness=4)

    clarification_manager = AsyncMock()
    provisioner = AsyncMock()
    provisioner.provision.return_value = _make_workspace()

    kiro_runner = AsyncMock()
    kiro_runner.run.return_value = _make_kiro_result(success=True)

    pr_creator = AsyncMock()
    pr_creator.create_pr_for_issue.return_value = _make_pr_creation_result()

    github_client = AsyncMock()
    event_emitter = AsyncMock()
    knowledge_provider = AsyncMock()

    return {
        "state_machine": state_machine,
        "classifier": classifier,
        "clarification_manager": clarification_manager,
        "provisioner": provisioner,
        "kiro_runner": kiro_runner,
        "pr_creator": pr_creator,
        "github_client": github_client,
        "event_emitter": event_emitter,
        "knowledge_provider": knowledge_provider,
    }


@pytest.fixture
def orchestrator(deps):
    return PipelineOrchestrator(**deps)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_creates_state_and_completes(orchestrator, deps):
    """Full pipeline: pending → intake → provisioning → implementation → pr_creation → completed."""
    event = _make_event()

    with patch(
        "src.pipeline.orchestrator.generate_workspace_files",
        new_callable=AsyncMock,
    ):
        run_async(orchestrator.process_issue(event))

    deps["state_machine"].create.assert_called_once_with(
        event.issue_id, event.full_repository
    )
    deps["classifier"].classify.assert_called_once()
    deps["provisioner"].provision.assert_called_once()
    deps["kiro_runner"].run.assert_called_once()
    deps["pr_creator"].create_pr_for_issue.assert_called_once()

    transition_calls = deps["state_machine"].transition.call_args_list
    stages = [call.args[1] for call in transition_calls]
    assert PipelineStage.INTAKE in stages
    assert PipelineStage.PROVISIONING in stages
    assert PipelineStage.IMPLEMENTATION in stages
    assert PipelineStage.PR_CREATION in stages
    assert PipelineStage.COMPLETED in stages


def test_happy_path_emits_completion_event(orchestrator, deps):
    event = _make_event()

    with patch(
        "src.pipeline.orchestrator.generate_workspace_files",
        new_callable=AsyncMock,
    ):
        run_async(orchestrator.process_issue(event))

    emitted_events = deps["event_emitter"].emit.call_args_list
    event_types = [call.args[0].event_type for call in emitted_events]
    assert EventType.COMPLETION in event_types


# ---------------------------------------------------------------------------
# Clarification path
# ---------------------------------------------------------------------------


def test_clarification_path_stops_at_clarification(deps):
    """When completeness < 3, pipeline stops at clarification."""
    deps["classifier"].classify.return_value = _make_classification(completeness=2)
    orch = PipelineOrchestrator(**deps)
    event = _make_event()

    run_async(orch.process_issue(event))

    deps["clarification_manager"].update_clarification_state.assert_called_once()
    deps["provisioner"].provision.assert_not_called()
    deps["kiro_runner"].run.assert_not_called()
    deps["pr_creator"].create_pr_for_issue.assert_not_called()

    transition_calls = deps["state_machine"].transition.call_args_list
    stages = [call.args[1] for call in transition_calls]
    assert PipelineStage.CLARIFICATION in stages
    assert PipelineStage.PROVISIONING not in stages


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_classification_failure_transitions_to_failed(deps):
    """When classifier raises, pipeline transitions to FAILED."""
    deps["classifier"].classify.side_effect = RuntimeError("LLM timeout")
    orch = PipelineOrchestrator(**deps)
    event = _make_event()

    run_async(orch.process_issue(event))

    transition_calls = deps["state_machine"].transition.call_args_list
    stages = [call.args[1] for call in transition_calls]
    assert PipelineStage.FAILED in stages

    emitted = deps["event_emitter"].emit.call_args_list
    error_events = [
        c for c in emitted if c.args[0].event_type == EventType.ERROR
    ]
    assert len(error_events) >= 1


def test_provisioning_failure_transitions_to_failed(deps):
    """When provisioner raises, pipeline transitions to FAILED."""
    deps["provisioner"].provision.side_effect = OSError("Disk full")
    orch = PipelineOrchestrator(**deps)
    event = _make_event()

    run_async(orch.process_issue(event))

    transition_calls = deps["state_machine"].transition.call_args_list
    stages = [call.args[1] for call in transition_calls]
    assert PipelineStage.FAILED in stages


def test_kiro_failure_transitions_to_failed(deps):
    """When Kiro CLI returns non-zero exit, pipeline transitions to FAILED."""
    deps["kiro_runner"].run.return_value = _make_kiro_result(success=False)
    orch = PipelineOrchestrator(**deps)
    event = _make_event()

    with patch(
        "src.pipeline.orchestrator.generate_workspace_files",
        new_callable=AsyncMock,
    ):
        run_async(orch.process_issue(event))

    transition_calls = deps["state_machine"].transition.call_args_list
    stages = [call.args[1] for call in transition_calls]
    assert PipelineStage.FAILED in stages
    assert PipelineStage.COMPLETED not in stages


def test_pr_creation_failure_transitions_to_failed(deps):
    """When PR creation raises, pipeline transitions to FAILED."""
    deps["pr_creator"].create_pr_for_issue.side_effect = RuntimeError("API error")
    orch = PipelineOrchestrator(**deps)
    event = _make_event()

    with patch(
        "src.pipeline.orchestrator.generate_workspace_files",
        new_callable=AsyncMock,
    ):
        run_async(orch.process_issue(event))

    transition_calls = deps["state_machine"].transition.call_args_list
    stages = [call.args[1] for call in transition_calls]
    assert PipelineStage.FAILED in stages


def test_state_creation_failure_returns_early(deps):
    """When state creation fails, process_issue returns without crashing."""
    deps["state_machine"].create.side_effect = RuntimeError("DB down")
    orch = PipelineOrchestrator(**deps)
    event = _make_event()

    run_async(orch.process_issue(event))

    deps["classifier"].classify.assert_not_called()


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


def test_event_emitter_failure_does_not_crash_pipeline(deps):
    """Event emission failures are swallowed."""
    deps["event_emitter"].emit.side_effect = RuntimeError("Emit failed")
    orch = PipelineOrchestrator(**deps)
    event = _make_event()

    with patch(
        "src.pipeline.orchestrator.generate_workspace_files",
        new_callable=AsyncMock,
    ):
        run_async(orch.process_issue(event))

    deps["pr_creator"].create_pr_for_issue.assert_called_once()


def test_state_transition_events_emitted(orchestrator, deps):
    """State transition events are emitted for each stage change."""
    event = _make_event()

    with patch(
        "src.pipeline.orchestrator.generate_workspace_files",
        new_callable=AsyncMock,
    ):
        run_async(orchestrator.process_issue(event))

    emitted = deps["event_emitter"].emit.call_args_list
    transition_events = [
        c
        for c in emitted
        if c.args[0].event_type == EventType.STATE_TRANSITION
    ]
    # At minimum: created→pending, pending→intake, intake→provisioning,
    # provisioning→implementation, implementation→pr_creation, pr_creation→completed
    assert len(transition_events) >= 5
