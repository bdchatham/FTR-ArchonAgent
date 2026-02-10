"""Property-based tests for the PipelineOrchestrator.

Verifies that state transition sequences produced by the orchestrator
are always valid according to the VALID_TRANSITIONS map, regardless
of which pipeline path is taken.

**Validates: Requirements 7.1, 7.2 (all pipeline flow requirements)**
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings as hyp_settings, strategies as st

from src.pipeline.classifier.models import IssueClassification, IssueType
from src.pipeline.github.pr_creator import PRCreationResult
from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.provisioner.workspace import ProvisionedWorkspace
from src.pipeline.runner.kiro import KiroResult
from src.pipeline.state.machine import PipelineStateMachine
from src.pipeline.state.models import (
    VALID_TRANSITIONS,
    PipelineStage,
    PipelineState,
)
from src.pipeline.webhook.models import GitHubIssueEvent, IssueAction


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

issue_actions = st.sampled_from(list(IssueAction))
issue_types = st.sampled_from(list(IssueType))
completeness_scores = st.integers(min_value=1, max_value=5)

safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=80,
).filter(lambda s: s.strip())

label_lists = st.lists(safe_text, min_size=0, max_size=5)


@st.composite
def github_issue_events(draw):
    return GitHubIssueEvent(
        action=draw(issue_actions),
        issue_number=draw(st.integers(min_value=1, max_value=99999)),
        title=draw(safe_text),
        body=draw(st.text(min_size=0, max_size=200)),
        labels=draw(label_lists),
        repository=draw(safe_text),
        owner=draw(safe_text),
        author=draw(safe_text),
    )


@st.composite
def issue_classifications(draw):
    score = draw(completeness_scores)
    questions = (
        draw(st.lists(safe_text, min_size=1, max_size=3))
        if score < 3
        else []
    )
    return IssueClassification(
        issue_type=draw(issue_types),
        requirements=draw(st.lists(safe_text, min_size=0, max_size=3)),
        affected_packages=draw(st.lists(safe_text, min_size=0, max_size=3)),
        completeness_score=score,
        clarification_questions=questions,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TransitionRecorder:
    """In-memory state repository that records all transitions."""

    def __init__(self):
        self._states = {}
        self.recorded_transitions: List[tuple] = []

    async def save(self, state: PipelineState) -> None:
        self._states[state.issue_id] = state

    async def get(self, issue_id: str):
        return self._states.get(issue_id)

    async def list_by_stage(self, stage: PipelineStage):
        return [
            s for s in self._states.values() if s.current_stage == stage
        ]

    async def update_with_version(self, state: PipelineState) -> bool:
        existing = self._states.get(state.issue_id)
        if existing is None:
            return False
        if existing.version != state.version - 1:
            return False
        if state.state_history:
            last = state.state_history[-1]
            self.recorded_transitions.append(
                (last.from_stage, last.to_stage)
            )
        self._states[state.issue_id] = state
        return True


def _build_orchestrator(
    recorder: TransitionRecorder,
    classification: IssueClassification,
    kiro_success: bool = True,
) -> PipelineOrchestrator:
    """Build an orchestrator with a real state machine and mocked externals."""
    state_machine = PipelineStateMachine(repository=recorder)

    classifier = AsyncMock()
    classifier.classify.return_value = classification

    clarification_manager = AsyncMock()

    provisioner = AsyncMock()
    workspace = ProvisionedWorkspace(
        path=Path("/tmp/ws"),
        packages=["pkg"],
        context_file=Path("/tmp/ws/context.md"),
        task_file=Path("/tmp/ws/task.md"),
    )
    provisioner.provision.return_value = workspace

    kiro_runner = AsyncMock()
    kiro_runner.run.return_value = KiroResult(
        success=kiro_success,
        exit_code=0 if kiro_success else 1,
        stdout="done" if kiro_success else "",
        stderr="" if kiro_success else "fail",
        duration_seconds=5.0,
    )

    pr_creator = AsyncMock()
    pr_creator.create_pr_for_issue.return_value = PRCreationResult(
        pr_number=1,
        pr_url="https://github.com/o/r/pull/1",
        comment_posted=True,
    )

    github_client = AsyncMock()
    event_emitter = AsyncMock()

    return PipelineOrchestrator(
        state_machine=state_machine,
        classifier=classifier,
        clarification_manager=clarification_manager,
        provisioner=provisioner,
        kiro_runner=kiro_runner,
        pr_creator=pr_creator,
        github_client=github_client,
        event_emitter=event_emitter,
    )


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@hyp_settings(max_examples=100, deadline=5000)
@given(event=github_issue_events(), classification=issue_classifications())
def test_all_transitions_are_valid(
    event: GitHubIssueEvent,
    classification: IssueClassification,
):
    """Property: Every state transition recorded by the orchestrator is
    present in the VALID_TRANSITIONS map.

    **Validates: Requirements 7.1, 7.2**
    """
    recorder = TransitionRecorder()
    orch = _build_orchestrator(recorder, classification, kiro_success=True)

    with patch(
        "src.pipeline.orchestrator.generate_workspace_files",
        new_callable=AsyncMock,
    ):
        run_async(orch.process_issue(event))

    for from_stage, to_stage in recorder.recorded_transitions:
        valid_targets = VALID_TRANSITIONS.get(from_stage, [])
        assert to_stage in valid_targets, (
            f"Invalid transition {from_stage.value} → {to_stage.value}"
        )


@hyp_settings(max_examples=100, deadline=5000)
@given(event=github_issue_events(), classification=issue_classifications())
def test_pipeline_ends_in_terminal_or_clarification(
    event: GitHubIssueEvent,
    classification: IssueClassification,
):
    """Property: After process_issue returns, the pipeline is in a terminal
    state (COMPLETED, FAILED) or CLARIFICATION (waiting for user).

    **Validates: Requirements 7.1, 7.2**
    """
    recorder = TransitionRecorder()
    orch = _build_orchestrator(recorder, classification, kiro_success=True)

    with patch(
        "src.pipeline.orchestrator.generate_workspace_files",
        new_callable=AsyncMock,
    ):
        run_async(orch.process_issue(event))

    state = run_async(recorder.get(event.issue_id))
    assert state is not None
    assert state.current_stage in {
        PipelineStage.COMPLETED,
        PipelineStage.FAILED,
        PipelineStage.CLARIFICATION,
    }


@hyp_settings(max_examples=100, deadline=5000)
@given(event=github_issue_events())
def test_kiro_failure_always_leads_to_failed_state(
    event: GitHubIssueEvent,
):
    """Property: When Kiro CLI fails, the pipeline always ends in FAILED.

    **Validates: Requirements 5.6, 7.4**
    """
    classification = IssueClassification(
        issue_type=IssueType.FEATURE,
        requirements=["req"],
        affected_packages=[],
        completeness_score=4,
        clarification_questions=[],
    )
    recorder = TransitionRecorder()
    orch = _build_orchestrator(recorder, classification, kiro_success=False)

    with patch(
        "src.pipeline.orchestrator.generate_workspace_files",
        new_callable=AsyncMock,
    ):
        run_async(orch.process_issue(event))

    state = run_async(recorder.get(event.issue_id))
    assert state is not None
    assert state.current_stage == PipelineStage.FAILED


@hyp_settings(max_examples=100, deadline=5000)
@given(event=github_issue_events())
def test_clarification_triggered_when_completeness_below_three(
    event: GitHubIssueEvent,
):
    """Property: When completeness < 3, pipeline enters CLARIFICATION
    and does NOT proceed to PROVISIONING.

    **Validates: Requirements 2.5, 3.4**
    """
    classification = IssueClassification(
        issue_type=IssueType.FEATURE,
        requirements=[],
        affected_packages=[],
        completeness_score=2,
        clarification_questions=["What is the expected behavior?"],
    )
    recorder = TransitionRecorder()
    orch = _build_orchestrator(recorder, classification, kiro_success=True)

    run_async(orch.process_issue(event))

    state = run_async(recorder.get(event.issue_id))
    assert state is not None
    assert state.current_stage == PipelineStage.CLARIFICATION

    visited_stages = {to for _, to in recorder.recorded_transitions}
    assert PipelineStage.PROVISIONING not in visited_stages
