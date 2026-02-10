"""Property-based tests for clarification workflow.

This module contains property-based tests using Hypothesis to verify that
the clarification workflow correctly formats comments and manages label state.

**Validates: Requirements 3.2, 3.3, 3.4, 3.6**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>
"""

import re
from typing import List

import pytest
from hypothesis import given, settings, strategies as st, assume

from src.pipeline.classifier.models import IssueClassification, IssueType
from src.pipeline.classifier.formatting import (
    format_clarification_comment,
    _format_questions_as_checklist,
    _sanitize_question,
)
from src.pipeline.classifier.clarification import (
    ClarificationManager,
    determine_label_action,
    NEEDS_CLARIFICATION_LABEL,
)


# =============================================================================
# Hypothesis Strategies for Generating Clarification Data
# =============================================================================


@st.composite
def valid_issue_type(draw: st.DrawFn) -> str:
    """Generate a valid issue type string."""
    return draw(
        st.sampled_from(["feature", "bug", "documentation", "infrastructure", "unknown"])
    )


@st.composite
def low_completeness_score(draw: st.DrawFn) -> int:
    """Generate a low completeness score (1-2) that requires clarification."""
    return draw(st.integers(min_value=1, max_value=2))


@st.composite
def high_completeness_score(draw: st.DrawFn) -> int:
    """Generate a high completeness score (3-5) that doesn't require clarification."""
    return draw(st.integers(min_value=3, max_value=5))


@st.composite
def valid_completeness_score(draw: st.DrawFn) -> int:
    """Generate any valid completeness score (1-5)."""
    return draw(st.integers(min_value=1, max_value=5))


@st.composite
def clarification_question(draw: st.DrawFn) -> str:
    """Generate a valid clarification question.
    
    Questions should be non-empty strings that don't contain newlines
    (which would break the checklist format).
    """
    question = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S", "Zs"),
                blacklist_characters="\n\r",
            ),
            min_size=5,
            max_size=200,
        ).filter(lambda x: x.strip() and len(x.strip()) >= 3)
    )
    return question


@st.composite
def non_empty_question_list(draw: st.DrawFn) -> List[str]:
    """Generate a non-empty list of clarification questions."""
    return draw(
        st.lists(clarification_question(), min_size=1, max_size=10)
    )


@st.composite
def classification_needing_clarification(draw: st.DrawFn) -> IssueClassification:
    """Generate a classification that needs clarification (score < 3)."""
    issue_type = draw(valid_issue_type())
    score = draw(low_completeness_score())
    questions = draw(non_empty_question_list())
    
    return IssueClassification(
        issue_type=IssueType(issue_type),
        completeness_score=score,
        clarification_questions=questions,
    )


@st.composite
def classification_not_needing_clarification(draw: st.DrawFn) -> IssueClassification:
    """Generate a classification that doesn't need clarification (score >= 3)."""
    issue_type = draw(valid_issue_type())
    score = draw(high_completeness_score())
    
    return IssueClassification(
        issue_type=IssueType(issue_type),
        completeness_score=score,
        clarification_questions=[],
    )


@st.composite
def any_valid_classification(draw: st.DrawFn) -> IssueClassification:
    """Generate any valid classification with appropriate questions for score."""
    issue_type = draw(valid_issue_type())
    score = draw(valid_completeness_score())
    
    # Generate questions based on score
    if score < 3:
        questions = draw(non_empty_question_list())
    else:
        questions = draw(st.lists(clarification_question(), max_size=3))
    
    return IssueClassification(
        issue_type=IssueType(issue_type),
        completeness_score=score,
        clarification_questions=questions,
    )


# =============================================================================
# Property 5: Clarification Comment Structure
# =============================================================================


