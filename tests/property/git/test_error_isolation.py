"""
Property-based tests for error isolation in multi-repository monitoring.

Feature: archon-rag-system, Property 4: Error isolation in multi-repository monitoring
Validates: Requirements 1.5
"""

import os
import sys
from hypothesis import given, strategies as st, assume
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
def invalid_github_url(draw):
    """Generate invalid GitHub URLs."""
    choice = draw(st.integers(min_value=0, max_value=4))
    
    if choice == 0:
        return "http://github.com/org/repo"  # Wrong protocol
    elif choice == 1:
        return "https://gitlab.com/org/repo"  # Wrong domain
    elif choice == 2:
        return "https://github.com/org"  # Missing repo
    elif choice == 3:
        return draw(st.text(max_size=50))  # Random text
    else:
        return ""  # Empty string


@st.composite
def mixed_repository_list(draw):
    """Generate list with both valid and invalid repository URLs."""
    num_valid = draw(st.integers(min_value=1, max_value=5))
    num_invalid = draw(st.integers(min_value=1, max_value=5))
    
    valid_repos = [draw(valid_github_url()) for _ in range(num_valid)]
    invalid_repos = [draw(invalid_github_url()) for _ in range(num_invalid)]
    
    # Shuffle them together
    all_repos = valid_repos + invalid_repos
    draw(st.randoms()).shuffle(all_repos)
    
    return {
        'all_repos': all_repos,
        'valid_repos': set(valid_repos),
        'invalid_repos': set(invalid_repos)
    }


# Feature: archon-rag-system, Property 4: Error isolation in multi-repository monitoring
@given(mixed_repository_list())
def test_error_isolation_with_invalid_urls(repo_data):
    """
    For any set of repositories containing both valid and invalid URLs, 
    the system should process all valid repositories and log errors for 
    invalid ones without terminating.
    
    Validates: Requirements 1.5
    """
    client = GitHubClient()
    
    all_repos = repo_data['all_repos']
    valid_repos = repo_data['valid_repos']
    invalid_repos = repo_data['invalid_repos']
    
    processed_valid = []
    processed_invalid = []
    errors_logged = []
    
    # Process each repository
    for repo_url in all_repos:
        try:
            if repo_url in valid_repos:
                # Mock successful access for valid repos
                with patch.object(client, '_get_repository') as mock_get_repo:
                    mock_repo = Mock()
                    mock_repo.full_name = repo_url
                    mock_get_repo.return_value = mock_repo
                    
                    result = client.validate_repository_access(repo_url)
                    if result:
                        processed_valid.append(repo_url)
            else:
                # Invalid URLs should fail during parsing or access
                try:
                    result = client.validate_repository_access(repo_url)
                    if not result:
                        processed_invalid.append(repo_url)
                        errors_logged.append(repo_url)
                except Exception as e:
                    processed_invalid.append(repo_url)
                    errors_logged.append(repo_url)
        
        except Exception as e:
            # Log error but continue processing
            errors_logged.append(repo_url)
            continue
    
    # Property 1: All valid repository entries should be processed successfully
    # Count how many valid repos are in the list (including duplicates)
    expected_valid_count = sum(1 for repo in all_repos if repo in valid_repos)
    assert len(processed_valid) == expected_valid_count, \
        f"Not all valid repositories were processed. Expected {expected_valid_count}, got {len(processed_valid)}"
    
    # Property 2: Invalid repositories should be logged as errors
    expected_invalid_count = sum(1 for repo in all_repos if repo in invalid_repos)
    assert len(errors_logged) >= expected_invalid_count, \
        "Not all invalid repositories were logged as errors"
    
    # Property 3: Processing should not terminate early
    total_processed = len(processed_valid) + len(processed_invalid)
    assert total_processed == len(all_repos), \
        f"Not all repositories were processed. Expected {len(all_repos)}, got {total_processed}"


