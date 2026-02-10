"""GitHub webhook handling for the agent pipeline.

This module receives and parses GitHub webhook events, specifically:
- issues.opened - New issue created
- issues.edited - Issue content updated
- issues.labeled - Label added to issue

The webhook handler trusts that signature validation is performed by the
Tekton EventListener before events reach this service.
"""

from .handler import WebhookHandler, create_webhook_handler
from .models import GitHubIssueEvent, IssueAction

__all__ = [
    "GitHubIssueEvent",
    "IssueAction",
    "WebhookHandler",
    "create_webhook_handler",
]