class TestClarificationCommentStructure:
    """Property tests for clarification comment structure.

    Feature: agent-orchestration, Property 5: Clarification Comment Structure

    *For any* clarification comment posted to GitHub, the comment SHALL
    contain at least one question and SHALL be formatted as a GitHub-flavored
    markdown checklist (lines starting with `- [ ]`).

    **Validates: Requirements 3.2, 3.3**
    """

    @given(classification=classification_needing_clarification())
    @settings(max_examples=100)
    def test_comment_contains_at_least_one_question(
        self, classification: IssueClassification
    ) -> None:
        """Property 5: Comment contains at least one question.

        *For any* clarification comment posted to GitHub, the comment SHALL
        contain at least one question.

        **Validates: Requirements 3.2**
        """
        comment = format_clarification_comment(classification)
        
        # Comment should not be empty when there are questions
        assert comment, "Comment should not be empty when questions exist"
        
        # Count checklist items in the comment
        checklist_pattern = r"^- \[ \] .+"
        checklist_items = re.findall(checklist_pattern, comment, re.MULTILINE)
        
        assert len(checklist_items) >= 1, (
            f"Comment should contain at least one checklist item, "
            f"found {len(checklist_items)}"
        )

    @given(classification=classification_needing_clarification())
    @settings(max_examples=100)
    def test_comment_formatted_as_markdown_checklist(
        self, classification: IssueClassification
    ) -> None:
        """Property 5: Comment is formatted as GitHub markdown checklist.

        *For any* clarification comment posted to GitHub, the comment SHALL
        be formatted as a GitHub-flavored markdown checklist (lines starting
        with `- [ ]`).

        **Validates: Requirements 3.3**
        """
        comment = format_clarification_comment(classification)
        
        # Find all lines that should be checklist items
        checklist_pattern = r"^- \[ \] .+"
        checklist_items = re.findall(checklist_pattern, comment, re.MULTILINE)
        
        # Each question should appear as a checklist item
        assert len(checklist_items) == len(classification.clarification_questions), (
            f"Expected {len(classification.clarification_questions)} checklist items, "
            f"found {len(checklist_items)}"
        )
        
        # Verify each checklist item starts with the correct prefix
        for item in checklist_items:
            assert item.startswith("- [ ] "), (
                f"Checklist item should start with '- [ ] ', got: {item[:10]}..."
            )

    @given(questions=non_empty_question_list())
    @settings(max_examples=100)
    def test_all_questions_appear_in_checklist(
        self, questions: List[str]
    ) -> None:
        """Property 5: All questions appear in the checklist.

        *For any* list of clarification questions, each question SHALL
        appear in the formatted checklist.

        **Validates: Requirements 3.2, 3.3**
        """
        classification = IssueClassification(
            issue_type=IssueType.FEATURE,
            completeness_score=2,
            clarification_questions=questions,
        )
        
        comment = format_clarification_comment(classification)
        
        # Each question should appear in the comment (after sanitization)
        for question in questions:
            sanitized = _sanitize_question(question)
            if sanitized:  # Only check non-empty sanitized questions
                assert sanitized in comment, (
                    f"Question '{sanitized[:50]}...' should appear in comment"
                )

    @given(classification=classification_needing_clarification())
    @settings(max_examples=100)
    def test_checklist_items_are_unchecked(
        self, classification: IssueClassification
    ) -> None:
        """Property 5: Checklist items are unchecked.

        *For any* clarification comment, all checklist items SHALL be
        unchecked (using `- [ ]` not `- [x]`).

        **Validates: Requirements 3.3**
        """
        comment = format_clarification_comment(classification)
        
        # Should not contain checked items
        checked_pattern = r"^- \[x\] "
        checked_items = re.findall(checked_pattern, comment, re.MULTILINE | re.IGNORECASE)
        
        assert len(checked_items) == 0, (
            f"Comment should not contain checked items, found {len(checked_items)}"
        )

    @given(questions=non_empty_question_list())
    @settings(max_examples=100)
    def test_format_questions_as_checklist_structure(
        self, questions: List[str]
    ) -> None:
        """Property 5: _format_questions_as_checklist produces valid structure.

        *For any* list of questions, the formatted checklist SHALL have
        each question on its own line with the `- [ ]` prefix.

        **Validates: Requirements 3.3**
        """
        checklist = _format_questions_as_checklist(questions)
        
        # Split into lines and verify structure
        lines = [line for line in checklist.split("\n") if line.strip()]
        
        # Each line should be a valid checklist item
        for line in lines:
            assert line.startswith("- [ ] "), (
                f"Each line should start with '- [ ] ', got: {line[:15]}..."
            )
            # The content after the prefix should not be empty
            content = line[6:]  # Remove "- [ ] " prefix
            assert content.strip(), "Checklist item content should not be empty"

    @given(classification=classification_not_needing_clarification())
    @settings(max_examples=100)
    def test_no_comment_when_no_questions(
        self, classification: IssueClassification
    ) -> None:
        """Property 5: No comment generated when no questions.

        *For any* classification without clarification questions, the
        format_clarification_comment function SHALL return an empty string.

        **Validates: Requirements 3.2**
        """
        # Ensure no questions
        classification.clarification_questions = []
        
        comment = format_clarification_comment(classification)
        
        assert comment == "", (
            "Comment should be empty when there are no clarification questions"
        )

    @given(question=clarification_question())
    @settings(max_examples=100)
    def test_sanitize_question_preserves_content(
        self, question: str
    ) -> None:
        """Property 5: Question sanitization preserves meaningful content.

        *For any* valid question, sanitization SHALL preserve the
        meaningful content while removing problematic characters.

        **Validates: Requirements 3.3**
        """
        sanitized = _sanitize_question(question)
        
        # Sanitized question should not be empty if original had content
        if question.strip():
            assert sanitized, "Sanitized question should not be empty"
            
        # Should not contain newlines
        assert "\n" not in sanitized, "Sanitized question should not contain newlines"
        assert "\r" not in sanitized, "Sanitized question should not contain carriage returns"
        
        # Should not have leading/trailing whitespace
        assert sanitized == sanitized.strip(), "Sanitized question should be trimmed"


