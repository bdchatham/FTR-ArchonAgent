"""Unit tests for PR creation logic.

Tests PR title/body building, label mapping, approach summary extraction,
and the PRCreator orchestration class.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7**
"""

import asyncio
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.pipeline.classifier.models import IssueClassification, IssueType
from src.pipeline.github.models import PRCreateRequest, PRCreateResult
from src.pipeline.github.pr_creator import (
    PRCreationResult,
    PRCreator,
    build_issue_comment,
    build_labels,
    build_pr_body,
    build_pr_title,
    extract_approach_summary,
    map_issue_type_to_label,
)
from src.pipeline.runner.kiro import KiroResult


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_classification(
    issue_type: IssueType = IssueType.BUG,
    completeness: int = 4,
    packages: Optional[List[str]] = None,
) -> IssueClassification:
    return IssueClassification(
        issue_type=issue_type,
        requirements=["Fix the login flow"],
        affected_packages=packages or ["ArchonAgent"],
        completeness_score=completeness,
        clarification_questions=[],
    )


def _make_kiro_result(
    stdout: str = "Implemented OAuth2 support",
    stderr: str = "",
    success: bool = True,
) -> KiroResult:
    return KiroResult(
        success=success,
        exit_code=0 if success else 1,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=42.0,
    )


class TestMapIssueTypeToLabel:
    """Validates Requirement 6.5: labels based on classification."""

    def test_feature_maps_to_enhancement(self):
        assert map_issue_type_to_label(IssueType.FEATURE) == "enhancement"

    def test_bug_maps_to_bug(self):
        assert map_issue_type_to_label(IssueType.BUG) == "bug"

    def test_documentation_maps_to_documentation(self):
        assert map_issue_type_to_label(IssueType.DOCUMENTATION) == "documentation"

    def test_infrastructure_maps_to_infrastructure(self):
        assert map_issue_type_to_label(IssueType.INFRASTRUCTURE) == "infrastructure"

    def test_unknown_maps_to_none(self):
        assert map_issue_type_to_label(IssueType.UNKNOWN) is None


class TestBuildPRTitle:
    """Validates Requirement 6.2: PR title with issue number and summary."""

    def test_title_includes_issue_number(self):
        title = build_pr_title(42, "Add OAuth2 support")
        assert "#42" in title

    def test_title_includes_summary(self):
        title = build_pr_title(1, "Fix login bug")
        assert "Fix login bug" in title

    def test_title_format(self):
        title = build_pr_title(99, "Update docs")
        assert title == "Fix #99: Update docs"


class TestBuildPRBody:
    """Validates Requirements 6.3, 6.4: PR body with summary, files, issue link."""

    def test_body_contains_closes_keyword(self):
        classification = _make_classification()
        body = build_pr_body(42, "summary", classification, [])
        assert "Closes #42" in body

    def test_body_contains_approach_summary(self):
        classification = _make_classification()
        body = build_pr_body(1, "Refactored auth module", classification, [])
        assert "Refactored auth module" in body

    def test_body_contains_files_changed(self):
        classification = _make_classification()
        body = build_pr_body(
            1, "summary", classification, ["src/auth.py", "tests/test_auth.py"]
        )
        assert "`src/auth.py`" in body
        assert "`tests/test_auth.py`" in body

    def test_body_contains_classification_type(self):
        classification = _make_classification(issue_type=IssueType.FEATURE)
        body = build_pr_body(1, "summary", classification, [])
        assert "feature" in body

    def test_body_contains_affected_packages(self):
        classification = _make_classification(packages=["ArchonAgent", "AphexCLI"])
        body = build_pr_body(1, "summary", classification, [])
        assert "ArchonAgent" in body
        assert "AphexCLI" in body

    def test_body_omits_files_section_when_empty(self):
        classification = _make_classification()
        body = build_pr_body(1, "summary", classification, [])
        assert "## Files Changed" not in body


class TestBuildIssueComment:
    """Validates Requirement 6.7: comment on issue with PR link."""

    def test_comment_contains_pr_number(self):
        comment = build_issue_comment(10, "https://github.com/org/repo/pull/10")
        assert "#10" in comment

    def test_comment_contains_pr_url(self):
        url = "https://github.com/org/repo/pull/10"
        comment = build_issue_comment(10, url)
        assert url in comment

    def test_comment_mentions_automation(self):
        comment = build_issue_comment(1, "https://example.com/pull/1")
        assert "Archon" in comment


class TestBuildLabels:
    """Validates Requirement 6.5: labels based on classification."""

    def test_always_includes_archon_automated(self):
        classification = _make_classification(issue_type=IssueType.UNKNOWN)
        labels = build_labels(classification)
        assert "archon-automated" in labels

    def test_bug_adds_bug_label(self):
        classification = _make_classification(issue_type=IssueType.BUG)
        labels = build_labels(classification)
        assert "bug" in labels
        assert "archon-automated" in labels

    def test_feature_adds_enhancement_label(self):
        classification = _make_classification(issue_type=IssueType.FEATURE)
        labels = build_labels(classification)
        assert "enhancement" in labels

    def test_unknown_only_has_archon_automated(self):
        classification = _make_classification(issue_type=IssueType.UNKNOWN)
        labels = build_labels(classification)
        assert labels == ["archon-automated"]


