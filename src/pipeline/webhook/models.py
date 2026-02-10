"""GitHub webhook event models for the agent pipeline.

This module defines the data models for GitHub webhook events, specifically
for issue-related events that trigger the agent orchestration pipeline.

Requirements:
- 1.4: WHEN an `issues.opened` event is received THEN the Webhook_Receiver
       SHALL enqueue the issue for intake processing
- 1.6: THE Webhook_Receiver SHALL acknowledge webhooks within 10 seconds
       to prevent GitHub retries

The models use Pydantic for validation, consistent with the pipeline's
configuration approach in config.py.
"""

from enum import Enum

from pydantic import BaseModel, Field


class IssueAction(str, Enum):
    """GitHub issue event action types.

    These are the issue event actions that the agent pipeline processes.
    The pipeline filters for issues with the 'archon-automate' label.

    Attributes:
        OPENED: A new issue was created. Triggers initial intake processing.
        EDITED: An existing issue was modified. Used to re-evaluate issues
                that were previously marked as needing clarification.
        LABELED: A label was added to an issue. Can trigger processing if
                 the 'archon-automate' label is added.
    """

    OPENED = "opened"
    EDITED = "edited"
    LABELED = "labeled"


class GitHubIssueEvent(BaseModel):
    """Parsed GitHub issue webhook event.

    This model represents the essential data extracted from a GitHub
    issue webhook payload. The Tekton EventListener validates the webhook
    signature before forwarding to this service.

    Attributes:
        action: The type of issue event (opened, edited, labeled).
        issue_number: The issue number within the repository.
        title: The issue title text.
        body: The issue body/description text. May be empty.
        labels: List of label names attached to the issue.
        repository: The repository name (without owner prefix).
        owner: The repository owner (user or organization).
        author: The GitHub username who created the issue.
    """

    action: IssueAction = Field(
        ...,
        description="The type of issue event that triggered the webhook",
    )

    issue_number: int = Field(
        ...,
        gt=0,
        description="The issue number within the repository (positive integer)",
    )

    title: str = Field(
        ...,
        min_length=1,
        description="The issue title text (cannot be empty)",
    )

    body: str = Field(
        default="",
        description="The issue body/description text (may be empty)",
    )

    labels: list[str] = Field(
        default_factory=list,
        description="List of label names attached to the issue",
    )

    repository: str = Field(
        ...,
        min_length=1,
        description="The repository name without owner prefix",
    )

    owner: str = Field(
        ...,
        min_length=1,
        description="The repository owner (user or organization)",
    )

    author: str = Field(
        ...,
        min_length=1,
        description="The GitHub username who created the issue",
    )

    @property
    def issue_id(self) -> str:
        """Generate the canonical issue identifier.

        Returns:
            str: Issue ID in format "{owner}/{repository}#{issue_number}"
        """
        return f"{self.owner}/{self.repository}#{self.issue_number}"

    @property
    def full_repository(self) -> str:
        """Generate the full repository path.

        Returns:
            str: Repository path in format "{owner}/{repository}"
        """
        return f"{self.owner}/{self.repository}"

    def has_label(self, label_name: str) -> bool:
        """Check if the issue has a specific label.

        Args:
            label_name: The label name to check for (case-sensitive).

        Returns:
            bool: True if the issue has the specified label.
        """
        return label_name in self.labels