# =============================================================================
# Property 6: Label State Consistency
# =============================================================================


class TestLabelStateConsistency:
    """Property tests for label state consistency.

    Feature: agent-orchestration, Property 6: Label State Consistency

    *For any* issue that transitions through clarification, the
    `needs-clarification` label SHALL be added when completeness is below 3
    and removed when completeness reaches 3 or above.

    **Validates: Requirements 3.4, 3.6**
    """

    @given(classification=classification_needing_clarification())
    @settings(max_examples=100)
    def test_label_added_when_completeness_below_3(
        self, classification: IssueClassification
    ) -> None:
        """Property 6: Label added when completeness below 3.

        *For any* issue with completeness score below 3, the
        `needs-clarification` label SHALL be added.

        **Validates: Requirements 3.4**
        """
        # Verify the classification needs clarification
        assert classification.completeness_score < 3
        
        # Test determine_label_action
        action = determine_label_action(classification)
        assert action == "add", (
            f"Label action should be 'add' for score {classification.completeness_score}, "
            f"got '{action}'"
        )
        
        # Test ClarificationManager.should_add_label
        manager = ClarificationManager(github_client=None)  # type: ignore
        assert manager.should_add_label(classification) is True, (
            f"should_add_label should return True for score {classification.completeness_score}"
        )
        assert manager.should_remove_label(classification) is False, (
            f"should_remove_label should return False for score {classification.completeness_score}"
        )

    @given(classification=classification_not_needing_clarification())
    @settings(max_examples=100)
    def test_label_removed_when_completeness_3_or_above(
        self, classification: IssueClassification
    ) -> None:
        """Property 6: Label removed when completeness 3 or above.

        *For any* issue with completeness score of 3 or above, the
        `needs-clarification` label SHALL be removed.

        **Validates: Requirements 3.6**
        """
        # Verify the classification doesn't need clarification
        assert classification.completeness_score >= 3
        
        # Test determine_label_action
        action = determine_label_action(classification)
        assert action == "remove", (
            f"Label action should be 'remove' for score {classification.completeness_score}, "
            f"got '{action}'"
        )
        
        # Test ClarificationManager.should_remove_label
        manager = ClarificationManager(github_client=None)  # type: ignore
        assert manager.should_remove_label(classification) is True, (
            f"should_remove_label should return True for score {classification.completeness_score}"
        )
        assert manager.should_add_label(classification) is False, (
            f"should_add_label should return False for score {classification.completeness_score}"
        )

    @given(score=low_completeness_score())
    @settings(max_examples=100)
    def test_low_scores_consistently_add_label(
        self, score: int
    ) -> None:
        """Property 6: All low scores (1-2) consistently add label.

        *For any* completeness score of 1 or 2, the label action SHALL
        always be 'add'.

        **Validates: Requirements 3.4**
        """
        classification = IssueClassification(
            issue_type=IssueType.FEATURE,
            completeness_score=score,
            clarification_questions=["What is the expected behavior?"],
        )
        
        action = determine_label_action(classification)
        assert action == "add", f"Score {score} should result in 'add' action"

    @given(score=high_completeness_score())
    @settings(max_examples=100)
    def test_high_scores_consistently_remove_label(
        self, score: int
    ) -> None:
        """Property 6: All high scores (3-5) consistently remove label.

        *For any* completeness score of 3, 4, or 5, the label action SHALL
        always be 'remove'.

        **Validates: Requirements 3.6**
        """
        classification = IssueClassification(
            issue_type=IssueType.FEATURE,
            completeness_score=score,
            clarification_questions=[],
        )
        
        action = determine_label_action(classification)
        assert action == "remove", f"Score {score} should result in 'remove' action"

    @given(classification=any_valid_classification())
    @settings(max_examples=100)
    def test_label_action_mutually_exclusive(
        self, classification: IssueClassification
    ) -> None:
        """Property 6: Label actions are mutually exclusive.

        *For any* classification, exactly one of should_add_label or
        should_remove_label SHALL return True (never both, never neither).

        **Validates: Requirements 3.4, 3.6**
        """
        manager = ClarificationManager(github_client=None)  # type: ignore
        
        should_add = manager.should_add_label(classification)
        should_remove = manager.should_remove_label(classification)
        
        # Exactly one should be True
        assert should_add != should_remove, (
            f"Exactly one of should_add_label ({should_add}) and "
            f"should_remove_label ({should_remove}) should be True for "
            f"score {classification.completeness_score}"
        )

    @given(classification=any_valid_classification())
    @settings(max_examples=100)
    def test_determine_label_action_consistent_with_manager(
        self, classification: IssueClassification
    ) -> None:
        """Property 6: determine_label_action consistent with ClarificationManager.

        *For any* classification, the determine_label_action function SHALL
        return a result consistent with ClarificationManager methods.

        **Validates: Requirements 3.4, 3.6**
        """
        manager = ClarificationManager(github_client=None)  # type: ignore
        action = determine_label_action(classification)
        
        if action == "add":
            assert manager.should_add_label(classification) is True
            assert manager.should_remove_label(classification) is False
        elif action == "remove":
            assert manager.should_remove_label(classification) is True
            assert manager.should_add_label(classification) is False
        else:
            # "none" case should not occur with valid classifications
            pytest.fail(f"Unexpected action '{action}' for valid classification")

    @given(issue_type=valid_issue_type())
    @settings(max_examples=100)
    def test_boundary_score_3_removes_label(
        self, issue_type: str
    ) -> None:
        """Property 6: Boundary score 3 removes label.

        Score 3 is the boundary between needing clarification (1-2) and
        being actionable (3-5). Score 3 SHALL result in label removal.

        **Validates: Requirements 3.6**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            completeness_score=3,
            clarification_questions=[],
        )
        
        action = determine_label_action(classification)
        assert action == "remove", "Score 3 should result in 'remove' action"
        
        manager = ClarificationManager(github_client=None)  # type: ignore
        assert manager.should_remove_label(classification) is True
        assert manager.should_add_label(classification) is False

    @given(issue_type=valid_issue_type())
    @settings(max_examples=100)
    def test_boundary_score_2_adds_label(
        self, issue_type: str
    ) -> None:
        """Property 6: Boundary score 2 adds label.

        Score 2 is below the threshold and SHALL result in label addition.

        **Validates: Requirements 3.4**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            completeness_score=2,
            clarification_questions=["What is the expected behavior?"],
        )
        
        action = determine_label_action(classification)
        assert action == "add", "Score 2 should result in 'add' action"
        
        manager = ClarificationManager(github_client=None)  # type: ignore
        assert manager.should_add_label(classification) is True
        assert manager.should_remove_label(classification) is False

    @given(classification=any_valid_classification())
    @settings(max_examples=100)
    def test_label_state_consistent_with_needs_clarification(
        self, classification: IssueClassification
    ) -> None:
        """Property 6: Label state consistent with needs_clarification property.

        *For any* classification, the label action SHALL be consistent with
        the needs_clarification property of the classification.

        **Validates: Requirements 3.4, 3.6**
        """
        manager = ClarificationManager(github_client=None)  # type: ignore
        
        if classification.needs_clarification:
            assert manager.should_add_label(classification) is True, (
                "should_add_label should be True when needs_clarification is True"
            )
        else:
            assert manager.should_remove_label(classification) is True, (
                "should_remove_label should be True when needs_clarification is False"
            )


