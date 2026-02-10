"""Unit tests for workspace context file generation.

Tests context.md and task.md generation including issue details,
classification formatting, knowledge retrieval, and edge cases.

**Validates: Requirements 4.3, 4.4, 4.5, 4.6**
"""

import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from src.pipeline.classifier.models import IssueClassification, IssueType
from src.pipeline.knowledge.provider import KnowledgeProvider
from src.pipeline.provisioner.context import (
    generate_context_file,
    generate_task_file,
    generate_workspace_files,
    _build_search_query,
)


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def feature_classification():
    return IssueClassification(
        issue_type=IssueType.FEATURE,
        requirements=["Add OAuth2 support", "Support refresh tokens"],
        affected_packages=["auth-service", "api-gateway"],
        completeness_score=4,
        clarification_questions=[],
    )


@pytest.fixture
def minimal_classification():
    return IssueClassification(
        issue_type=IssueType.BUG,
        requirements=[],
        affected_packages=[],
        completeness_score=3,
        clarification_questions=[],
    )


def _make_mock_provider(context_text: str = "Mock knowledge context") -> KnowledgeProvider:
    provider = AsyncMock(spec=KnowledgeProvider)
    provider.combined_context = AsyncMock(return_value=context_text)
    return provider


class TestGenerateContextFile:

    def test_creates_context_file(self, workspace, feature_classification):
        result = run_async(generate_context_file(
            workspace, "Add auth", "Implement OAuth2",
            feature_classification,
        ))
        assert result == workspace / "context.md"
        assert result.exists()

    def test_contains_issue_title(self, workspace, feature_classification):
        run_async(generate_context_file(
            workspace, "Add auth", "Implement OAuth2",
            feature_classification,
        ))
        content = (workspace / "context.md").read_text()
        assert "Add auth" in content

    def test_contains_issue_body(self, workspace, feature_classification):
        run_async(generate_context_file(
            workspace, "Add auth", "Implement OAuth2",
            feature_classification,
        ))
        content = (workspace / "context.md").read_text()
        assert "Implement OAuth2" in content

    def test_contains_classification_type(self, workspace, feature_classification):
        run_async(generate_context_file(
            workspace, "Add auth", "body",
            feature_classification,
        ))
        content = (workspace / "context.md").read_text()
        assert "feature" in content

    def test_contains_affected_packages(self, workspace, feature_classification):
        run_async(generate_context_file(
            workspace, "Add auth", "body",
            feature_classification,
        ))
        content = (workspace / "context.md").read_text()
        assert "auth-service" in content
        assert "api-gateway" in content

    def test_contains_requirements(self, workspace, feature_classification):
        run_async(generate_context_file(
            workspace, "Add auth", "body",
            feature_classification,
        ))
        content = (workspace / "context.md").read_text()
        assert "Add OAuth2 support" in content
        assert "Support refresh tokens" in content

    def test_contains_completeness_score(self, workspace, feature_classification):
        run_async(generate_context_file(
            workspace, "title", "body",
            feature_classification,
        ))
        content = (workspace / "context.md").read_text()
        assert "4/5" in content

    def test_empty_body_shows_placeholder(self, workspace, minimal_classification):
        run_async(generate_context_file(
            workspace, "Fix bug", "",
            minimal_classification,
        ))
        content = (workspace / "context.md").read_text()
        assert "No description provided" in content

    def test_no_knowledge_provider_omits_section(self, workspace, feature_classification):
        run_async(generate_context_file(
            workspace, "title", "body",
            feature_classification, knowledge_provider=None,
        ))
        content = (workspace / "context.md").read_text()
        assert "Knowledge Context" not in content

    def test_with_knowledge_provider_includes_context(self, workspace, feature_classification):
        provider = _make_mock_provider("Relevant docs about auth flow")
        run_async(generate_context_file(
            workspace, "Add auth", "body",
            feature_classification, knowledge_provider=provider,
        ))
        content = (workspace / "context.md").read_text()
        assert "Knowledge Context" in content
        assert "Relevant docs about auth flow" in content

    def test_knowledge_provider_failure_degrades_gracefully(
        self, workspace, feature_classification
    ):
        provider = AsyncMock(spec=KnowledgeProvider)
        provider.combined_context = AsyncMock(side_effect=ConnectionError("down"))
        run_async(generate_context_file(
            workspace, "title", "body",
            feature_classification, knowledge_provider=provider,
        ))
        content = (workspace / "context.md").read_text()
        assert "Knowledge Context" not in content

    def test_no_affected_packages_omits_line(self, workspace, minimal_classification):
        run_async(generate_context_file(
            workspace, "title", "body",
            minimal_classification,
        ))
        content = (workspace / "context.md").read_text()
        assert "Affected Packages" not in content

    def test_no_requirements_omits_section(self, workspace, minimal_classification):
        run_async(generate_context_file(
            workspace, "title", "body",
            minimal_classification,
        ))
        content = (workspace / "context.md").read_text()
        assert "### Requirements" not in content