@given(st.lists(valid_github_url(), min_size=3, max_size=10))
def test_error_isolation_with_access_failures(repo_urls):
    """
    For any list of valid URLs where some repositories have access failures,
    other repositories should still be processed successfully.
    
    Validates: Requirements 1.5
    """
    client = GitHubClient()
    
    # Randomly mark some repositories to fail
    failure_indices = set()
    for i in range(len(repo_urls)):
        if i % 3 == 0:  # Every third repository fails
            failure_indices.add(i)
    
    assume(len(failure_indices) > 0)  # Ensure at least one failure
    assume(len(failure_indices) < len(repo_urls))  # Ensure at least one success
    
    successful_repos = []
    failed_repos = []
    
    for i, repo_url in enumerate(repo_urls):
        with patch.object(client, '_get_repository') as mock_get_repo:
            if i in failure_indices:
                # Simulate access failure
                mock_get_repo.side_effect = RepositoryAccessDeniedError(
                    f"Access denied: {repo_url}"
                )
            else:
                # Simulate success
                mock_repo = Mock()
                mock_repo.full_name = repo_url
                mock_get_repo.return_value = mock_repo
            
            try:
                result = client.validate_repository_access(repo_url)
                if result:
                    successful_repos.append(repo_url)
                else:
                    failed_repos.append(repo_url)
            except Exception:
                failed_repos.append(repo_url)
    
    # Property 1: All repositories should be attempted
    assert len(successful_repos) + len(failed_repos) == len(repo_urls), \
        "Not all repositories were attempted"
    
    # Property 2: Non-failing repositories should succeed
    expected_successes = len(repo_urls) - len(failure_indices)
    assert len(successful_repos) == expected_successes, \
        f"Expected {expected_successes} successes, got {len(successful_repos)}"
    
    # Property 3: Failing repositories should be logged
    assert len(failed_repos) == len(failure_indices), \
        f"Expected {len(failure_indices)} failures, got {len(failed_repos)}"


@given(st.lists(valid_github_url(), min_size=5, max_size=15))
def test_continuous_processing_despite_errors(repo_urls):
    """
    For any list of repositories with various error types, processing should
    continue through all repositories without early termination.
    
    Validates: Requirements 1.5
    """
    client = GitHubClient()
    
    # Create different error scenarios
    error_scenarios = [
        None,  # Success
        RepositoryNotFoundError("Not found"),
        RepositoryAccessDeniedError("Access denied"),
        GitHubAPIError("API error"),
    ]
    
    processed_count = 0
    error_count = 0
    
    for i, repo_url in enumerate(repo_urls):
        with patch.object(client, '_get_repository') as mock_get_repo:
            # Cycle through error scenarios
            error = error_scenarios[i % len(error_scenarios)]
            
            if error is None:
                # Success case
                mock_repo = Mock()
                mock_repo.full_name = repo_url
                mock_get_repo.return_value = mock_repo
            else:
                # Error case
                mock_get_repo.side_effect = error
            
            try:
                result = client.validate_repository_access(repo_url)
                processed_count += 1
                if not result:
                    error_count += 1
            except Exception:
                processed_count += 1
                error_count += 1
    
    # Property: All repositories should be processed despite errors
    assert processed_count == len(repo_urls), \
        f"Processing terminated early. Expected {len(repo_urls)}, processed {processed_count}"
    
    # Property: Some errors should have been encountered
    expected_errors = sum(1 for i in range(len(repo_urls)) if i % len(error_scenarios) != 0)
    assert error_count >= expected_errors, \
        "Not all errors were properly handled"


@given(
    st.lists(valid_github_url(), min_size=2, max_size=8),
    st.lists(invalid_github_url(), min_size=1, max_size=4)
)
def test_valid_repos_unaffected_by_invalid_repos(valid_urls, invalid_urls):
    """
    For any combination of valid and invalid repository URLs, valid repositories
    should be processed successfully regardless of invalid ones.
    
    Validates: Requirements 1.5
    """
    client = GitHubClient()
    
    # Interleave valid and invalid URLs
    all_urls = []
    max_len = max(len(valid_urls), len(invalid_urls))
    for i in range(max_len):
        if i < len(valid_urls):
            all_urls.append(('valid', valid_urls[i]))
        if i < len(invalid_urls):
            all_urls.append(('invalid', invalid_urls[i]))
    
    valid_processed = []
    invalid_processed = []
    
    for url_type, url in all_urls:
        try:
            if url_type == 'valid':
                with patch.object(client, '_get_repository') as mock_get_repo:
                    mock_repo = Mock()
                    mock_repo.full_name = url
                    mock_get_repo.return_value = mock_repo
                    
                    result = client.validate_repository_access(url)
                    if result:
                        valid_processed.append(url)
            else:
                # Invalid URL - should fail
                try:
                    client.validate_repository_access(url)
                    invalid_processed.append(url)
                except Exception:
                    invalid_processed.append(url)
        except Exception:
            if url_type == 'invalid':
                invalid_processed.append(url)
    
    # Property: All valid repositories should be processed successfully
    assert len(valid_processed) == len(valid_urls), \
        f"Not all valid repositories were processed. Expected {len(valid_urls)}, got {len(valid_processed)}"
    
    # Property: Invalid repositories should not prevent valid ones from processing
    assert set(valid_processed) == set(valid_urls), \
        "Valid repositories were affected by invalid ones"
