"""Clarification workflow management for GitHub issues.

This module provides the ClarificationManager class that handles the
clarification workflow for issues that lack sufficient detail. It manages:
- Adding the needs-clarification label when completeness < 3
- Removing the label when completeness >= 3
- Posting clarification comments to issues

Requirements:
- 3.4: Add needs-clarification label when completeness < 3
- 3.5: Remove label when completeness >= 3
- 3.6: Label state should be consistent with completeness score

Source:
- src/pipeline/github/client.py (GitHubClient)
- src/pipeline/classifier/models.py (IssueClassification)
- src/pipeline/classifier/formatting.py (format_clarification_comment)
"""

import logging
from typing import Optional

from src.pipeline.classifier.formatting import format_clarification_comment
from src.pipeline.classifier.models import IssueClassification
from src.pipeline.github.client import GitHubClient


logger = logging.getLogger(__name__)


NEEDS_CLARIFICATION_LABEL = "needs-clarification"


class ClarificationManager:
    """Manages the clarification workflow for GitHub issues.

    This class handles adding and removing the needs-clarification label
    based on the issue's completeness score, and posting clarification
    comments when needed.

    The label state is kept consistent with the completeness score:
    - completeness < 3: label is added (issue needs more information)
    - completeness >= 3: label is removed (issue is actionable)

    Attributes:
        github_client: The GitHub API client for label operations.
        label_name: The name of the clarification label (default: "needs-clarification").

    Example:
        >>> client = GitHubClient(token="ghp_xxx")
        >>> manager = ClarificationManager(client)
        >>> await manager.update_clarification_state(
        ...     owner="org",
        ...     repo="repo",
        ...     issue_number=123,
        ...     classification=classification,
        ... )
    """

    def __init__(
        self,
        github_client: GitHubClient,
        label_name: str = NEEDS_CLARIFICATION_LABEL,
    ):
        """Initialize the clarification manager.

        Args:
            github_client: The GitHub API client for label operations.
            label_name: The name of the clarification label.
        """
        self.github_client = github_client
        self.label_name = label_name

    def should_add_label(self, classification: IssueClassification) -> bool:
        """Determine if the needs-clarification label should be added.

        The label should be added when the completeness score is below 3,
        indicating the issue lacks sufficient detail for implementation.

        Args:
            classification: The issue classification result.

        Returns:
            True if the label should be added, False otherwise.
        """
        return classification.completeness_score < 3

    def should_remove_label(self, classification: IssueClassification) -> bool:
        """Determine if the needs-clarification label should be removed.

        The label should be removed when the completeness score is 3 or
        above, indicating the issue has sufficient detail.

        Args:
            classification: The issue classification result.

        Returns:
            True if the label should be removed, False otherwise.
        """
        return classification.completeness_score >= 3

    async def add_clarification_label(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> None:
        """Add the needs-clarification label to an issue.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            issue_number: Issue number to label.
        """
        logger.info(
            "Adding clarification label to issue",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "label": self.label_name,
            },
        )

        await self.github_client.add_label(
            owner=owner,
            repo=repo,
            issue_number=issue_number,
            label=self.label_name,
        )

        logger.info(
            "Clarification label added successfully",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
            },
        )

    async def remove_clarification_label(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> None:
        """Remove the needs-clarification label from an issue.

        This method is idempotent - if the label is not present,
        no error is raised.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            issue_number: Issue number to remove label from.
        """
        logger.info(
            "Removing clarification label from issue",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "label": self.label_name,
            },
        )

        await self.github_client.remove_label(
            owner=owner,
            repo=repo,
            issue_number=issue_number,
            label=self.label_name,
        )

        logger.info(
            "Clarification label removed successfully",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
            },
        )

    async def post_clarification_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        classification: IssueClassification,
    ) -> Optional[dict]:
        """Post a clarification comment to an issue.

        Formats the clarification questions from the classification as
        a GitHub markdown checklist and posts it as a comment.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            issue_number: Issue number to comment on.
            classification: The issue classification with clarification questions.

        Returns:
            The created comment data from GitHub API, or None if no
            clarification questions were present.
        """
        comment_body = format_clarification_comment(classification)

        if not comment_body:
            logger.debug(
                "No clarification questions to post",
                extra={
                    "owner": owner,
                    "repo": repo,
                    "issue_number": issue_number,
                },
            )
            return None

        logger.info(
            "Posting clarification comment to issue",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "questions_count": len(classification.clarification_questions),
            },
        )

        result = await self.github_client.create_comment(
            owner=owner,
            repo=repo,
            issue_number=issue_number,
            body=comment_body,
        )

        logger.info(
            "Clarification comment posted successfully",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "comment_id": result.get("id"),
            },
        )

        return result

    async def update_clarification_state(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        classification: IssueClassification,
        post_comment: bool = True,
    ) -> None:
        """Update the clarification state for an issue based on classification.

        This method ensures the label state is consistent with the
        completeness score:
        - If completeness < 3: adds the label and optionally posts a comment
        - If completeness >= 3: removes the label

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            issue_number: Issue number to update.
            classification: The issue classification result.
            post_comment: Whether to post a clarification comment when
                         adding the label. Default is True.
        """
        logger.info(
            "Updating clarification state for issue",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "completeness_score": classification.completeness_score,
                "needs_clarification": classification.needs_clarification,
            },
        )

        if self.should_add_label(classification):
            await self.add_clarification_label(owner, repo, issue_number)

            if post_comment:
                await self.post_clarification_comment(
                    owner, repo, issue_number, classification
                )

        elif self.should_remove_label(classification):
            await self.remove_clarification_label(owner, repo, issue_number)

        logger.info(
            "Clarification state updated successfully",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "label_action": (
                    "added" if classification.needs_clarification else "removed"
                ),
            },
        )


def determine_label_action(
    classification: IssueClassification,
) -> str:
    """Determine what label action should be taken based on classification.

    This is a pure function that determines the appropriate label action
    without performing any side effects. Useful for testing and validation.

    Args:
        classification: The issue classification result.

    Returns:
        One of: "add", "remove", or "none"
        - "add": Label should be added (completeness < 3)
        - "remove": Label should be removed (completeness >= 3)
        - "none": No action needed (edge case, shouldn't normally occur)
    """
    if classification.completeness_score < 3:
        return "add"
    elif classification.completeness_score >= 3:
        return "remove"
    return "none"
