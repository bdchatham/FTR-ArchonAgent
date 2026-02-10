"""Context file generation for provisioned workspaces.

Generates context.md and task.md files that provide Kiro CLI with the
information needed for autonomous implementation. context.md contains
issue details, classification results, and knowledge context from
semantic search. task.md contains the implementation task summary.

Requirements:
- 4.3: Create context.md with issue details, classification, relevant docs
- 4.4: Query Knowledge_Provider for relevant context in context.md
- 4.5: Resolve Knowledge_Provider from KnowledgeBase resource in config
- 4.6: Create task.md with implementation task summary
"""

import logging
from pathlib import Path
from typing import Optional

from src.pipeline.classifier.models import IssueClassification
from src.pipeline.knowledge.provider import KnowledgeProvider

logger = logging.getLogger(__name__)


async def generate_context_file(
    workspace_path: Path,
    issue_title: str,
    issue_body: str,
    classification: IssueClassification,
    knowledge_provider: Optional[KnowledgeProvider] = None,
) -> Path:
    """Generate context.md with issue details and knowledge context.

    Writes a Markdown file containing the issue description, classification
    results, and (when a KnowledgeProvider is available) semantically
    retrieved documentation context.

    Args:
        workspace_path: Directory where context.md will be written.
        issue_title: Title of the GitHub issue.
        issue_body: Body text of the GitHub issue.
        classification: LLM classification of the issue.
        knowledge_provider: Optional provider for knowledge retrieval.

    Returns:
        Path to the written context.md file.
    """
    knowledge_context = await _retrieve_knowledge_context(
        issue_title, classification, knowledge_provider
    )

    content = _build_context_markdown(
        issue_title, issue_body, classification, knowledge_context
    )

    context_file = workspace_path / "context.md"
    context_file.write_text(content, encoding="utf-8")

    logger.info("Generated context.md", extra={"path": str(context_file)})
    return context_file


async def generate_task_file(
    workspace_path: Path,
    issue_title: str,
    issue_body: str,
    classification: IssueClassification,
) -> Path:
    """Generate task.md with the implementation task summary.

    Writes a Markdown file summarising what Kiro CLI should implement,
    derived from the issue content and classification.

    Args:
        workspace_path: Directory where task.md will be written.
        issue_title: Title of the GitHub issue.
        issue_body: Body text of the GitHub issue.
        classification: LLM classification of the issue.

    Returns:
        Path to the written task.md file.
    """
    content = _build_task_markdown(issue_title, issue_body, classification)

    task_file = workspace_path / "task.md"
    task_file.write_text(content, encoding="utf-8")

    logger.info("Generated task.md", extra={"path": str(task_file)})
    return task_file


async def generate_workspace_files(
    workspace_path: Path,
    issue_title: str,
    issue_body: str,
    classification: IssueClassification,
    knowledge_provider: Optional[KnowledgeProvider] = None,
) -> tuple[Path, Path]:
    """Generate both context.md and task.md for a workspace.

    Convenience wrapper that produces both files in a single call.

    Args:
        workspace_path: Directory where files will be written.
        issue_title: Title of the GitHub issue.
        issue_body: Body text of the GitHub issue.
        classification: LLM classification of the issue.
        knowledge_provider: Optional provider for knowledge retrieval.

    Returns:
        Tuple of (context_file_path, task_file_path).
    """
    context_file = await generate_context_file(
        workspace_path, issue_title, issue_body,
        classification, knowledge_provider,
    )
    task_file = await generate_task_file(
        workspace_path, issue_title, issue_body, classification,
    )
    return context_file, task_file


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _retrieve_knowledge_context(
    issue_title: str,
    classification: IssueClassification,
    knowledge_provider: Optional[KnowledgeProvider],
) -> str:
    """Query the KnowledgeProvider for relevant context.

    Builds a search query from the issue title and requirements, then
    calls combined_context() on the provider. Returns an empty string
    when no provider is available or the query fails.

    Args:
        issue_title: Title of the GitHub issue.
        classification: LLM classification with requirements.
        knowledge_provider: Optional provider for knowledge retrieval.

    Returns:
        Formatted knowledge context string, or empty string.
    """
    if knowledge_provider is None:
        return ""

    search_query = _build_search_query(issue_title, classification)

    try:
        return await knowledge_provider.combined_context(search_query)
    except Exception:
        logger.exception("Knowledge retrieval failed, continuing without context")
        return ""


