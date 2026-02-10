"""GitHub API client for issue and PR interactions.

This module provides an async wrapper around the GitHub API for:
- Creating comments on issues
- Managing labels (add/remove)
- Creating pull requests
- Requesting reviewers

Includes rate limiting and retry logic for API resilience.

Requirements:
- 11.1: GitHub API client for issue/PR interactions
- 11.2: Create comments on issues
- 11.3: Manage labels (add/remove)
- 11.4: Create pull requests
- 11.5: Request reviewers
- 11.6: Rate limiting and retry logic

Source:
- src/pipeline/github/models.py (PRCreateRequest, PRCreateResult)
- src/pipeline/config.py (github_token, github_base_url)
"""

import asyncio
import logging
import random
import time
from typing import Any, Dict, List, Optional

import httpx

from src.pipeline.github.models import PRCreateRequest, PRCreateResult


logger = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    """Raised when a GitHub API request fails.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code from the response.
        response_body: Response body from GitHub API.
        request_url: The URL that was requested.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        request_url: Optional[str] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        self.request_url = request_url
        super().__init__(message)


class RateLimitError(GitHubAPIError):
    """Raised when GitHub API rate limit is exceeded.

    Attributes:
        reset_at: Unix timestamp when the rate limit resets.
        retry_after: Seconds to wait before retrying.
    """

    def __init__(
        self,
        message: str,
        reset_at: Optional[int] = None,
        retry_after: Optional[int] = None,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        self.reset_at = reset_at
        self.retry_after = retry_after


class GitHubClient:
    """Async GitHub API client with rate limiting and retry logic.

    This client provides methods for interacting with GitHub issues and
    pull requests. It implements:

    - Automatic retry with exponential backoff for transient failures
    - Rate limit handling by respecting X-RateLimit-* headers
    - Support for both github.com and GitHub Enterprise Server

    Attributes:
        token: GitHub API token (PAT or GitHub App token).
        base_url: Base URL for GitHub API (default: https://api.github.com).
        max_retries: Maximum number of retry attempts for transient failures.
        base_delay: Base delay in seconds for exponential backoff.
        max_delay: Maximum delay in seconds between retries.
        timeout: Request timeout in seconds.

    Example:
        >>> client = GitHubClient(token="ghp_xxx")
        >>> async with client:
        ...     await client.create_comment("owner", "repo", 123, "Hello!")

    Or without context manager:
        >>> client = GitHubClient(token="ghp_xxx")
        >>> await client.create_comment("owner", "repo", 123, "Hello!")
        >>> await client.close()
    """

    # HTTP status codes that should trigger a retry
    RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        timeout: float = 30.0,
    ):
        """Initialize the GitHub client.

        Args:
            token: GitHub API token for authentication.
            base_url: Base URL for GitHub API. Use this to support
                      GitHub Enterprise Server endpoints.
            max_retries: Maximum number of retry attempts.
            base_delay: Base delay in seconds for exponential backoff.
            max_delay: Maximum delay in seconds between retries.
            timeout: Request timeout in seconds.
        """
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client, creating it if necessary.

        Returns:
            The httpx AsyncClient instance.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._default_headers(),
                timeout=self.timeout,
            )
        return self._client

    def _default_headers(self) -> Dict[str, str]:
        """Build default headers for GitHub API requests.

        Returns:
            Dictionary of HTTP headers.
        """
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ArchonAgent-Pipeline/1.0",
        }

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "GitHubClient":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit - close the client."""
        await self.close()

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff delay with jitter.

        Uses exponential backoff with full jitter to prevent
        thundering herd problems.

        Args:
            attempt: The current retry attempt (0-indexed).

        Returns:
            Delay in seconds before the next retry.
        """
        exponential_delay = self.base_delay * (2 ** attempt)
        capped_delay = min(exponential_delay, self.max_delay)
        jitter = random.uniform(0, capped_delay)
        return jitter

    def _parse_rate_limit_headers(
        self,
        headers: httpx.Headers,
    ) -> Dict[str, Optional[int]]:
        """Parse rate limit information from response headers.

        Args:
            headers: Response headers from GitHub API.

        Returns:
            Dictionary with rate limit information:
            - limit: Maximum requests allowed
            - remaining: Requests remaining in current window
            - reset: Unix timestamp when limit resets
            - used: Requests used in current window
        """
        return {
            "limit": self._parse_int_header(headers, "x-ratelimit-limit"),
            "remaining": self._parse_int_header(headers, "x-ratelimit-remaining"),
            "reset": self._parse_int_header(headers, "x-ratelimit-reset"),
            "used": self._parse_int_header(headers, "x-ratelimit-used"),
        }

    def _parse_int_header(
        self,
        headers: httpx.Headers,
        name: str,
    ) -> Optional[int]:
        """Parse an integer header value.

        Args:
            headers: Response headers.
            name: Header name to parse.

        Returns:
            Integer value or None if not present/invalid.
        """
        value = headers.get(name)
        if value is not None:
            try:
                return int(value)
            except ValueError:
                pass
        return None

    async def _handle_rate_limit(
        self,
        response: httpx.Response,
    ) -> None:
        """Handle rate limit response by waiting until reset.

        Args:
            response: The rate-limited response from GitHub.

        Raises:
            RateLimitError: With information about when to retry.
        """
        rate_limit = self._parse_rate_limit_headers(response.headers)
        reset_at = rate_limit.get("reset")

        retry_after = None
        if reset_at is not None:
            retry_after = max(0, reset_at - int(time.time()))

        # Also check Retry-After header
        retry_after_header = response.headers.get("retry-after")
        if retry_after_header is not None:
            try:
                retry_after = int(retry_after_header)
            except ValueError:
                pass

        logger.warning(
            "GitHub API rate limit exceeded",
            extra={
                "reset_at": reset_at,
                "retry_after": retry_after,
                "limit": rate_limit.get("limit"),
                "used": rate_limit.get("used"),
            },
        )

        raise RateLimitError(
            message="GitHub API rate limit exceeded",
            status_code=response.status_code,
            reset_at=reset_at,
            retry_after=retry_after,
        )

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """Make an HTTP request with retry logic.

        This method implements exponential backoff with jitter for
        transient failures and respects GitHub's rate limit headers.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH).
            path: API path (e.g., /repos/owner/repo/issues/1/comments).
            json_data: Optional JSON body for the request.

        Returns:
            The HTTP response from GitHub.

        Raises:
            GitHubAPIError: If the request fails after all retries.
            RateLimitError: If rate limit is exceeded.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.request(
                    method=method,
                    url=path,
                    json=json_data,
                )

                # Check for rate limiting
                if response.status_code == 403:
                    remaining = self._parse_int_header(
                        response.headers,
                        "x-ratelimit-remaining",
                    )
                    if remaining is not None and remaining == 0:
                        await self._handle_rate_limit(response)

                if response.status_code == 429:
                    await self._handle_rate_limit(response)

                # Check for retryable errors
                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    if attempt < self.max_retries:
                        delay = self._calculate_backoff(attempt)
                        logger.warning(
                            "Retryable error from GitHub API",
                            extra={
                                "status_code": response.status_code,
                                "attempt": attempt + 1,
                                "max_retries": self.max_retries,
                                "delay": delay,
                                "path": path,
                            },
                        )
                        await asyncio.sleep(delay)
                        continue

                # Check for client/server errors
                if response.status_code >= 400:
                    error_body = response.text
                    logger.error(
                        "GitHub API error",
                        extra={
                            "status_code": response.status_code,
                            "path": path,
                            "method": method,
                            "response_body": error_body[:500],
                        },
                    )
                    raise GitHubAPIError(
                        message=f"GitHub API error: {response.status_code}",
                        status_code=response.status_code,
                        response_body=error_body,
                        request_url=str(response.url),
                    )

                return response

            except RateLimitError:
                raise
            except GitHubAPIError:
                raise
            except httpx.TimeoutException as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self._calculate_backoff(attempt)
                    logger.warning(
                        "Request timeout, retrying",
                        extra={
                            "attempt": attempt + 1,
                            "max_retries": self.max_retries,
                            "delay": delay,
                            "path": path,
                        },
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.RequestError as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self._calculate_backoff(attempt)
                    logger.warning(
                        "Request error, retrying",
                        extra={
                            "error": str(e),
                            "attempt": attempt + 1,
                            "max_retries": self.max_retries,
                            "delay": delay,
                            "path": path,
                        },
                    )
                    await asyncio.sleep(delay)
                    continue

        # All retries exhausted
        logger.error(
            "GitHub API request failed after all retries",
            extra={
                "path": path,
                "method": method,
                "max_retries": self.max_retries,
                "last_error": str(last_exception),
            },
        )
        raise GitHubAPIError(
            message=f"Request failed after {self.max_retries} retries: {last_exception}",
            request_url=f"{self.base_url}{path}",
        )

    async def create_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> Dict[str, Any]:
        """Create a comment on an issue.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            issue_number: Issue number to comment on.
            body: Comment body in markdown format.

        Returns:
            The created comment data from GitHub API.

        Raises:
            GitHubAPIError: If the request fails.
        """
        path = f"/repos/{owner}/{repo}/issues/{issue_number}/comments"

        logger.info(
            "Creating comment on issue",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "body_length": len(body),
            },
        )

        response = await self._request(
            method="POST",
            path=path,
            json_data={"body": body},
        )

        result = response.json()
        logger.info(
            "Comment created successfully",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "comment_id": result.get("id"),
            },
        )

        return result

    async def add_label(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        label: str,
    ) -> List[Dict[str, Any]]:
        """Add a label to an issue.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            issue_number: Issue number to label.
            label: Label name to add.

        Returns:
            List of all labels on the issue after adding.

        Raises:
            GitHubAPIError: If the request fails.
        """
        path = f"/repos/{owner}/{repo}/issues/{issue_number}/labels"

        logger.info(
            "Adding label to issue",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "label": label,
            },
        )

        response = await self._request(
            method="POST",
            path=path,
            json_data={"labels": [label]},
        )

        result = response.json()
        logger.info(
            "Label added successfully",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "label": label,
                "total_labels": len(result),
            },
        )

        return result

    async def remove_label(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        label: str,
    ) -> None:
        """Remove a label from an issue.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            issue_number: Issue number to remove label from.
            label: Label name to remove.

        Raises:
            GitHubAPIError: If the request fails (except 404 which is ignored).
        """
        # URL-encode the label name for the path
        encoded_label = label.replace(" ", "%20")
        path = f"/repos/{owner}/{repo}/issues/{issue_number}/labels/{encoded_label}"

        logger.info(
            "Removing label from issue",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "label": label,
            },
        )

        try:
            await self._request(method="DELETE", path=path)
            logger.info(
                "Label removed successfully",
                extra={
                    "owner": owner,
                    "repo": repo,
                    "issue_number": issue_number,
                    "label": label,
                },
            )
        except GitHubAPIError as e:
            # 404 means label wasn't on the issue - that's fine
            if e.status_code == 404:
                logger.debug(
                    "Label not found on issue (already removed)",
                    extra={
                        "owner": owner,
                        "repo": repo,
                        "issue_number": issue_number,
                        "label": label,
                    },
                )
                return
            raise

    async def create_pr(
        self,
        owner: str,
        repo: str,
        request: PRCreateRequest,
    ) -> PRCreateResult:
        """Create a pull request.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            request: Pull request creation request with title, body, branches.

        Returns:
            PRCreateResult with the created PR number and URL.

        Raises:
            GitHubAPIError: If the request fails.
        """
        path = f"/repos/{owner}/{repo}/pulls"

        logger.info(
            "Creating pull request",
            extra={
                "owner": owner,
                "repo": repo,
                "title": request.title,
                "head": request.head_branch,
                "base": request.base_branch,
            },
        )

        response = await self._request(
            method="POST",
            path=path,
            json_data={
                "title": request.title,
                "body": request.body,
                "head": request.head_branch,
                "base": request.base_branch,
            },
        )

        result = PRCreateResult.from_github_response(response.json())

        logger.info(
            "Pull request created successfully",
            extra={
                "owner": owner,
                "repo": repo,
                "pr_number": result.pr_number,
                "pr_url": result.pr_url,
            },
        )

        # Add labels if specified
        if request.labels:
            await self._add_pr_labels(owner, repo, result.pr_number, request.labels)

        # Request reviewers if specified
        if request.reviewers:
            await self.request_reviewers(
                owner,
                repo,
                result.pr_number,
                request.reviewers,
            )

        return result

    async def _add_pr_labels(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        labels: List[str],
    ) -> None:
        """Add labels to a pull request.

        PRs use the issues API for labels since PRs are a type of issue.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.
            labels: List of label names to add.
        """
        path = f"/repos/{owner}/{repo}/issues/{pr_number}/labels"

        logger.info(
            "Adding labels to pull request",
            extra={
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "labels": labels,
            },
        )

        await self._request(
            method="POST",
            path=path,
            json_data={"labels": labels},
        )

        logger.info(
            "Labels added to pull request",
            extra={
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "labels": labels,
            },
        )

    async def request_reviewers(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        reviewers: List[str],
    ) -> Dict[str, Any]:
        """Request reviewers for a pull request.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            pr_number: Pull request number.
            reviewers: List of GitHub usernames to request as reviewers.

        Returns:
            The updated PR data from GitHub API.

        Raises:
            GitHubAPIError: If the request fails.
        """
        path = f"/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers"

        logger.info(
            "Requesting reviewers for pull request",
            extra={
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "reviewers": reviewers,
            },
        )

        response = await self._request(
            method="POST",
            path=path,
            json_data={"reviewers": reviewers},
        )

        result = response.json()
        logger.info(
            "Reviewers requested successfully",
            extra={
                "owner": owner,
                "repo": repo,
                "pr_number": pr_number,
                "reviewers": reviewers,
            },
        )

        return result

    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> Dict[str, Any]:
        """Get issue details.

        Args:
            owner: Repository owner (user or organization).
            repo: Repository name.
            issue_number: Issue number to retrieve.

        Returns:
            Issue data from GitHub API.

        Raises:
            GitHubAPIError: If the request fails.
        """
        path = f"/repos/{owner}/{repo}/issues/{issue_number}"

        logger.debug(
            "Getting issue details",
            extra={
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
            },
        )

        response = await self._request(method="GET", path=path)
        return response.json()

    async def health_check(self) -> bool:
        """Check if the GitHub API is accessible.

        This method makes a simple authenticated request to verify
        the token is valid and the API is reachable.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            response = await self.client.get("/user")
            return response.status_code == 200
        except Exception as e:
            logger.warning(
                "GitHub API health check failed",
                extra={"error": str(e)},
            )
            return False
