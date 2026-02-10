"""Property-based tests for workspace context file generation.

Verifies that context.md and task.md are correctly generated across
all valid combinations of issue details, classifications, and knowledge
provider availability.

**Validates: Requirements 4.3, 4.4, 4.5, 4.6**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>
"""

import asyncio
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

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


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def _printable_text(min_size=0, max_size=200):
    """Text strategy that avoids bare \\r which file I/O normalises."""
    alphabet = st.characters(blacklist_categories=("Cs",), blacklist_characters="\r")
    return st.text(alphabet=alphabet, min_size=min_size, max_size=max_size)


@st.composite
def valid_issue_title(draw):
    return draw(_printable_text(min_size=1, max_size=200).filter(lambda t: t.strip()))


@st.composite
def valid_issue_body(draw):
    return draw(_printable_text(min_size=0, max_size=1000))


@st.composite
def valid_issue_type(draw):
    return draw(st.sampled_from(list(IssueType)))


@st.composite
def valid_requirements(draw):
    return draw(st.lists(
        _printable_text(min_size=1, max_size=100).filter(lambda t: t.strip()),
        min_size=0, max_size=5,
    ))


@st.composite
def valid_packages(draw):
    return draw(st.lists(
        st.text(
            alphabet=st.sampled_from(
                "abcdefghijklmnopqrstuvwxyz0123456789-"
            ),
            min_size=1, max_size=30,
        ).filter(lambda x: x.strip() and not x.startswith("-")),
        min_size=0, max_size=5,
        unique=True,
    ))


@st.composite
def valid_classification(draw):
    return IssueClassification(
        issue_type=draw(valid_issue_type()),
        requirements=draw(valid_requirements()),
        affected_packages=draw(valid_packages()),
        completeness_score=draw(st.integers(min_value=1, max_value=5)),
        clarification_questions=[],
    )


# ---------------------------------------------------------------------------
# Property tests for context.md generation (Requirement 4.3, 4.4)
# ---------------------------------------------------------------------------


