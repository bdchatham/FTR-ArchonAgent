"""LLM-based issue classifier for the agent pipeline.

This module implements the IssueClassifier that uses an LLM to analyze
GitHub issues and extract structured classification data including:
- Issue type (feature, bug, documentation, infrastructure, unknown)
- Extracted requirements from the issue body
- Affected packages
- Completeness score (1-5)
- Clarification questions when completeness is below 3

The classifier uses LangChain with a vLLM-compatible endpoint for inference.

Requirements:
- 2.1: Classify issue type from: feature, bug, documentation, infrastructure, unknown
- 2.2: Extract structured requirements from the issue body
- 2.3: Identify affected packages from issue content and labels
- 2.4: Assess issue completeness on a scale of 1-5
- 2.5: Generate clarification questions when completeness < 3
- 2.6: Store classification results in structured format

Source:
- src/pipeline/classifier/models.py (IssueType, IssueClassification)
- src/pipeline/config.py (llm_url, llm_model)
"""

import json
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.pipeline.classifier.models import IssueClassification, IssueType


logger = logging.getLogger(__name__)


CLASSIFICATION_SYSTEM_PROMPT = """You are an expert software development issue classifier. Your task is to analyze GitHub issues and extract structured information.

You MUST respond with valid JSON only. Do not include any text before or after the JSON object.

Analyze the issue and provide:

1. **issue_type**: Classify as one of:
   - "feature": New functionality or enhancement requests
   - "bug": Reports of incorrect or unexpected behavior
   - "documentation": Documentation changes or additions
   - "infrastructure": DevOps, deployment, CI/CD, or infrastructure changes
   - "unknown": Cannot determine from the content

2. **requirements**: Extract specific requirements as a list of strings. Each requirement should be a clear, actionable statement.

3. **affected_packages**: Identify package/module names that may need changes based on the issue content.

4. **completeness_score**: Rate from 1-5:
   - 1: Very incomplete - missing critical information (what, why, where)
   - 2: Incomplete - missing important details (acceptance criteria, context)
   - 3: Adequate - has minimum required information to start work
   - 4: Good - clear requirements with context
   - 5: Excellent - comprehensive with examples and acceptance criteria

5. **clarification_questions**: If completeness_score < 3, provide specific questions to ask. Otherwise, leave empty.

6. **confidence**: Your confidence in the classification (0.0 to 1.0).

7. **reasoning**: Brief explanation of your classification decision.

Respond with this exact JSON structure:
{
  "issue_type": "feature|bug|documentation|infrastructure|unknown",
  "requirements": ["requirement 1", "requirement 2"],
  "affected_packages": ["package1", "package2"],
  "completeness_score": 1-5,
  "clarification_questions": ["question 1", "question 2"],
  "confidence": 0.0-1.0,
  "reasoning": "explanation"
}"""


def _build_classification_prompt(
    title: str,
    body: str,
    labels: list[str],
) -> str:
    """Build the user prompt for issue classification.

    Args:
        title: The issue title.
        body: The issue body/description.
        labels: List of labels attached to the issue.

    Returns:
        Formatted prompt string for the LLM.
    """
    labels_str = ", ".join(labels) if labels else "none"
    body_content = body if body else "(no description provided)"

    return f"""Analyze this GitHub issue:

**Title:** {title}

**Labels:** {labels_str}

**Description:**
{body_content}

Provide your analysis as JSON."""


def _parse_llm_response(response_text: str) -> dict[str, Any]:
    """Parse the LLM response text into a dictionary.

    Handles common LLM response quirks like markdown code blocks.

    Args:
        response_text: Raw text response from the LLM.

    Returns:
        Parsed dictionary from the JSON response.

    Raises:
        json.JSONDecodeError: If the response is not valid JSON.
    """
    text = response_text.strip()

    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return json.loads(text.strip())


