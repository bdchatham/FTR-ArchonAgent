"""Clarification comment formatting for GitHub issues.

This module provides functions to format clarification questions as
GitHub-flavored markdown for posting as issue comments.

Requirements:
- 3.2: Clarification questions SHALL be posted as a comment on the issue
- 3.3: Comment SHALL be formatted as a GitHub-flavored markdown checklist

Source:
- src/pipeline/classifier/models.py (IssueClassification)
"""

from src.pipeline.classifier.models import IssueClassification


CLARIFICATION_HEADER = """## 🤖 Clarification Needed

Thank you for submitting this issue! Before I can proceed with implementation, I need some additional information. Please address the following questions:

"""

CLARIFICATION_FOOTER = """
---

*Once you've provided the requested information, I'll re-evaluate the issue and proceed with implementation if the details are sufficient.*
"""


def format_clarification_comment(classification: IssueClassification) -> str:
    """Format clarification questions as a GitHub markdown checklist.

    Creates a formatted comment with a header explaining the purpose,
    the clarification questions as a checklist, and a footer with
    instructions for the user.

    Args:
        classification: The issue classification containing clarification questions.

    Returns:
        A formatted markdown string ready to post as a GitHub comment.
        Returns an empty string if there are no clarification questions.

    Example:
        >>> classification = IssueClassification(
        ...     issue_type=IssueType.FEATURE,
        ...     completeness_score=2,
        ...     clarification_questions=[
        ...         "What is the expected behavior?",
        ...         "Which components are affected?",
        ...     ],
        ... )
        >>> comment = format_clarification_comment(classification)
        >>> print(comment)
        ## 🤖 Clarification Needed
        ...
        - [ ] What is the expected behavior?
        - [ ] Which components are affected?
        ...
    """
    if not classification.clarification_questions:
        return ""

    checklist_items = _format_questions_as_checklist(
        classification.clarification_questions
    )

    return f"{CLARIFICATION_HEADER}{checklist_items}{CLARIFICATION_FOOTER}"


def _format_questions_as_checklist(questions: list[str]) -> str:
    """Format a list of questions as GitHub markdown checklist items.

    Each question is formatted as an unchecked checkbox item:
    `- [ ] Question text`

    Args:
        questions: List of clarification questions.

    Returns:
        Formatted checklist string with each question on its own line.
    """
    checklist_lines = []
    for question in questions:
        sanitized_question = _sanitize_question(question)
        if sanitized_question:
            checklist_lines.append(f"- [ ] {sanitized_question}")

    return "\n".join(checklist_lines)


def _sanitize_question(question: str) -> str:
    """Sanitize a question for safe inclusion in markdown.

    Removes leading/trailing whitespace and ensures the question
    doesn't contain problematic characters that could break markdown.

    Args:
        question: The raw question string.

    Returns:
        Sanitized question string, or empty string if invalid.
    """
    if not question:
        return ""

    sanitized = question.strip()

    sanitized = sanitized.replace("\n", " ").replace("\r", " ")

    while "  " in sanitized:
        sanitized = sanitized.replace("  ", " ")

    return sanitized
