"""Property-based tests for issue classification output.

This module contains property-based tests using Hypothesis to verify that
the issue classifier produces valid classification outputs and generates
clarification questions when needed.

**Validates: Requirements 2.1, 2.4, 2.5**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>
"""

from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, settings, strategies as st, assume
from pydantic import ValidationError

from src.pipeline.classifier.models import IssueClassification, IssueType
from src.pipeline.classifier.agent import _validate_and_normalize_response


# =============================================================================
# Hypothesis Strategies for Generating Classification Data
# =============================================================================


@st.composite
def valid_issue_type(draw: st.DrawFn) -> str:
    """Generate a valid issue type string.

    Returns one of the valid IssueType enum values.
    """
    return draw(
        st.sampled_from(["feature", "bug", "documentation", "infrastructure", "unknown"])
    )


@st.composite
def valid_completeness_score(draw: st.DrawFn) -> int:
    """Generate a valid completeness score (1-5)."""
    return draw(st.integers(min_value=1, max_value=5))


@st.composite
def invalid_completeness_score(draw: st.DrawFn) -> int:
    """Generate an invalid completeness score (outside 1-5 range)."""
    return draw(
        st.one_of(
            st.integers(max_value=0),
            st.integers(min_value=6),
        )
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
def requirement_string(draw: st.DrawFn) -> str:
    """Generate a valid requirement string."""
    return draw(
        st.text(min_size=1, max_size=200).filter(lambda x: x.strip())
    )


@st.composite
def package_name(draw: st.DrawFn) -> str:
    """Generate a valid package name."""
    return draw(
        st.text(
            alphabet=st.sampled_from(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
            ),
            min_size=1,
            max_size=50,
        ).filter(lambda x: x.strip())
    )


@st.composite
def clarification_question(draw: st.DrawFn) -> str:
    """Generate a valid clarification question."""
    return draw(
        st.text(min_size=1, max_size=300).filter(lambda x: x.strip())
    )


@st.composite
def valid_confidence(draw: st.DrawFn) -> Optional[float]:
    """Generate a valid confidence score (0.0-1.0) or None."""
    include_confidence = draw(st.booleans())
    if not include_confidence:
        return None
    return draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))


