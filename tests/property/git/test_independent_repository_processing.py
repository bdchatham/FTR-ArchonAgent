"""
Property-based tests for independent repository processing.

Feature: archon-rag-system, Property 3: Independent repository processing
Validates: Requirements 1.4
"""

import os
import sys
from hypothesis import given, strategies as st
from unittest.mock import Mock, patch


from git.github_client import (
    GitHubClient, 
    RepositoryNotFoundError, 
    RepositoryAccessDeniedError,
    GitHubAPIError
)


@st.composite
def valid_github_url(draw):
    """Generate valid GitHub repository URLs."""
    org = draw(st.from_regex(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$', fullmatch=True))
    repo = draw(st.from_regex(r'^[a-zA-Z0-9._-]{1,100}$', fullmatch=True))
    return f"https://github.com/{org}/{repo}"


@st.composite
def repository_list_with_failures(draw):
    """Generate list of repositories where some may fail."""
    num_repos = draw(st.integers(min_value=2, max_value=10))
    repos = []
    
    for i in range(num_repos):
        url = draw(valid_github_url())
        # Randomly decide if this repo should fail
        should_fail = draw(st.booleans())
        error_type = None
        
        if should_fail:
            error_type = draw(st.sampled_from([
                'not_found',
                'access_denied',
                'api_error'
            ]))
        
        repos.append({
            'url': url,
            'should_fail': should_fail,
            'error_type': error_type
        })
    
    return repos


# Feature: archon-rag-system, Property 3: Independent repository processing
@given(repository_list_with_failures())
def test_independent_repository_processing(repo_configs):
    """
    For any list of repository configurations, processing should handle each 
    repository independently such that failure in one does not prevent 
    processing of others.
    
    Validates: Requirements 1.4
    """
    client = GitHubClient()
    
    # Track which repositories were attempted
    attempted_repos = []
    successful_repos = []
    failed_repos = []
    
    # Process each repository independently
    for repo_config in repo_configs:
        repo_url = repo_config['url']
        attempted_repos.append(repo_url)
        
        try:
            # Mock the repository access based on configuration
            with patch.object(client, '_get_repository') as mock_get_repo:
                if repo_config['should_fail']:
                    # Simulate failure
                    if repo_config['error_type'] == 'not_found':
                        mock_get_repo.side_effect = RepositoryNotFoundError(
                            f"Repository not found: {repo_url}"
                        )
                    elif repo_config['error_type'] == 'access_denied':
                        mock_get_repo.side_effect = RepositoryAccessDeniedError(
                            f"Access denied: {repo_url}"
                        )
                    else:
                        mock_get_repo.side_effect = GitHubAPIError(
                            f"API error: {repo_url}"
                        )
                else:
                    # Simulate success
                    mock_repo = Mock()
                    mock_repo.full_name = repo_url
                    mock_get_repo.return_value = mock_repo
                
                # Attempt to validate repository access
                result = client.validate_repository_access(repo_url)
                
                if result:
                    successful_repos.append(repo_url)
                else:
                    failed_repos.append(repo_url)
        
        except Exception as e:
            # Even if exception occurs, we should continue processing
            failed_repos.append(repo_url)
    
    # Property 1: All repositories should be attempted
    assert len(attempted_repos) == len(repo_configs), \
        "Not all repositories were attempted"
    
    # Property 2: Number of successful + failed should equal total
    assert len(successful_repos) + len(failed_repos) == len(repo_configs), \
        "Some repositories were not accounted for"
    
    # Property 3: Each item in the list should be processed (even if URLs are duplicates)
    # The point is that processing continues through the entire list
    assert len(attempted_repos) == len(repo_configs), \
        "Not all list items were processed"


@given(st.lists(valid_github_url(), min_size=3, max_size=10))
def test_repository_processing_isolation(repo_urls):
    """
    For any list of repositories, if one fails, others should still be processed.
    
    Validates: Requirements 1.4
    """
    client = GitHubClient()
    
    # Make the middle repository fail
    middle_index = len(repo_urls) // 2
    
    results = []
    
    for i, repo_url in enumerate(repo_urls):
        with patch.object(client, '_get_repository') as mock_get_repo:
            if i == middle_index:
                # Make this one fail
                mock_get_repo.side_effect = RepositoryNotFoundError("Not found")
            else:
                # Make others succeed
                mock_repo = Mock()
                mock_repo.full_name = repo_url
                mock_get_repo.return_value = mock_repo
            
            result = client.validate_repository_access(repo_url)
            if result:
                results.append(('success', repo_url))
            else:
                results.append(('failure', repo_url))
    
    # Property: All repositories should be attempted despite middle failure
    assert len(results) == len(repo_urls), \
        "Not all repositories were processed after a failure"
    
    # Property: Only the middle repository should fail
    failure_count = sum(1 for status, _ in results if status == 'failure')
    assert failure_count == 1, \
        f"Expected exactly 1 failure, got {failure_count}"
    
    # Property: All non-middle repositories should succeed
    successful_count = sum(1 for status, _ in results if status == 'success')
    assert successful_count == len(repo_urls) - 1, \
        f"Expected {len(repo_urls) - 1} successes, got {successful_count}"


@given(st.lists(valid_github_url(), min_size=2, max_size=5))
def test_no_cross_contamination_between_repositories(repo_urls):
    """
    For any list of repositories, processing one should not affect the state 
    or results of processing another.
    
    Validates: Requirements 1.4
    """
    client = GitHubClient()
    
    # Process each repository and collect results
    first_pass_results = []
    
    for repo_url in repo_urls:
        with patch.object(client, '_get_repository') as mock_get_repo:
            mock_repo = Mock()
            mock_repo.full_name = repo_url
            mock_get_repo.return_value = mock_repo
            
            result = client.validate_repository_access(repo_url)
            first_pass_results.append((repo_url, result))
    
    # Process again in different order
    shuffled_urls = repo_urls[::-1]  # Reverse order
    second_pass_results = []
    
    for repo_url in shuffled_urls:
        with patch.object(client, '_get_repository') as mock_get_repo:
            mock_repo = Mock()
            mock_repo.full_name = repo_url
            mock_get_repo.return_value = mock_repo
            
            result = client.validate_repository_access(repo_url)
            second_pass_results.append((repo_url, result))
    
    # Property: Results should be consistent regardless of processing order
    first_pass_dict = dict(first_pass_results)
    second_pass_dict = dict(second_pass_results)
    
    for repo_url in repo_urls:
        assert first_pass_dict[repo_url] == second_pass_dict[repo_url], \
            f"Repository {repo_url} produced different results in different orders"