def _validate_and_normalize_response(data: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the parsed LLM response.

    Ensures all required fields are present and have valid values.

    Args:
        data: Parsed dictionary from LLM response.

    Returns:
        Normalized dictionary with validated fields.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    issue_type_str = data.get("issue_type", "unknown").lower()
    valid_types = {t.value for t in IssueType}
    if issue_type_str not in valid_types:
        logger.warning(
            "Invalid issue type from LLM, defaulting to unknown",
            extra={"received_type": issue_type_str},
        )
        issue_type_str = "unknown"

    completeness_score = data.get("completeness_score", 1)
    if not isinstance(completeness_score, int):
        try:
            completeness_score = int(completeness_score)
        except (ValueError, TypeError):
            completeness_score = 1

    completeness_score = max(1, min(5, completeness_score))

    requirements = data.get("requirements", [])
    if not isinstance(requirements, list):
        requirements = []
    requirements = [str(r) for r in requirements if r]

    affected_packages = data.get("affected_packages", [])
    if not isinstance(affected_packages, list):
        affected_packages = []
    affected_packages = [str(p) for p in affected_packages if p]

    clarification_questions = data.get("clarification_questions", [])
    if not isinstance(clarification_questions, list):
        clarification_questions = []
    clarification_questions = [str(q) for q in clarification_questions if q]

    confidence = data.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            confidence = None

    reasoning = data.get("reasoning")
    if reasoning is not None:
        reasoning = str(reasoning)

    return {
        "issue_type": issue_type_str,
        "requirements": requirements,
        "affected_packages": affected_packages,
        "completeness_score": completeness_score,
        "clarification_questions": clarification_questions,
        "confidence": confidence,
        "reasoning": reasoning,
    }


class ClassificationError(Exception):
    """Raised when issue classification fails.

    Attributes:
        message: Human-readable error description.
        cause: The underlying exception that caused the failure.
    """

    def __init__(self, message: str, cause: Optional[Exception] = None):
        self.message = message
        self.cause = cause
        super().__init__(message)


class IssueClassifier:
    """LLM-based classifier for GitHub issues.

    This classifier uses a language model to analyze GitHub issues and
    extract structured classification data. It connects to a vLLM-compatible
    endpoint using LangChain's ChatOpenAI client.

    The classifier extracts:
    - Issue type (feature, bug, documentation, infrastructure, unknown)
    - Requirements from the issue body
    - Affected packages
    - Completeness score (1-5)
    - Clarification questions when completeness is below 3

    Attributes:
        llm_url: URL of the vLLM-compatible endpoint.
        model_name: Name of the model to use for inference.
        timeout: Request timeout in seconds.
        temperature: Sampling temperature for the LLM.

    Example:
        >>> classifier = IssueClassifier(
        ...     llm_url="http://localhost:8000/v1",
        ...     model_name="Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
        ... )
        >>> result = await classifier.classify(
        ...     title="Add user authentication",
        ...     body="We need to add OAuth2 support...",
        ...     labels=["enhancement"],
        ... )
        >>> print(result.issue_type)
        IssueType.FEATURE
    """

    def __init__(
        self,
        llm_url: str,
        model_name: str,
        timeout: float = 30.0,
        temperature: float = 0.1,
    ):
        """Initialize the issue classifier.

        Args:
            llm_url: URL of the vLLM-compatible endpoint (e.g., http://localhost:8000/v1).
            model_name: Name of the model to use for inference.
            timeout: Request timeout in seconds.
            temperature: Sampling temperature (lower = more deterministic).
        """
        self.llm_url = llm_url
        self.model_name = model_name
        self.timeout = timeout
        self.temperature = temperature
        self._llm: Optional[ChatOpenAI] = None

    @property
    def llm(self) -> ChatOpenAI:
        """Get the LLM client, creating it if necessary.

        Returns:
            The ChatOpenAI client instance.
        """
        if self._llm is None:
            self._llm = ChatOpenAI(
                base_url=self.llm_url,
                model=self.model_name,
                temperature=self.temperature,
                timeout=self.timeout,
                api_key="not-needed",
            )
        return self._llm

    async def classify(
        self,
        title: str,
        body: str,
        labels: list[str],
    ) -> IssueClassification:
        """Classify a GitHub issue using the LLM.

        Analyzes the issue title, body, and labels to extract structured
        classification data including issue type, requirements, affected
        packages, and completeness assessment.

        Args:
            title: The issue title.
            body: The issue body/description.
            labels: List of labels attached to the issue.

        Returns:
            IssueClassification with the analysis results.

        Note:
            If classification fails for any reason, returns a default
            classification with IssueType.UNKNOWN and completeness_score=1.
        """
        logger.info(
            "Classifying issue",
            extra={
                "title": title[:100],
                "body_length": len(body) if body else 0,
                "labels": labels,
            },
        )

        try:
            classification = await self._perform_classification(title, body, labels)
            logger.info(
                "Issue classified successfully",
                extra={
                    "issue_type": classification.issue_type.value,
                    "completeness_score": classification.completeness_score,
                    "requirements_count": len(classification.requirements),
                    "packages_count": len(classification.affected_packages),
                },
            )
            return classification

        except Exception as e:
            logger.error(
                "Issue classification failed",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "title": title[:100],
                },
            )
            return IssueClassification.create_unknown(
                reason=f"Classification failed: {e}"
            )

    async def _perform_classification(
        self,
        title: str,
        body: str,
        labels: list[str],
    ) -> IssueClassification:
        """Perform the actual LLM classification.

        Args:
            title: The issue title.
            body: The issue body/description.
            labels: List of labels attached to the issue.

        Returns:
            IssueClassification with the analysis results.

        Raises:
            ClassificationError: If the LLM call or parsing fails.
        """
        user_prompt = _build_classification_prompt(title, body, labels)

        messages = [
            SystemMessage(content=CLASSIFICATION_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            response_text = response.content
        except Exception as e:
            raise ClassificationError(f"LLM invocation failed: {e}", cause=e)

        if not isinstance(response_text, str):
            raise ClassificationError(
                f"Unexpected response type: {type(response_text)}"
            )

        try:
            parsed_data = _parse_llm_response(response_text)
        except json.JSONDecodeError as e:
            logger.warning(
                "Failed to parse LLM response as JSON",
                extra={
                    "response_preview": response_text[:200],
                    "error": str(e),
                },
            )
            raise ClassificationError(f"Invalid JSON response: {e}", cause=e)

        try:
            normalized_data = _validate_and_normalize_response(parsed_data)
        except Exception as e:
            raise ClassificationError(f"Response validation failed: {e}", cause=e)

        if (
            normalized_data["completeness_score"] < 3
            and not normalized_data["clarification_questions"]
        ):
            normalized_data["clarification_questions"] = [
                "Could you provide more details about the expected behavior?",
                "What specific changes or features are you requesting?",
            ]

        return IssueClassification(
            issue_type=IssueType(normalized_data["issue_type"]),
            requirements=normalized_data["requirements"],
            affected_packages=normalized_data["affected_packages"],
            completeness_score=normalized_data["completeness_score"],
            clarification_questions=normalized_data["clarification_questions"],
            confidence=normalized_data["confidence"],
            reasoning=normalized_data["reasoning"],
        )

    async def health_check(self) -> bool:
        """Check if the LLM endpoint is accessible.

        Makes a simple request to verify the LLM is reachable.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            messages = [HumanMessage(content="Hello")]
            await self.llm.ainvoke(messages)
            return True
        except Exception as e:
            logger.warning(
                "LLM health check failed",
                extra={"error": str(e)},
            )
            return False