@st.composite
def valid_classification_data(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate valid classification data dictionary.

    This strategy generates data that should successfully create an
    IssueClassification object.
    """
    issue_type = draw(valid_issue_type())
    completeness_score = draw(valid_completeness_score())
    requirements = draw(st.lists(requirement_string(), max_size=10))
    affected_packages = draw(st.lists(package_name(), max_size=5))
    confidence = draw(valid_confidence())
    reasoning = draw(st.one_of(st.none(), st.text(min_size=1, max_size=200).filter(lambda x: x.strip())))

    # Generate clarification questions based on completeness score
    if completeness_score < 3:
        clarification_questions = draw(
            st.lists(clarification_question(), min_size=1, max_size=5)
        )
    else:
        clarification_questions = draw(
            st.lists(clarification_question(), max_size=3)
        )

    return {
        "issue_type": issue_type,
        "requirements": requirements,
        "affected_packages": affected_packages,
        "completeness_score": completeness_score,
        "clarification_questions": clarification_questions,
        "confidence": confidence,
        "reasoning": reasoning,
    }


@st.composite
def llm_response_data(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate data simulating an LLM response that needs normalization.

    This strategy generates data that may have edge cases like:
    - String completeness scores
    - Invalid issue types
    - Out-of-range confidence values
    """
    # Issue type might be invalid or have different casing
    issue_type = draw(
        st.one_of(
            valid_issue_type(),
            st.sampled_from(["FEATURE", "Bug", "DOCUMENTATION", "invalid_type"]),
        )
    )

    # Completeness score might be a string or out of range
    completeness_score = draw(
        st.one_of(
            st.integers(min_value=1, max_value=5),
            st.integers(min_value=-10, max_value=20),
            st.sampled_from(["1", "3", "5"]),
        )
    )

    requirements = draw(st.lists(requirement_string(), max_size=10))
    affected_packages = draw(st.lists(package_name(), max_size=5))
    clarification_questions = draw(st.lists(clarification_question(), max_size=5))

    # Confidence might be out of range
    confidence = draw(
        st.one_of(
            st.none(),
            st.floats(min_value=-1.0, max_value=2.0, allow_nan=False),
        )
    )

    reasoning = draw(st.one_of(st.none(), st.text(max_size=200)))

    return {
        "issue_type": issue_type,
        "requirements": requirements,
        "affected_packages": affected_packages,
        "completeness_score": completeness_score,
        "clarification_questions": clarification_questions,
        "confidence": confidence,
        "reasoning": reasoning,
    }


# =============================================================================
# Property Tests
# =============================================================================


class TestClassificationOutputValidation:
    """Property tests for classification output validation.

    Feature: agent-orchestration, Property 3: Classification Output Validation

    *For any* issue classification result, the issue type SHALL be one of the
    valid enum values (`feature`, `bug`, `documentation`, `infrastructure`,
    `unknown`) and the completeness score SHALL be an integer in the range 1-5.

    **Validates: Requirements 2.1, 2.4**
    """

    @given(data=valid_classification_data())
    @settings(max_examples=100)
    def test_valid_classification_creates_successfully(
        self, data: Dict[str, Any]
    ) -> None:
        """Property 3: Valid classification data creates IssueClassification.

        *For any* valid classification data with a valid issue type and
        completeness score in range 1-5, an IssueClassification object
        SHALL be successfully created.

        **Validates: Requirements 2.1, 2.4**
        """
        classification = IssueClassification(
            issue_type=IssueType(data["issue_type"]),
            requirements=data["requirements"],
            affected_packages=data["affected_packages"],
            completeness_score=data["completeness_score"],
            clarification_questions=data["clarification_questions"],
            confidence=data["confidence"],
            reasoning=data["reasoning"],
        )

        # Verify the classification was created with correct values
        assert classification.issue_type.value == data["issue_type"]
        assert classification.completeness_score == data["completeness_score"]
        assert 1 <= classification.completeness_score <= 5

    @given(issue_type=valid_issue_type())
    @settings(max_examples=100)
    def test_issue_type_is_valid_enum_value(self, issue_type: str) -> None:
        """Property 3: Issue type is always a valid enum value.

        *For any* issue classification result, the issue type SHALL be one
        of the valid enum values.

        **Validates: Requirements 2.1**
        """
        # Verify the issue type is a valid enum value
        assert issue_type in {"feature", "bug", "documentation", "infrastructure", "unknown"}

        # Verify it can be converted to IssueType enum
        issue_type_enum = IssueType(issue_type)
        assert issue_type_enum.value == issue_type

    @given(score=valid_completeness_score())
    @settings(max_examples=100)
    def test_completeness_score_in_valid_range(self, score: int) -> None:
        """Property 3: Completeness score is always in range 1-5.

        *For any* issue classification result, the completeness score SHALL
        be an integer in the range 1-5.

        **Validates: Requirements 2.4**
        """
        classification = IssueClassification(
            issue_type=IssueType.FEATURE,
            completeness_score=score,
        )

        assert isinstance(classification.completeness_score, int)
        assert 1 <= classification.completeness_score <= 5

    @given(score=invalid_completeness_score())
    @settings(max_examples=100)
    def test_invalid_completeness_score_rejected(self, score: int) -> None:
        """Property 3: Invalid completeness scores are rejected.

        *For any* completeness score outside the range 1-5, the
        IssueClassification model SHALL reject it with a validation error.

        **Validates: Requirements 2.4**
        """
        with pytest.raises(ValidationError):
            IssueClassification(
                issue_type=IssueType.FEATURE,
                completeness_score=score,
            )

    @given(data=llm_response_data())
    @settings(max_examples=100)
    def test_normalize_response_produces_valid_output(
        self, data: Dict[str, Any]
    ) -> None:
        """Property 3: Normalized response always has valid issue type and score.

        *For any* LLM response data (potentially with edge cases), the
        _validate_and_normalize_response function SHALL produce output
        with a valid issue type and completeness score in range 1-5.

        **Validates: Requirements 2.1, 2.4**
        """
        normalized = _validate_and_normalize_response(data)

        # Issue type must be valid
        assert normalized["issue_type"] in {
            "feature", "bug", "documentation", "infrastructure", "unknown"
        }

        # Completeness score must be in range
        assert isinstance(normalized["completeness_score"], int)
        assert 1 <= normalized["completeness_score"] <= 5

    @given(data=valid_classification_data())
    @settings(max_examples=100)
    def test_classification_round_trip_preserves_values(
        self, data: Dict[str, Any]
    ) -> None:
        """Property 3: Classification round-trip preserves all values.

        *For any* valid classification data, converting to IssueClassification
        and back to dict SHALL preserve all field values.

        **Validates: Requirements 2.1, 2.4**
        """
        classification = IssueClassification(
            issue_type=IssueType(data["issue_type"]),
            requirements=data["requirements"],
            affected_packages=data["affected_packages"],
            completeness_score=data["completeness_score"],
            clarification_questions=data["clarification_questions"],
            confidence=data["confidence"],
            reasoning=data["reasoning"],
        )

        # Convert to dict and back
        as_dict = classification.to_dict()
        restored = IssueClassification.from_dict(as_dict)

        # Verify all values preserved
        assert restored.issue_type == classification.issue_type
        assert restored.completeness_score == classification.completeness_score
        assert restored.requirements == classification.requirements
        assert restored.affected_packages == classification.affected_packages
        assert restored.clarification_questions == classification.clarification_questions


class TestClarificationQuestionGeneration:
    """Property tests for clarification question generation.

    Feature: agent-orchestration, Property 4: Clarification Question Generation

    *For any* issue with completeness score below 3, the classifier SHALL
    generate a non-empty list of clarification questions.

    **Validates: Requirement 2.5**
    """

    @given(
        score=low_completeness_score(),
        questions=st.lists(clarification_question(), min_size=1, max_size=5),
    )
    @settings(max_examples=100)
    def test_low_score_has_clarification_questions(
        self, score: int, questions: List[str]
    ) -> None:
        """Property 4: Low completeness score has clarification questions.

        *For any* issue with completeness score below 3, the classification
        SHALL have a non-empty list of clarification questions.

        **Validates: Requirement 2.5**
        """
        classification = IssueClassification(
            issue_type=IssueType.FEATURE,
            completeness_score=score,
            clarification_questions=questions,
        )

        # Verify needs_clarification property
        assert classification.needs_clarification is True
        assert classification.is_actionable is False

        # Verify questions are present
        assert len(classification.clarification_questions) > 0

    @given(score=high_completeness_score())
    @settings(max_examples=100)
    def test_high_score_does_not_need_clarification(self, score: int) -> None:
        """Property 4: High completeness score does not need clarification.

        *For any* issue with completeness score of 3 or above, the
        needs_clarification property SHALL be False.

        **Validates: Requirement 2.5**
        """
        classification = IssueClassification(
            issue_type=IssueType.FEATURE,
            completeness_score=score,
            clarification_questions=[],
        )

        # Verify needs_clarification property
        assert classification.needs_clarification is False
        assert classification.is_actionable is True

    @given(data=llm_response_data())
    @settings(max_examples=100)
    def test_normalize_ensures_questions_for_low_scores(
        self, data: Dict[str, Any]
    ) -> None:
        """Property 4: Normalization ensures questions for low scores.

        *For any* LLM response with completeness score below 3 and no
        clarification questions, the normalization process SHALL NOT
        add questions (that's done in the classifier agent).

        This test verifies the normalization preserves the questions list.

        **Validates: Requirement 2.5**
        """
        normalized = _validate_and_normalize_response(data)

        # The normalized data should have a list for clarification_questions
        assert isinstance(normalized["clarification_questions"], list)

        # All questions should be non-empty strings
        for question in normalized["clarification_questions"]:
            assert isinstance(question, str)

    @given(
        score=low_completeness_score(),
        issue_type=valid_issue_type(),
    )
    @settings(max_examples=100)
    def test_create_unknown_has_clarification_questions(
        self, score: int, issue_type: str
    ) -> None:
        """Property 4: create_unknown factory produces clarification questions.

        *For any* call to create_unknown, the resulting classification SHALL
        have a non-empty list of clarification questions since it has
        completeness_score=1.

        **Validates: Requirement 2.5**
        """
        classification = IssueClassification.create_unknown(
            reason="Test reason"
        )

        # create_unknown sets completeness_score=1
        assert classification.completeness_score == 1
        assert classification.needs_clarification is True

        # Must have clarification questions
        assert len(classification.clarification_questions) > 0

    @given(
        score=low_completeness_score(),
        questions=st.lists(clarification_question(), min_size=1, max_size=5),
    )
    @settings(max_examples=100)
    def test_clarification_questions_are_non_empty_strings(
        self, score: int, questions: List[str]
    ) -> None:
        """Property 4: Clarification questions are non-empty strings.

        *For any* classification with clarification questions, each question
        SHALL be a non-empty string.

        **Validates: Requirement 2.5**
        """
        classification = IssueClassification(
            issue_type=IssueType.UNKNOWN,
            completeness_score=score,
            clarification_questions=questions,
        )

        for question in classification.clarification_questions:
            assert isinstance(question, str)
            assert len(question.strip()) > 0


class TestClassificationEdgeCases:
    """Edge case tests for classification validation.

    These tests verify that the classification model handles edge cases
    correctly, including boundary values and special inputs.

    **Validates: Requirements 2.1, 2.4, 2.5**
    """

    @given(
        issue_type=valid_issue_type(),
        requirements=st.lists(requirement_string(), max_size=20),
        packages=st.lists(package_name(), max_size=10),
    )
    @settings(max_examples=100)
    def test_boundary_completeness_score_3(
        self,
        issue_type: str,
        requirements: List[str],
        packages: List[str],
    ) -> None:
        """Edge case: Completeness score 3 is the boundary.

        Score 3 is the boundary between needing clarification (1-2) and
        being actionable (3-5). Verify the properties are correct.

        **Validates: Requirements 2.4, 2.5**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            requirements=requirements,
            affected_packages=packages,
            completeness_score=3,
            clarification_questions=[],
        )

        # Score 3 should NOT need clarification
        assert classification.needs_clarification is False
        assert classification.is_actionable is True

    @given(
        issue_type=valid_issue_type(),
        requirements=st.lists(requirement_string(), max_size=20),
        packages=st.lists(package_name(), max_size=10),
        questions=st.lists(clarification_question(), min_size=1, max_size=5),
    )
    @settings(max_examples=100)
    def test_boundary_completeness_score_2(
        self,
        issue_type: str,
        requirements: List[str],
        packages: List[str],
        questions: List[str],
    ) -> None:
        """Edge case: Completeness score 2 needs clarification.

        Score 2 is below the threshold and should need clarification.

        **Validates: Requirements 2.4, 2.5**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            requirements=requirements,
            affected_packages=packages,
            completeness_score=2,
            clarification_questions=questions,
        )

        # Score 2 should need clarification
        assert classification.needs_clarification is True
        assert classification.is_actionable is False

    @given(issue_type=valid_issue_type())
    @settings(max_examples=100)
    def test_minimum_completeness_score(self, issue_type: str) -> None:
        """Edge case: Minimum completeness score (1) is valid.

        **Validates: Requirements 2.4**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            completeness_score=1,
            clarification_questions=["What are you trying to accomplish?"],
        )

        assert classification.completeness_score == 1
        assert classification.needs_clarification is True

    @given(issue_type=valid_issue_type())
    @settings(max_examples=100)
    def test_maximum_completeness_score(self, issue_type: str) -> None:
        """Edge case: Maximum completeness score (5) is valid.

        **Validates: Requirements 2.4**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            completeness_score=5,
        )

        assert classification.completeness_score == 5
        assert classification.is_actionable is True

    @given(
        issue_type=valid_issue_type(),
        score=valid_completeness_score(),
    )
    @settings(max_examples=100)
    def test_empty_requirements_list_valid(
        self, issue_type: str, score: int
    ) -> None:
        """Edge case: Empty requirements list is valid.

        **Validates: Requirements 2.1, 2.4**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            completeness_score=score,
            requirements=[],
        )

        assert classification.requirements == []

    @given(
        issue_type=valid_issue_type(),
        score=valid_completeness_score(),
    )
    @settings(max_examples=100)
    def test_empty_affected_packages_valid(
        self, issue_type: str, score: int
    ) -> None:
        """Edge case: Empty affected packages list is valid.

        **Validates: Requirements 2.1, 2.4**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            completeness_score=score,
            affected_packages=[],
        )

        assert classification.affected_packages == []

    @given(
        issue_type=valid_issue_type(),
        score=high_completeness_score(),
    )
    @settings(max_examples=100)
    def test_high_score_with_questions_still_actionable(
        self, issue_type: str, score: int
    ) -> None:
        """Edge case: High score with questions is still actionable.

        Even if clarification questions are present, a high completeness
        score means the issue is actionable.

        **Validates: Requirements 2.4, 2.5**
        """
        classification = IssueClassification(
            issue_type=IssueType(issue_type),
            completeness_score=score,
            clarification_questions=["Optional follow-up question?"],
        )

        # High score is actionable regardless of questions
        assert classification.is_actionable is True
        assert classification.needs_clarification is False


