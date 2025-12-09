"""Basic unit tests for GitHubClient functionality."""

import os
import sys
from unittest.mock import Mock, patch
import pytest

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda'))

from shared.github_client import (
    GitHubClient,
    GitHubClientError,
    RepositoryNotFoundError,
    RepositoryAccessDeniedError,
    GitHubAPIError,
    FileMetadata
)


def test_parse_repo_url_valid():
    """Test parsing valid GitHub URLs."""
    client = GitHubClient()
    
    org, repo = client.parse_repo_url("https://github.com/octocat/Hello-World")
    assert org == "octocat"
    assert repo == "Hello-World"
    
    # With trailing slash
    org, repo = client.parse_repo_url("https://github.com/octocat/Hello-World/")
    assert org == "octocat"
    assert repo == "Hello-World"


def test_parse_repo_url_invalid():
    """Test parsing invalid GitHub URLs."""
    client = GitHubClient()
    
    with pytest.raises(GitHubClientError):
        client.parse_repo_url("https://gitlab.com/org/repo")
    
    with pytest.raises(GitHubClientError):
        client.parse_repo_url("not-a-url")
    
    with pytest.raises(GitHubClientError):
        client.parse_repo_url("https://github.com/org")


def test_validate_repository_access_success():
    """Test successful repository access validation."""
    client = GitHubClient()
    
    with patch.object(client._github, 'get_repo') as mock_get_repo:
        mock_repo = Mock()
        mock_repo.full_name = "octocat/Hello-World"
        mock_get_repo.return_value = mock_repo
        
        result = client.validate_repository_access("https://github.com/octocat/Hello-World")
        assert result is True


def test_validate_repository_access_not_found():
    """Test repository not found."""
    client = GitHubClient()
    
    from github import GithubException
    
    with patch.object(client._github, 'get_repo') as mock_get_repo:
        mock_get_repo.side_effect = GithubException(
            status=404,
            data={'message': 'Not Found'},
            headers={}
        )
        
        result = client.validate_repository_access("https://github.com/octocat/NonExistent")
        assert result is False


def test_get_directory_contents():
    """Test getting directory contents."""
    client = GitHubClient()
    
    with patch.object(client._github, 'get_repo') as mock_get_repo:
        mock_repo = Mock()
        
        # Mock file contents
        mock_file1 = Mock()
        mock_file1.type = "file"
        mock_file1.path = ".kiro/doc1.md"
        mock_file1.sha = "abc123"
        mock_file1.size = 1024
        mock_file1.html_url = "https://github.com/org/repo/blob/main/.kiro/doc1.md"
        
        mock_file2 = Mock()
        mock_file2.type = "file"
        mock_file2.path = ".kiro/doc2.md"
        mock_file2.sha = "def456"
        mock_file2.size = 2048
        mock_file2.html_url = "https://github.com/org/repo/blob/main/.kiro/doc2.md"
        
        mock_repo.get_contents.return_value = [mock_file1, mock_file2]
        mock_get_repo.return_value = mock_repo
        
        files = client.get_directory_contents("https://github.com/org/repo", ".kiro/")
        
        assert len(files) == 2
        assert files[0].path == ".kiro/doc1.md"
        assert files[0].sha == "abc123"
        assert files[1].path == ".kiro/doc2.md"
        assert files[1].sha == "def456"


def test_get_file_content():
    """Test getting file content."""
    client = GitHubClient()
    
    with patch.object(client._github, 'get_repo') as mock_get_repo:
        mock_repo = Mock()
        
        mock_content = Mock()
        mock_content.decoded_content = b"# Hello World\n\nThis is a test document."
        
        mock_repo.get_contents.return_value = mock_content
        mock_get_repo.return_value = mock_repo
        
        content = client.get_file_content("https://github.com/org/repo", ".kiro/doc.md")
        
        assert content == "# Hello World\n\nThis is a test document."


def test_get_file_sha():
    """Test getting file SHA."""
    client = GitHubClient()
    
    with patch.object(client._github, 'get_repo') as mock_get_repo:
        mock_repo = Mock()
        
        mock_content = Mock()
        mock_content.sha = "abc123def456"
        
        mock_repo.get_contents.return_value = mock_content
        mock_get_repo.return_value = mock_repo
        
        sha = client.get_file_sha("https://github.com/org/repo", ".kiro/doc.md")
        
        assert sha == "abc123def456"


def test_get_rate_limit():
    """Test getting rate limit information."""
    client = GitHubClient()
    
    from datetime import datetime, timedelta
    
    mock_rate_limit = Mock()
    mock_core = Mock()
    mock_core.limit = 5000
    mock_core.remaining = 4999
    mock_core.reset = datetime.now() + timedelta(hours=1)
    
    mock_search = Mock()
    mock_search.limit = 30
    mock_search.remaining = 29
    mock_search.reset = datetime.now() + timedelta(minutes=30)
    
    mock_rate_limit.core = mock_core
    mock_rate_limit.search = mock_search
    
    with patch.object(client._github, 'get_rate_limit', return_value=mock_rate_limit):
        rate_info = client.get_rate_limit()
        
        assert rate_info['core']['limit'] == 5000
        assert rate_info['core']['remaining'] == 4999
        assert rate_info['search']['limit'] == 30
        assert rate_info['search']['remaining'] == 29
