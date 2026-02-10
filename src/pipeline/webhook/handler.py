"""GitHub webhook handler for the agent pipeline.

This module provides the WebhookHandler class for parsing GitHub webhook
events. Signature validation is handled by the Tekton EventListener before
events reach this service, so we trust incoming requests.

Requirements:
- 1.4: WHEN an `issues.opened` event is received THEN the Webhook_Receiver
       SHALL enqueue the issue for intake processing
- 1.5: THE Webhook_Receiver SHALL extract: issue number, title, body, labels,
       repository, author from the event payload
- 1.6: THE Webhook_Receiver SHALL acknowledge webhooks within 10 seconds
       to prevent GitHub retries

GitHub Webhook Payload Structure (issues event):
{
  "action": "opened",
  "issue": {
    "number": 123,
    "title": "Issue title",
    "body": "Issue body",
    "labels": [{"name": "bug"}, {"name": "archon-automate"}],
    "user": {"login": "username"}
  },
  "repository": {
    "name": "repo-name",
    "owner": {"login": "owner-name"}
  }
}
"""

import logging
from typing import Any, Dict, List, Optional

from .models import GitHubIssueEvent, IssueAction

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Handler for parsing GitHub webhook events.

    This handler parses raw GitHub webhook payloads into structured
    GitHubIssueEvent objects. Signature validation is performed by the
    Tekton EventListener before events reach this service.

    The handler is designed to be fast and return quickly to satisfy
    the 10-second acknowledgment requirement (Requirement 1.6).

    Attributes:
        secret: The webhook secret (retained for potential future use,
                but signature validation is handled by EventListener).
    """

    def __init__(self, secret: str) -> None:
        """Initialize the webhook handler.

        Args:
            secret: The GitHub webhook secret. While signature validation
                    is handled by the Tekton EventListener, the secret is
                    retained for potential future use or local testing.
        """
        self.secret = secret

    def parse_issue_event(self, payload: Dict[str, Any]) -> Optional[GitHubIssueEvent]:
        """Parse a GitHub issue event from a webhook payload.

        Extracts issue data from the raw webhook payload and returns a
        structured GitHubIssueEvent object. Returns None for invalid
        payloads or unsupported event types.

        Requirement 1.5: Extract issue number, title, body, labels,
        repository, and author from the event payload.

        Args:
            payload: The raw webhook payload as a dictionary.

        Returns:
            GitHubIssueEvent if parsing succeeds, None otherwise.
            Returns None for:
            - Missing required fields
            - Invalid action types (not opened, edited, or labeled)
            - Malformed payload structure
        """
        if not isinstance(payload, dict):
            logger.warning("Invalid payload: expected dict, got %s", type(payload))
            return None

        try:
            # Extract and validate action
            action_str = payload.get("action")
            if action_str is None:
                logger.warning("Missing 'action' field in payload")
                return None

            action = self._parse_action(action_str)
            if action is None:
                logger.debug(
                    "Ignoring unsupported action type: %s",
                    action_str,
                )
                return None

            # Extract issue data
            issue_data = payload.get("issue")
            if not isinstance(issue_data, dict):
                logger.warning(
                    "Missing or invalid 'issue' field in payload: %s",
                    type(issue_data),
                )
                return None

            # Extract repository data
            repo_data = payload.get("repository")
            if not isinstance(repo_data, dict):
                logger.warning(
                    "Missing or invalid 'repository' field in payload: %s",
                    type(repo_data),
                )
                return None

            # Extract required fields from issue
            issue_number = issue_data.get("number")
            if not isinstance(issue_number, int) or issue_number <= 0:
                logger.warning(
                    "Invalid issue number: %s (type: %s)",
                    issue_number,
                    type(issue_number),
                )
                return None

            title = issue_data.get("title")
            if not isinstance(title, str) or not title.strip():
                logger.warning("Invalid or empty issue title: %s", title)
                return None

            # Body can be None or empty string
            body = issue_data.get("body")
            if body is None:
                body = ""
            elif not isinstance(body, str):
                logger.warning("Invalid issue body type: %s", type(body))
                body = ""

            # Extract labels (list of objects with 'name' field)
            labels = self._extract_labels(issue_data.get("labels", []))

            # Extract author from issue.user.login
            user_data = issue_data.get("user")
            author = self._extract_user_login(user_data, "issue author")
            if author is None:
                return None

            # Extract repository name
            repo_name = repo_data.get("name")
            if not isinstance(repo_name, str) or not repo_name.strip():
                logger.warning("Invalid or empty repository name: %s", repo_name)
                return None

            # Extract owner from repository.owner.login
            owner_data = repo_data.get("owner")
            owner = self._extract_user_login(owner_data, "repository owner")
            if owner is None:
                return None

            # Create and return the event
            event = GitHubIssueEvent(
                action=action,
                issue_number=issue_number,
                title=title.strip(),
                body=body,
                labels=labels,
                repository=repo_name.strip(),
                owner=owner,
                author=author,
            )

            logger.info(
                "Parsed issue event: action=%s, issue=%s",
                action.value,
                event.issue_id,
            )

            return event

        except Exception as e:
            logger.exception("Unexpected error parsing webhook payload: %s", e)
            return None

    def _parse_action(self, action_str: str) -> Optional[IssueAction]:
        """Parse the action string into an IssueAction enum.

        Args:
            action_str: The action string from the webhook payload.

        Returns:
            IssueAction if valid, None otherwise.
        """
        if not isinstance(action_str, str):
            return None

        try:
            return IssueAction(action_str)
        except ValueError:
            return None

    def _extract_labels(self, labels_data: Any) -> List[str]:
        """Extract label names from the labels array.

        GitHub sends labels as an array of objects with 'name' field:
        [{"name": "bug"}, {"name": "archon-automate"}]

        Args:
            labels_data: The labels array from the issue data.

        Returns:
            List of label name strings. Invalid entries are skipped.
        """
        if not isinstance(labels_data, list):
            logger.debug("Labels is not a list: %s", type(labels_data))
            return []

        labels = []
        for label in labels_data:
            if isinstance(label, dict):
                name = label.get("name")
                if isinstance(name, str) and name.strip():
                    labels.append(name.strip())
            elif isinstance(label, str) and label.strip():
                # Handle case where labels might be plain strings
                labels.append(label.strip())

        return labels

    def _extract_user_login(
        self, user_data: Any, context: str
    ) -> Optional[str]:
        """Extract the login field from a user object.

        Args:
            user_data: The user object containing a 'login' field.
            context: Description of the user for logging purposes.

        Returns:
            The login string if valid, None otherwise.
        """
        if not isinstance(user_data, dict):
            logger.warning(
                "Missing or invalid %s data: %s",
                context,
                type(user_data),
            )
            return None

        login = user_data.get("login")
        if not isinstance(login, str) or not login.strip():
            logger.warning("Invalid or empty %s login: %s", context, login)
            return None

        return login.strip()


def create_webhook_handler(secret: str) -> WebhookHandler:
    """Factory function to create a WebhookHandler instance.

    Args:
        secret: The GitHub webhook secret.

    Returns:
        A configured WebhookHandler instance.
    """
    return WebhookHandler(secret=secret)
