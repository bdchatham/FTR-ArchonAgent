"""Property-based tests for PR creation logic.

Verifies universal properties of PR title/body building, label mapping,
approach summary extraction, and the PRCreator orchestration across
randomized inputs.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>
"""

import asyncio
from unittest.mock import AsyncMock

from hypothesis import given, settings, strategies as st

from src.pipeline.classifier.models import IssueClassification, IssueType
from src.pipeline.github.models import PRCreateResult
from src.pipeline.github.pr_creator import (
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


issue_type_strategy = st.sampled_from(list(IssueType))

issue_number_strategy = st.integers(min_value=1, max_value=100_000)

safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00\r",
    ),
    min_size=1,
    max_size=200,
)

package_list_strategy = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=30,
    ),
    min_size=0,
    max_size=5,
)

file_path_strategy = st.lists(
    st.from_regex(r"[a-z][a-z0-9_/]*\.[a-z]{1,4}", fullmatch=True),
    min_size=0,
    max_size=10,
)

classification_strategy = st.builds(
    IssueClassification,
    issue_type=issue_type_strategy,
    requirements=st.just([]),
    affected_packages=package_list_strategy,
    completeness_score=st.integers(min_value=3, max_value=5),
    clarification_questions=st.just([]),
)

kiro_stdout_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00\r",
    ),
    min_size=0,
    max_size=500,
)


class TestPRTitleProperty:
    """Property: PR title always contains the issue number and summary text.

    Feature: agent-orchestration

    *For any* issue number and title, the built PR title SHALL contain
    the issue number prefixed with # and the original title text.

    **Validates: Requirements 6.2**
    """

    @given(
        issue_number=issue_number_strategy,
        issue_title=safe_text,
    )
    @settings(max_examples=100)
    def test_title_always_contains_issue_reference_and_summary(
        self, issue_number, issue_title
    ):
        title = build_pr_title(issue_number, issue_title)
        assert f"#{issue_number}" in title
        assert issue_title in title


class TestPRBodyProperty:
    """Property: PR body always contains issue link keyword and approach summary.

    Feature: agent-orchestration

    *For any* issue number, approach summary, classification, and file list,
    the built PR body SHALL contain the "Closes #N" keyword and the
    approach summary text.

    **Validates: Requirements 6.3, 6.4**
    """

    @given(
        issue_number=issue_number_strategy,
        approach_summary=safe_text,
        classification=classification_strategy,
        files_changed=file_path_strategy,
    )
    @settings(max_examples=100)
    def test_body_always_contains_issue_link_and_summary(
        self, issue_number, approach_summary, classification, files_changed
    ):
        body = build_pr_body(
            issue_number, approach_summary, classification, files_changed
        )
        assert f"Closes #{issue_number}" in body
        assert approach_summary in body
        assert classification.issue_type.value in body

        for file_path in files_changed:
            assert file_path in body


class TestLabelMappingProperty:
    """Property: label mapping is deterministic and known types always produce a label.

    Feature: agent-orchestration

    *For any* IssueType, the label mapping SHALL return a non-empty string
    for known types (feature, bug, documentation, infrastructure) and None
    for UNKNOWN.

    **Validates: Requirements 6.5**
    """

    @given(issue_type=issue_type_strategy)
    @settings(max_examples=100)
    def test_known_types_produce_labels_unknown_produces_none(self, issue_type):
        label = map_issue_type_to_label(issue_type)
        if issue_type == IssueType.UNKNOWN:
            assert label is None
        else:
            assert isinstance(label, str)
            assert len(label) > 0


class TestBuildLabelsProperty:
    """Property: built labels always include archon-automated marker.

    Feature: agent-orchestration

    *For any* classification, the built label list SHALL always contain
    "archon-automated" and SHALL contain a type-specific label for
    known issue types.

    **Validates: Requirements 6.5**
    """

    @given(classification=classification_strategy)
    @settings(max_examples=100)
    def test_labels_always_include_archon_automated(self, classification):
        labels = build_labels(classification)
        assert "archon-automated" in labels
        assert len(labels) >= 1

        if classification.issue_type != IssueType.UNKNOWN:
            assert len(labels) == 2
        else:
            assert len(labels) == 1


class TestApproachSummaryProperty:
    """Property: approach summary is always a non-empty string.

    Feature: agent-orchestration

    *For any* KiroResult stdout content, the extracted approach summary
    SHALL be a non-empty string and SHALL not exceed 2100 characters.

    **Validates: Requirements 6.3**
    """

    @given(stdout=kiro_stdout_strategy)
    @settings(max_examples=100)
    def test_summary_always_non_empty_and_bounded(self, stdout):
        kiro_result = KiroResult(
            success=True,
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_seconds=1.0,
        )
        summary = extract_approach_summary(kiro_result)
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert len(summary) <= 2100


class TestIssueCommentProperty:
    """Property: issue comment always contains PR number and URL.

    Feature: agent-orchestration

    *For any* PR number and URL, the built issue comment SHALL contain
    both the PR number reference and the full URL.

    **Validates: Requirements 6.7**
    """

    @given(
        pr_number=st.integers(min_value=1, max_value=100_000),
        pr_url=st.from_regex(
            r"https://github\.com/[a-z]+/[a-z]+/pull/[0-9]+", fullmatch=True
        ),
    )
    @settings(max_examples=100)
    def test_comment_always_contains_pr_reference_and_url(
        self, pr_number, pr_url
    ):
        comment = build_issue_comment(pr_number, pr_url)
        assert f"#{pr_number}" in comment
        assert pr_url in comment


class TestPRCreatorOrchestrationProperty:
    """Property: PRCreator always returns a valid PRCreationResult.

    Feature: agent-orchestration

    *For any* valid inputs, the PRCreator SHALL return a PRCreationResult
    with the PR number and URL from the GitHub client response.

    **Validates: Requirements 6.1, 6.6**
    """

    @given(
        issue_number=issue_number_strategy,
        issue_title=safe_text,
        classification=classification_strategy,
        stdout=kiro_stdout_strategy,
        pr_number=st.integers(min_value=1, max_value=100_000),
    )
    @settings(max_examples=100)
    def test_creator_returns_valid_result(
        self, issue_number, issue_title, classification, stdout, pr_number
    ):
        pr_url = f"https://github.com/org/repo/pull/{pr_number}"

        client = AsyncMock()
        client.create_pr = AsyncMock(
            return_value=PRCreateResult(pr_number=pr_number, pr_url=pr_url)
        )
        client.create_comment = AsyncMock(return_value={"id": 1})

        kiro_result = KiroResult(
            success=True,
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_seconds=1.0,
        )

        creator = PRCreator(github_client=client)
        result = run_async(
            creator.create_pr_for_issue(
                owner="org",
                repo="repo",
                issue_number=issue_number,
                issue_title=issue_title,
                head_branch="archon/branch",
                kiro_result=kiro_result,
                classification=classification,
            )
        )

        assert result.pr_number == pr_number
        assert result.pr_url == pr_url
        assert result.comment_posted is True
        client.create_pr.assert_called_once()
        client.create_comment.assert_called_once()