def _build_search_query(
    issue_title: str,
    classification: IssueClassification,
) -> str:
    """Build a semantic search query from issue metadata.

    Combines the issue title with extracted requirements to form a
    richer search query for the knowledge provider.

    Args:
        issue_title: Title of the GitHub issue.
        classification: LLM classification with requirements.

    Returns:
        Combined search query string.
    """
    parts = [issue_title]
    parts.extend(classification.requirements)
    return " ".join(parts)


def _build_context_markdown(
    issue_title: str,
    issue_body: str,
    classification: IssueClassification,
    knowledge_context: str,
) -> str:
    """Assemble the full context.md Markdown content.

    Args:
        issue_title: Title of the GitHub issue.
        issue_body: Body text of the GitHub issue.
        classification: LLM classification of the issue.
        knowledge_context: Pre-retrieved knowledge context string.

    Returns:
        Complete Markdown string for context.md.
    """
    sections: list[str] = []

    sections.append(f"# Context: {issue_title}\n")
    sections.append(_format_issue_section(issue_title, issue_body))
    sections.append(_format_classification_section(classification))

    if knowledge_context:
        sections.append(_format_knowledge_section(knowledge_context))

    return "\n".join(sections)


def _format_issue_section(issue_title: str, issue_body: str) -> str:
    """Format the issue details section of context.md."""
    lines = [
        "## Issue Details\n",
        f"**Title:** {issue_title}\n",
    ]
    if issue_body:
        lines.append(f"**Description:**\n\n{issue_body}\n")
    else:
        lines.append("**Description:** _No description provided._\n")
    return "\n".join(lines)


def _format_classification_section(
    classification: IssueClassification,
) -> str:
    """Format the classification results section of context.md."""
    lines = [
        "## Classification\n",
        f"- **Type:** {classification.issue_type.value}",
        f"- **Completeness:** {classification.completeness_score}/5",
    ]

    if classification.affected_packages:
        packages = ", ".join(classification.affected_packages)
        lines.append(f"- **Affected Packages:** {packages}")

    if classification.requirements:
        lines.append("\n### Requirements\n")
        for req in classification.requirements:
            lines.append(f"- {req}")

    lines.append("")
    return "\n".join(lines)


def _format_knowledge_section(knowledge_context: str) -> str:
    """Format the knowledge context section of context.md."""
    return f"## Knowledge Context\n\n{knowledge_context}\n"


def _build_task_markdown(
    issue_title: str,
    issue_body: str,
    classification: IssueClassification,
) -> str:
    """Assemble the full task.md Markdown content.

    Args:
        issue_title: Title of the GitHub issue.
        issue_body: Body text of the GitHub issue.
        classification: LLM classification of the issue.

    Returns:
        Complete Markdown string for task.md.
    """
    sections: list[str] = []

    sections.append(f"# Task: {issue_title}\n")
    sections.append(f"**Type:** {classification.issue_type.value}\n")
    sections.append("## Objective\n")
    sections.append(_build_objective(issue_title, issue_body))

    if classification.requirements:
        sections.append("## Requirements\n")
        for i, req in enumerate(classification.requirements, 1):
            sections.append(f"{i}. {req}")
        sections.append("")

    if classification.affected_packages:
        sections.append("## Affected Packages\n")
        for pkg in classification.affected_packages:
            sections.append(f"- {pkg}")
        sections.append("")

    return "\n".join(sections)


def _build_objective(issue_title: str, issue_body: str) -> str:
    """Derive a concise objective statement from the issue content.

    Uses the issue body when available; falls back to the title.

    Args:
        issue_title: Title of the GitHub issue.
        issue_body: Body text of the GitHub issue.

    Returns:
        Objective paragraph string.
    """
    if issue_body:
        return f"{issue_body}\n"
    return f"{issue_title}\n"
