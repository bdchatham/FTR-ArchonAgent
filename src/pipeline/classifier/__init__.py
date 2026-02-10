"""LLM-based issue classification.

This module classifies GitHub issues using an LLM to determine:
- Issue type (feature, bug, documentation, infrastructure, unknown)
- Extracted requirements from issue body
- Affected packages
- Completeness score (1-5)
- Clarification questions when completeness < 3

It also provides formatting utilities for clarification comments and
label management for the clarification workflow.
"""

from src.pipeline.classifier.agent import ClassificationError, IssueClassifier
from src.pipeline.classifier.clarification import (
    NEEDS_CLARIFICATION_LABEL,
    ClarificationManager,
    determine_label_action,
)
from src.pipeline.classifier.formatting import format_clarification_comment
from src.pipeline.classifier.models import IssueClassification, IssueType

__all__ = [
    "ClassificationError",
    "ClarificationManager",
    "determine_label_action",
    "format_clarification_comment",
    "IssueClassification",
    "IssueClassifier",
    "IssueType",
    "NEEDS_CLARIFICATION_LABEL",
]