class TestGenerateTaskFile:

    def test_creates_task_file(self, workspace, feature_classification):
        result = run_async(generate_task_file(
            workspace, "Add auth", "Implement OAuth2",
            feature_classification,
        ))
        assert result == workspace / "task.md"
        assert result.exists()

    def test_contains_issue_title(self, workspace, feature_classification):
        run_async(generate_task_file(
            workspace, "Add auth", "Implement OAuth2",
            feature_classification,
        ))
        content = (workspace / "task.md").read_text()
        assert "Add auth" in content

    def test_contains_issue_type(self, workspace, feature_classification):
        run_async(generate_task_file(
            workspace, "Add auth", "body",
            feature_classification,
        ))
        content = (workspace / "task.md").read_text()
        assert "feature" in content

    def test_contains_objective_from_body(self, workspace, feature_classification):
        run_async(generate_task_file(
            workspace, "Add auth", "Implement OAuth2 flow",
            feature_classification,
        ))
        content = (workspace / "task.md").read_text()
        assert "Implement OAuth2 flow" in content

    def test_empty_body_uses_title_as_objective(self, workspace, minimal_classification):
        run_async(generate_task_file(
            workspace, "Fix the login bug", "",
            minimal_classification,
        ))
        content = (workspace / "task.md").read_text()
        assert "Fix the login bug" in content

    def test_contains_numbered_requirements(self, workspace, feature_classification):
        run_async(generate_task_file(
            workspace, "title", "body",
            feature_classification,
        ))
        content = (workspace / "task.md").read_text()
        assert "1. Add OAuth2 support" in content
        assert "2. Support refresh tokens" in content

    def test_contains_affected_packages(self, workspace, feature_classification):
        run_async(generate_task_file(
            workspace, "title", "body",
            feature_classification,
        ))
        content = (workspace / "task.md").read_text()
        assert "auth-service" in content
        assert "api-gateway" in content

    def test_no_requirements_omits_section(self, workspace, minimal_classification):
        run_async(generate_task_file(
            workspace, "title", "body",
            minimal_classification,
        ))
        content = (workspace / "task.md").read_text()
        assert "## Requirements" not in content

    def test_no_packages_omits_section(self, workspace, minimal_classification):
        run_async(generate_task_file(
            workspace, "title", "body",
            minimal_classification,
        ))
        content = (workspace / "task.md").read_text()
        assert "## Affected Packages" not in content


class TestGenerateWorkspaceFiles:

    def test_generates_both_files(self, workspace, feature_classification):
        context_file, task_file = run_async(generate_workspace_files(
            workspace, "Add auth", "body",
            feature_classification,
        ))
        assert context_file.exists()
        assert task_file.exists()

    def test_returns_correct_paths(self, workspace, feature_classification):
        context_file, task_file = run_async(generate_workspace_files(
            workspace, "title", "body",
            feature_classification,
        ))
        assert context_file == workspace / "context.md"
        assert task_file == workspace / "task.md"

    def test_with_knowledge_provider(self, workspace, feature_classification):
        provider = _make_mock_provider("knowledge text")
        context_file, task_file = run_async(generate_workspace_files(
            workspace, "title", "body",
            feature_classification, knowledge_provider=provider,
        ))
        context_content = context_file.read_text()
        assert "knowledge text" in context_content


class TestBuildSearchQuery:

    def test_includes_title(self):
        classification = IssueClassification(
            issue_type=IssueType.FEATURE, requirements=[],
            affected_packages=[], completeness_score=3,
            clarification_questions=[],
        )
        query = _build_search_query("Add auth", classification)
        assert "Add auth" in query

    def test_includes_requirements(self):
        classification = IssueClassification(
            issue_type=IssueType.FEATURE,
            requirements=["OAuth2", "refresh tokens"],
            affected_packages=[], completeness_score=4,
            clarification_questions=[],
        )
        query = _build_search_query("Add auth", classification)
        assert "OAuth2" in query
        assert "refresh tokens" in query

    def test_empty_requirements_returns_title_only(self):
        classification = IssueClassification(
            issue_type=IssueType.BUG, requirements=[],
            affected_packages=[], completeness_score=3,
            clarification_questions=[],
        )
        query = _build_search_query("Fix bug", classification)
        assert query == "Fix bug"