class TestClarificationWorkflowEdgeCases:
    """Edge case tests for clarification workflow.

    These tests verify that the clarification workflow handles edge cases
    correctly, including boundary values and special inputs.

    **Validates: Requirements 3.2, 3.3, 3.4, 3.6**
    """

    @given(
        issue_type=valid_issue_type(),
        questions=non_empty_question_list(),
    )
    @settings(max_examples=100)
    def test_minimum_score_1_adds_label_and_has_comment(
        self, issue_type: str, questions: List[str]
    ) -> None:
        """Edge case: Minimum score 1 adds label and generates comment.

        **Validates: Requirements 3.2, 3.4**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            completeness_score=1,
            clarification_questions=questions,
        )
        
        # Should add label
        action = determine_label_action(classification)
        assert action == "add"
        
        # Should generate comment
        comment = format_clarification_comment(classification)
        assert comment, "Comment should be generated for score 1"
        assert "- [ ]" in comment, "Comment should contain checklist items"

    @given(issue_type=valid_issue_type())
    @settings(max_examples=100)
    def test_maximum_score_5_removes_label(
        self, issue_type: str
    ) -> None:
        """Edge case: Maximum score 5 removes label.

        **Validates: Requirements 3.6**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            completeness_score=5,
            clarification_questions=[],
        )
        
        action = determine_label_action(classification)
        assert action == "remove"

    @given(questions=st.lists(clarification_question(), min_size=1, max_size=1))
    @settings(max_examples=100)
    def test_single_question_produces_valid_checklist(
        self, questions: List[str]
    ) -> None:
        """Edge case: Single question produces valid checklist.

        **Validates: Requirements 3.2, 3.3**
        """
        classification = IssueClassification(
            issue_type=IssueType.FEATURE,
            completeness_score=2,
            clarification_questions=questions,
        )
        
        comment = format_clarification_comment(classification)
        
        # Should have exactly one checklist item
        checklist_pattern = r"^- \[ \] .+"
        checklist_items = re.findall(checklist_pattern, comment, re.MULTILINE)
        assert len(checklist_items) == 1

    @given(questions=st.lists(clarification_question(), min_size=5, max_size=10))
    @settings(max_examples=100)
    def test_many_questions_all_appear_in_checklist(
        self, questions: List[str]
    ) -> None:
        """Edge case: Many questions all appear in checklist.

        **Validates: Requirements 3.2, 3.3**
        """
        classification = IssueClassification(
            issue_type=IssueType.FEATURE,
            completeness_score=1,
            clarification_questions=questions,
        )
        
        comment = format_clarification_comment(classification)
        
        # Should have all questions as checklist items
        checklist_pattern = r"^- \[ \] .+"
        checklist_items = re.findall(checklist_pattern, comment, re.MULTILINE)
        assert len(checklist_items) == len(questions)

    @given(classification=any_valid_classification())
    @settings(max_examples=100)
    def test_custom_label_name_supported(
        self, classification: IssueClassification
    ) -> None:
        """Edge case: Custom label name is supported.

        **Validates: Requirements 3.4, 3.6**
        """
        custom_label = "custom-clarification-label"
        manager = ClarificationManager(
            github_client=None,  # type: ignore
            label_name=custom_label,
        )
        
        assert manager.label_name == custom_label
        
        # Methods should still work correctly
        if classification.completeness_score < 3:
            assert manager.should_add_label(classification) is True
        else:
            assert manager.should_remove_label(classification) is True

    @given(issue_type=valid_issue_type())
    @settings(max_examples=100)
    def test_default_label_name_is_needs_clarification(
        self, issue_type: str
    ) -> None:
        """Edge case: Default label name is 'needs-clarification'.

        **Validates: Requirements 3.4**
        """
        manager = ClarificationManager(github_client=None)  # type: ignore
        assert manager.label_name == NEEDS_CLARIFICATION_LABEL
        assert manager.label_name == "needs-clarification"
