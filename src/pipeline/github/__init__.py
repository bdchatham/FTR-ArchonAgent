"""GitHub API client for issue and PR interactions.

This module provides a wrapper around the GitHub API for:
- Creating comments on issues
- Managing labels (add/remove)
- Creating pull requests
- Requesting reviewers
- Orchestrating PR creation from pipeline results

Includes rate limiting and retry logic for API resilience.
"""

from src.pipeline.github.client import (
    GitHubAPIError,
    GitHubClient,
    RateLimitError,
)
from src.pipeline.github.models import PRCreateRequest, PRCreateResult
from src.pipeline.github.pr_creator import PRCreationResult, PRCreator

__all__ = [
    "GitHubAPIError",
    "GitHubClient",
    "PRCreateRequest",
    "PRCreateResult",
    "PRCreationResult",
    "PRCreator",
    "RateLimitError",
]