class TestContextFileProperties:
    """Property tests for context.md generation.

    Feature: agent-orchestration

    *For any* valid issue details and classification, generate_context_file
    SHALL produce a context.md containing the issue title, body, and
    classification results.

    **Validates: Requirements 4.3, 4.4**
    """

    @given(
        title=valid_issue_title(),
        body=valid_issue_body(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_context_file_always_contains_issue_title(
        self, title, body, classification
    ):
        """Property: context.md always contains the issue title.

        **Validates: Requirements 4.3**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_context_file(ws, title, body, classification))
            content = (ws / "context.md").read_text()
            assert title in content

    @given(
        title=valid_issue_title(),
        body=_printable_text(min_size=1, max_size=500).filter(lambda t: t.strip()),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_context_file_contains_nonempty_body(
        self, title, body, classification
    ):
        """Property: context.md contains the issue body when non-empty.

        **Validates: Requirements 4.3**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_context_file(ws, title, body, classification))
            content = (ws / "context.md").read_text()
            assert body in content

    @given(
        title=valid_issue_title(),
        body=valid_issue_body(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_context_file_contains_classification_type(
        self, title, body, classification
    ):
        """Property: context.md always contains the classification type.

        **Validates: Requirements 4.3**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_context_file(ws, title, body, classification))
            content = (ws / "context.md").read_text()
            assert classification.issue_type.value in content

    @given(
        title=valid_issue_title(),
        body=valid_issue_body(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_context_file_contains_all_affected_packages(
        self, title, body, classification
    ):
        """Property: context.md lists every affected package.

        **Validates: Requirements 4.3**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_context_file(ws, title, body, classification))
            content = (ws / "context.md").read_text()
            for pkg in classification.affected_packages:
                assert pkg in content

    @given(
        title=valid_issue_title(),
        body=valid_issue_body(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_context_file_contains_all_requirements(
        self, title, body, classification
    ):
        """Property: context.md lists every extracted requirement.

        **Validates: Requirements 4.3**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_context_file(ws, title, body, classification))
            content = (ws / "context.md").read_text()
            for req in classification.requirements:
                assert req in content

    @given(
        title=valid_issue_title(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_context_file_includes_knowledge_when_provider_available(
        self, title, classification
    ):
        """Property: context.md includes knowledge section when provider returns content.

        **Validates: Requirements 4.4**
        """
        provider = AsyncMock(spec=KnowledgeProvider)
        provider.combined_context = AsyncMock(return_value="knowledge payload")

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_context_file(
                ws, title, "body", classification,
                knowledge_provider=provider,
            ))
            content = (ws / "context.md").read_text()
            assert "Knowledge Context" in content
            assert "knowledge payload" in content

    @given(
        title=valid_issue_title(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_context_file_omits_knowledge_when_no_provider(
        self, title, classification
    ):
        """Property: context.md omits knowledge section when no provider.

        **Validates: Requirements 4.4**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_context_file(
                ws, title, "body", classification,
                knowledge_provider=None,
            ))
            content = (ws / "context.md").read_text()
            assert "Knowledge Context" not in content


# ---------------------------------------------------------------------------
# Property tests for task.md generation (Requirement 4.6)
# ---------------------------------------------------------------------------


class TestTaskFileProperties:
    """Property tests for task.md generation.

    Feature: agent-orchestration

    *For any* valid issue details and classification, generate_task_file
    SHALL produce a task.md containing the issue title, type, and
    implementation summary.

    **Validates: Requirements 4.6**
    """

    @given(
        title=valid_issue_title(),
        body=valid_issue_body(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_task_file_always_contains_title(
        self, title, body, classification
    ):
        """Property: task.md always contains the issue title.

        **Validates: Requirements 4.6**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_task_file(ws, title, body, classification))
            content = (ws / "task.md").read_text()
            assert title in content

    @given(
        title=valid_issue_title(),
        body=valid_issue_body(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_task_file_always_contains_issue_type(
        self, title, body, classification
    ):
        """Property: task.md always contains the classification type.

        **Validates: Requirements 4.6**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_task_file(ws, title, body, classification))
            content = (ws / "task.md").read_text()
            assert classification.issue_type.value in content

    @given(
        title=valid_issue_title(),
        body=valid_issue_body(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_task_file_contains_all_requirements(
        self, title, body, classification
    ):
        """Property: task.md lists every extracted requirement.

        **Validates: Requirements 4.6**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_task_file(ws, title, body, classification))
            content = (ws / "task.md").read_text()
            for req in classification.requirements:
                assert req in content

    @given(
        title=valid_issue_title(),
        body=valid_issue_body(),
        classification=valid_classification(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_task_file_contains_all_affected_packages(
        self, title, body, classification
    ):
        """Property: task.md lists every affected package.

        **Validates: Requirements 4.6**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            run_async(generate_task_file(ws, title, body, classification))
            content = (ws / "task.md").read_text()
            for pkg in classification.affected_packages:
                assert pkg in content


# ---------------------------------------------------------------------------
# Property tests for search query construction (Requirement 4.4)
# ---------------------------------------------------------------------------


class TestSearchQueryProperties:
    """Property tests for search query construction.

    Feature: agent-orchestration

    *For any* valid issue title and classification, the search query
    SHALL include the title and all requirements.

    **Validates: Requirements 4.4**
    """

    @given(
        title=valid_issue_title(),
        classification=valid_classification(),
    )
    @settings(max_examples=100)
    def test_search_query_contains_title(self, title, classification):
        """Property: Search query always contains the issue title.

        **Validates: Requirements 4.4**
        """
        query = _build_search_query(title, classification)
        assert title in query

    @given(
        title=valid_issue_title(),
        classification=valid_classification(),
    )
    @settings(max_examples=100)
    def test_search_query_contains_all_requirements(self, title, classification):
        """Property: Search query contains every requirement.

        **Validates: Requirements 4.4**
        """
        query = _build_search_query(title, classification)
        for req in classification.requirements:
            assert req in query
