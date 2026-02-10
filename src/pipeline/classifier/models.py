"""Issue classification models for the agent pipeline.

This module defines the data models for LLM-based issue classification,
including the issue type enumeration and classification result structure.

Requirements:
- 2.1: THE Issue_Intake_Agent SHALL use an LLM to classify issue type from:
       `feature`, `bug`, `documentation`, `infrastructure`, `unknown`
- 2.4: THE Issue_Intake_Agent SHALL assess issue completeness on a scale of 1-5

The models use Pydantic for validation, consistent with the pipeline's
approach in webhook/models.py, state/models.py, and github/models.py.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class IssueType(str, Enum):
    """Classification of GitHub issue types.

    The LLM classifier categorizes issues into one of these types to
    determine appropriate handling in the agent pipeline.

    Attributes:
        FEATURE: A request for new functionality or enhancement.
        BUG: A report of incorrect or unexpected behavior.
        DOCUMENTATION: A request for documentation changes or additions.
        INFRASTRUCTURE: A request for infrastructure, deployment, or DevOps changes.
        UNKNOWN: Issue type could not be determined from the content.
    """

    FEATURE = "feature"
    BUG = "bug"
    DOCUMENTATION = "documentation"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"


class IssueClassification(BaseModel):
    """Result of LLM-based issue classification.

    This model contains the structured output from the issue classifier,
    including the determined issue type, extracted requirements, affected
    packages, and a completeness assessment.

    The completeness_score determines whether the issue has sufficient
    detail for implementation. Scores below 3 trigger clarification
    questions to be posted to the issue.

    Attributes:
        issue_type: The classified type of the issue.
        requirements: List of requirements extracted from the issue body.
        affected_packages: List of package names that may need changes.
        completeness_score: Assessment of issue detail completeness (1-5).
            1 = Very incomplete, missing critical information
            2 = Incomplete, missing important details
            3 = Adequate, has minimum required information
            4 = Good, has clear requirements and context
            5 = Excellent, comprehensive with examples and acceptance criteria
        clarification_questions: Questions to ask when completeness < 3.
            Should be empty when completeness_score >= 3.
        confidence: Optional confidence score for the classification (0.0-1.0).
        reasoning: Optional explanation of the classification decision.
    """

    issue_type: IssueType = Field(
        ...,
        description="The classified type of the issue",
    )

    requirements: list[str] = Field(
        default_factory=list,
        description="List of requirements extracted from the issue body",
    )

    affected_packages: list[str] = Field(
        default_factory=list,
        description="List of package names that may need changes",
    )

    completeness_score: int = Field(
        ...,
        ge=1,
        le=5,
        description="Assessment of issue detail completeness (1-5)",
    )

    clarification_questions: list[str] = Field(
        default_factory=list,
        description="Questions to ask when completeness < 3",
    )

    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional confidence score for the classification (0.0-1.0)",
    )

    reasoning: Optional[str] = Field(
        default=None,
        description="Optional explanation of the classification decision",
    )

    @field_validator("completeness_score")
    @classmethod
    def validate_completeness_score(cls, v: int) -> int:
        """Validate completeness score is within valid range.

        The score must be an integer from 1 to 5 inclusive.
        This validator provides a clear error message for invalid values.

        Args:
            v: The completeness score to validate.

        Returns:
            int: The validated completeness score.

        Raises:
            ValueError: If the score is outside the valid range.
        """
        if not 1 <= v <= 5:
            raise ValueError(
                f"Completeness score must be between 1 and 5, got {v}"
            )
        return v

    @property
    def needs_clarification(self) -> bool:
        """Check if the issue needs clarification based on completeness.

        Issues with completeness_score below 3 are considered to need
        additional information before implementation can proceed.

        Returns:
            bool: True if completeness_score < 3, False otherwise.
        """
        return self.completeness_score < 3

    @property
    def is_actionable(self) -> bool:
        """Check if the issue has sufficient detail for implementation.

        An issue is actionable when it has a completeness score of 3 or
        higher, indicating it has at least the minimum required information.

        Returns:
            bool: True if completeness_score >= 3, False otherwise.
        """
        return self.completeness_score >= 3

    def to_dict(self) -> dict:
        """Convert classification to a dictionary for storage.

        This method serializes the classification for storage in the
        pipeline state's classification field.

        Returns:
            dict: Dictionary representation of the classification.
        """
        return {
            "issue_type": self.issue_type.value,
            "requirements": self.requirements,
            "affected_packages": self.affected_packages,
            "completeness_score": self.completeness_score,
            "clarification_questions": self.clarification_questions,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IssueClassification":
        """Create an IssueClassification from a dictionary.

        This factory method deserializes a classification from the
        pipeline state's classification field.

        Args:
            data: Dictionary containing classification data.

        Returns:
            IssueClassification: Reconstructed classification object.

        Raises:
            KeyError: If required fields are missing.
            ValueError: If field values are invalid.
        """
        return cls(
            issue_type=IssueType(data["issue_type"]),
            requirements=data.get("requirements", []),
            affected_packages=data.get("affected_packages", []),
            completeness_score=data["completeness_score"],
            clarification_questions=data.get("clarification_questions", []),
            confidence=data.get("confidence"),
            reasoning=data.get("reasoning"),
        )

    @classmethod
    def create_unknown(
        cls,
        reason: str = "Could not classify issue",
    ) -> "IssueClassification":
        """Create a classification for an unclassifiable issue.

        This factory method creates a default classification when the
        LLM cannot determine the issue type. The completeness score is
        set to 1 to trigger clarification.

        Args:
            reason: Explanation of why classification failed.

        Returns:
            IssueClassification: Classification with UNKNOWN type.
        """
        return cls(
            issue_type=IssueType.UNKNOWN,
            requirements=[],
            affected_packages=[],
            completeness_score=1,
            clarification_questions=[
                "Could you provide more details about what you're trying to accomplish?",
                "What is the expected behavior or outcome?",
            ],
            confidence=0.0,
            reasoning=reason,
        )