class TestExtractApproachSummary:
    """Validates Requirement 6.3: approach summary from kiro output."""

    def test_uses_stdout_when_present(self):
        result = _make_kiro_result(stdout="Implemented feature X")
        summary = extract_approach_summary(result)
        assert summary == "Implemented feature X"

    def test_fallback_when_stdout_empty(self):
        result = _make_kiro_result(stdout="")
        summary = extract_approach_summary(result)
        assert "Archon agent pipeline" in summary

    def test_truncates_long_output(self):
        long_output = "x" * 3000
        result = _make_kiro_result(stdout=long_output)
        summary = extract_approach_summary(result)
        assert len(summary) < 3000
        assert "truncated" in summary

    def test_strips_whitespace(self):
        result = _make_kiro_result(stdout="  output  \n  ")
        summary = extract_approach_summary(result)
        assert summary == "output"


class TestPRCreator:
    """Validates Requirements 6.1, 6.6, 6.7: full PR creation workflow."""

    def _make_mock_client(self):
        client = AsyncMock()
        client.create_pr = AsyncMock(
            return_value=PRCreateResult(
                pr_number=55,
                pr_url="https://github.com/org/repo/pull/55",
            )
        )
        client.create_comment = AsyncMock(return_value={"id": 1})
        return client

    def test_creates_pr_and_comments(self):
        client = self._make_mock_client()
        creator = PRCreator(github_client=client)

        result = run_async(
            creator.create_pr_for_issue(
                owner="org",
                repo="repo",
                issue_number=42,
                issue_title="Add OAuth2",
                head_branch="archon/issue-42",
                kiro_result=_make_kiro_result(),
                classification=_make_classification(),
            )
        )

        assert result.pr_number == 55
        assert result.pr_url == "https://github.com/org/repo/pull/55"
        assert result.comment_posted is True
        client.create_pr.assert_called_once()
        client.create_comment.assert_called_once()

    def test_passes_reviewers_to_pr_request(self):
        client = self._make_mock_client()
        creator = PRCreator(github_client=client)

        run_async(
            creator.create_pr_for_issue(
                owner="org",
                repo="repo",
                issue_number=1,
                issue_title="Fix bug",
                head_branch="archon/issue-1",
                kiro_result=_make_kiro_result(),
                classification=_make_classification(),
                reviewers=["alice", "bob"],
            )
        )

        call_args = client.create_pr.call_args
        pr_request = call_args[0][2]
        assert pr_request.reviewers == ["alice", "bob"]

    def test_passes_labels_from_classification(self):
        client = self._make_mock_client()
        creator = PRCreator(github_client=client)

        run_async(
            creator.create_pr_for_issue(
                owner="org",
                repo="repo",
                issue_number=1,
                issue_title="New feature",
                head_branch="archon/issue-1",
                kiro_result=_make_kiro_result(),
                classification=_make_classification(issue_type=IssueType.FEATURE),
            )
        )

        call_args = client.create_pr.call_args
        pr_request = call_args[0][2]
        assert "archon-automated" in pr_request.labels
        assert "enhancement" in pr_request.labels

    def test_comment_failure_is_non_fatal(self):
        client = self._make_mock_client()
        client.create_comment = AsyncMock(side_effect=Exception("API error"))
        creator = PRCreator(github_client=client)

        result = run_async(
            creator.create_pr_for_issue(
                owner="org",
                repo="repo",
                issue_number=1,
                issue_title="Fix",
                head_branch="archon/issue-1",
                kiro_result=_make_kiro_result(),
                classification=_make_classification(),
            )
        )

        assert result.pr_number == 55
        assert result.comment_posted is False

    def test_uses_custom_base_branch(self):
        client = self._make_mock_client()
        creator = PRCreator(github_client=client)

        run_async(
            creator.create_pr_for_issue(
                owner="org",
                repo="repo",
                issue_number=1,
                issue_title="Fix",
                head_branch="archon/issue-1",
                kiro_result=_make_kiro_result(),
                classification=_make_classification(),
                base_branch="develop",
            )
        )

        call_args = client.create_pr.call_args
        pr_request = call_args[0][2]
        assert pr_request.base_branch == "develop"

    def test_passes_files_changed(self):
        client = self._make_mock_client()
        creator = PRCreator(github_client=client)

        run_async(
            creator.create_pr_for_issue(
                owner="org",
                repo="repo",
                issue_number=1,
                issue_title="Fix",
                head_branch="archon/issue-1",
                kiro_result=_make_kiro_result(),
                classification=_make_classification(),
                files_changed=["src/main.py", "tests/test_main.py"],
            )
        )

        call_args = client.create_pr.call_args
        pr_request = call_args[0][2]
        assert pr_request.files_changed == ["src/main.py", "tests/test_main.py"]