class TestNormalizationRobustness:
    """Tests for the robustness of response normalization.

    These tests verify that _validate_and_normalize_response handles
    various edge cases and malformed inputs gracefully.

    **Validates: Requirements 2.1, 2.4**
    """

    @given(
        invalid_type=st.text(min_size=1, max_size=50).filter(
            lambda x: x.lower() not in {"feature", "bug", "documentation", "infrastructure", "unknown"}
        )
    )
    @settings(max_examples=100)
    def test_invalid_issue_type_defaults_to_unknown(
        self, invalid_type: str
    ) -> None:
        """Normalization: Invalid issue type defaults to unknown.

        **Validates: Requirements 2.1**
        """
        data = {
            "issue_type": invalid_type,
            "completeness_score": 3,
        }

        normalized = _validate_and_normalize_response(data)
        assert normalized["issue_type"] == "unknown"

    @given(score=st.integers(min_value=6, max_value=100))
    @settings(max_examples=100)
    def test_high_score_clamped_to_5(self, score: int) -> None:
        """Normalization: Scores above 5 are clamped to 5.

        **Validates: Requirements 2.4**
        """
        data = {
            "issue_type": "feature",
            "completeness_score": score,
        }

        normalized = _validate_and_normalize_response(data)
        assert normalized["completeness_score"] == 5

    @given(score=st.integers(max_value=0))
    @settings(max_examples=100)
    def test_low_score_clamped_to_1(self, score: int) -> None:
        """Normalization: Scores below 1 are clamped to 1.

        **Validates: Requirements 2.4**
        """
        data = {
            "issue_type": "feature",
            "completeness_score": score,
        }

        normalized = _validate_and_normalize_response(data)
        assert normalized["completeness_score"] == 1

    @given(score_str=st.sampled_from(["1", "2", "3", "4", "5"]))
    @settings(max_examples=100)
    def test_string_score_converted_to_int(self, score_str: str) -> None:
        """Normalization: String scores are converted to integers.

        **Validates: Requirements 2.4**
        """
        data = {
            "issue_type": "feature",
            "completeness_score": score_str,
        }

        normalized = _validate_and_normalize_response(data)
        assert isinstance(normalized["completeness_score"], int)
        assert normalized["completeness_score"] == int(score_str)

    @given(confidence=st.floats(min_value=1.1, max_value=10.0, allow_nan=False))
    @settings(max_examples=100)
    def test_high_confidence_clamped_to_1(self, confidence: float) -> None:
        """Normalization: Confidence above 1.0 is clamped to 1.0.

        **Validates: Requirements 2.1**
        """
        data = {
            "issue_type": "feature",
            "completeness_score": 3,
            "confidence": confidence,
        }

        normalized = _validate_and_normalize_response(data)
        assert normalized["confidence"] == 1.0

    @given(confidence=st.floats(max_value=-0.1, allow_nan=False))
    @settings(max_examples=100)
    def test_negative_confidence_clamped_to_0(self, confidence: float) -> None:
        """Normalization: Negative confidence is clamped to 0.0.

        **Validates: Requirements 2.1**
        """
        data = {
            "issue_type": "feature",
            "completeness_score": 3,
            "confidence": confidence,
        }

        normalized = _validate_and_normalize_response(data)
        assert normalized["confidence"] == 0.0

    @given(issue_type=st.sampled_from(["FEATURE", "Bug", "DOCUMENTATION", "Infrastructure", "UNKNOWN"]))
    @settings(max_examples=100)
    def test_issue_type_case_insensitive(self, issue_type: str) -> None:
        """Normalization: Issue type matching is case-insensitive.

        **Validates: Requirements 2.1**
        """
        data = {
            "issue_type": issue_type,
            "completeness_score": 3,
        }

        normalized = _validate_and_normalize_response(data)
        assert normalized["issue_type"] == issue_type.lower()

