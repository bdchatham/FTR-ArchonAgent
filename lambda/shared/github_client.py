"""GitHub client for accessing repository contents using PyGithub."""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from github import Github, GithubException, RateLimitExceededException
from github.Repository import Repository
from github.ContentFile import ContentFile
import time


@dataclass
class FileMetadata:
    """Metadata for a file in a GitHub repository."""
    path: str
    sha: str
    size: int
    url: str


class GitHubClientError(Exception):
    """Base exception for GitHub client errors."""
    pass


class RepositoryNotFoundError(GitHubClientError):
    """Raised when repository is not found (404)."""
    pass


class RepositoryAccessDeniedError(GitHubClientError):
    """Raised when repository access is denied (403)."""
    pass


class GitHubAPIError(GitHubClientError):
    """Raised for other GitHub API errors."""
    pass


class GitHubClient:
    """
    Client for interacting with GitHub API using PyGithub.
    
    PyGithub handles rate limiting automatically, so this client focuses on
    providing a clean interface for repository operations with proper error handling.
    """
    
    URL_PATTERN = re.compile(
        r'^https://github\.com/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_.-]+)/?$'
    )
    
    def __init__(self, access_token: Optional[str] = None):
        """
        Initialize GitHub client.
        
        Args:
            access_token: Optional GitHub personal access token for authentication.
                         If None, uses unauthenticated access (lower rate limits).
        """
        self._github = Github(access_token) if access_token else Github()
    
    def parse_repo_url(self, repo_url: str) -> Tuple[str, str]:
        """
        Parse GitHub repository URL to extract org/user and repo name.
        
        Args:
            repo_url: GitHub repository URL (e.g., "https://github.com/org/repo")
            
        Returns:
            Tuple of (org, repo)
            
        Raises:
            GitHubClientError: If URL format is invalid
        """
        # Normalize URL by removing trailing slash
        url_normalized = repo_url.rstrip('/')
        
        match = self.URL_PATTERN.match(url_normalized)
        if not match:
            raise GitHubClientError(f"Invalid GitHub URL format: {repo_url}")
        
        org, repo = match.groups()
        return org, repo
    
    def _get_repository(self, repo_url: str) -> Repository:
        """
        Get PyGithub Repository object.
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            PyGithub Repository object
            
        Raises:
            RepositoryNotFoundError: If repository doesn't exist
            RepositoryAccessDeniedError: If access is denied
            GitHubAPIError: For other API errors
        """
        org, repo = self.parse_repo_url(repo_url)
        full_name = f"{org}/{repo}"
        
        try:
            return self._github.get_repo(full_name)
        except GithubException as e:
            if e.status == 404:
                raise RepositoryNotFoundError(
                    f"Repository not found: {full_name}"
                ) from e
            elif e.status == 403:
                # 403 can be access denied or rate limit
                error_message = e.data.get('message', '') if e.data else ''
                if 'rate limit' in error_message.lower():
                    raise GitHubAPIError(
                        f"Rate limit exceeded for {full_name}"
                    ) from e
                else:
                    raise RepositoryAccessDeniedError(
                        f"Access denied to repository: {full_name}"
                    ) from e
            else:
                raise GitHubAPIError(
                    f"GitHub API error for {full_name}: {e.data.get('message', str(e)) if e.data else str(e)}"
                ) from e
    
    def validate_repository_access(self, repo_url: str) -> bool:
        """
        Validate that repository exists and is accessible.
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            True if repository is accessible, False otherwise
        """
        try:
            self._get_repository(repo_url)
            return True
        except (RepositoryNotFoundError, RepositoryAccessDeniedError, GitHubAPIError):
            return False
    
    def get_directory_contents(
        self, 
        repo_url: str, 
        path: str, 
        branch: str = "main"
    ) -> List[FileMetadata]:
        """
        Get contents of a directory in a repository.
        
        Args:
            repo_url: GitHub repository URL
            path: Path to directory (e.g., ".kiro/")
            branch: Branch name (default: "main")
            
        Returns:
            List of FileMetadata objects for files in the directory
            
        Raises:
            RepositoryNotFoundError: If repository doesn't exist
            RepositoryAccessDeniedError: If access is denied
            GitHubAPIError: For other API errors
        """
        repo = self._get_repository(repo_url)
        
        try:
            contents = repo.get_contents(path, ref=branch)
            
            # Handle both single file and list of files
            if not isinstance(contents, list):
                contents = [contents]
            
            # Filter for files only (exclude directories)
            file_list = []
            for item in contents:
                if item.type == "file":
                    file_list.append(FileMetadata(
                        path=item.path,
                        sha=item.sha,
                        size=item.size,
                        url=item.html_url
                    ))
                elif item.type == "dir":
                    # Recursively get files from subdirectories
                    subdir_files = self.get_directory_contents(repo_url, item.path, branch)
                    file_list.extend(subdir_files)
            
            return file_list
            
        except GithubException as e:
            if e.status == 404:
                # Directory doesn't exist - return empty list
                return []
            elif e.status == 403:
                raise RepositoryAccessDeniedError(
                    f"Access denied to path {path} in repository"
                ) from e
            else:
                raise GitHubAPIError(
                    f"GitHub API error accessing {path}: {e.data.get('message', str(e))}"
                ) from e
    
    def get_file_content(
        self, 
        repo_url: str, 
        file_path: str, 
        branch: str = "main"
    ) -> str:
        """
        Get content of a specific file.
        
        Args:
            repo_url: GitHub repository URL
            file_path: Path to file in repository
            branch: Branch name (default: "main")
            
        Returns:
            File content as string
            
        Raises:
            RepositoryNotFoundError: If repository doesn't exist
            RepositoryAccessDeniedError: If access is denied
            GitHubAPIError: For other API errors
        """
        repo = self._get_repository(repo_url)
        
        try:
            content_file = repo.get_contents(file_path, ref=branch)
            
            # Handle case where path points to a directory
            if isinstance(content_file, list):
                raise GitHubAPIError(f"Path {file_path} is a directory, not a file")
            
            # Decode content from base64
            return content_file.decoded_content.decode('utf-8')
            
        except GithubException as e:
            if e.status == 404:
                raise RepositoryNotFoundError(
                    f"File not found: {file_path}"
                ) from e
            elif e.status == 403:
                raise RepositoryAccessDeniedError(
                    f"Access denied to file {file_path}"
                ) from e
            else:
                raise GitHubAPIError(
                    f"GitHub API error accessing {file_path}: {e.data.get('message', str(e))}"
                ) from e
        except UnicodeDecodeError as e:
            raise GitHubAPIError(
                f"Failed to decode file content as UTF-8: {file_path}"
            ) from e
    
    def get_file_sha(
        self, 
        repo_url: str, 
        file_path: str, 
        branch: str = "main"
    ) -> str:
        """
        Get SHA hash of a specific file.
        
        Args:
            repo_url: GitHub repository URL
            file_path: Path to file in repository
            branch: Branch name (default: "main")
            
        Returns:
            SHA hash of the file
            
        Raises:
            RepositoryNotFoundError: If repository or file doesn't exist
            RepositoryAccessDeniedError: If access is denied
            GitHubAPIError: For other API errors
        """
        repo = self._get_repository(repo_url)
        
        try:
            content_file = repo.get_contents(file_path, ref=branch)
            
            # Handle case where path points to a directory
            if isinstance(content_file, list):
                raise GitHubAPIError(f"Path {file_path} is a directory, not a file")
            
            return content_file.sha
            
        except GithubException as e:
            if e.status == 404:
                raise RepositoryNotFoundError(
                    f"File not found: {file_path}"
                ) from e
            elif e.status == 403:
                raise RepositoryAccessDeniedError(
                    f"Access denied to file {file_path}"
                ) from e
            else:
                raise GitHubAPIError(
                    f"GitHub API error accessing {file_path}: {e.data.get('message', str(e))}"
                ) from e
    
    def get_rate_limit(self) -> dict:
        """
        Get current rate limit status.
        
        Returns:
            Dictionary with rate limit information
        """
        rate_limit = self._github.get_rate_limit()
        return {
            'core': {
                'limit': rate_limit.core.limit,
                'remaining': rate_limit.core.remaining,
                'reset': rate_limit.core.reset
            },
            'search': {
                'limit': rate_limit.search.limit,
                'remaining': rate_limit.search.remaining,
                'reset': rate_limit.search.reset
            }
        }
