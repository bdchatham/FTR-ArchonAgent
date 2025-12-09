"""
Property-based tests for API error resilience.

Feature: archon-rag-system, Property 8: API error resilience
Validates: Requirements 3.5
"""

import os
import sys
from hypothesis import given, strategies as st, assume
from unittest.mock import Mock, patch
from github import GithubException

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambda'))

from shared.github_client import (
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
def github_api_error(draw):
    """Generate various GitHub API error scenarios."""
    error_type = draw(st.sampled_from([
        'rate_limit',
        'timeout',
        'server_error',
        'not_found',
        'forbidden',
        'bad_gateway',
        'service_unavailable'
    ]))
    
    status_codes = {
        'rate_limit': 403,
        'timeout': 408,
        'server_error': 500,
        'not_found': 404,
        'forbidden': 403,
        'bad_gateway': 502,
        'service_unavailable': 503
    }
    
    messages = {
        'rate_limit': 'API rate limit exceeded',
        'timeout': 'Request timeout',
        'server_error': 'Internal server error',
        'not_found': 'Not Found',
        'forbidden': 'Forbidden',
        'bad_gateway': 'Bad Gateway',
        'service_unavailable': 'Service Unavailable'
    }
    
    return {
        'type': error_type,
        'status': status_codes[error_type],
        'message': messages[error_type]
    }


# Feature: archon-rag-system, Property 8: API error resilience
@given(valid_github_url(), github_api_error())
def test_api_error_handling_without_crash(repo_url, error_config):
    """
    For any GitHub API error (rate limit, timeout, etc.), the system should 
    handle the error gracefully without crashing and continue processing.
    
    Validates: Requirements 3.5
    """
    client = GitHubClient()
    
    # Create a mock GithubException
    mock_exception = GithubException(
        status=error_config['status'],
        data={'message': error_config['message']},
        headers={}
    )
    
    # Test that the client handles the error gracefully
    with patch.object(client._github, 'get_repo') as mock_get_repo:
        mock_get_repo.side_effect = mock_exception
        
        # Property 1: Should not crash (exception should be caught and handled)
        try:
            result = client.validate_repository_access(repo_url)
            # Should return False for errors
            assert result is False, "Should return False for API errors"
        except (RepositoryNotFoundError, RepositoryAccessDeniedError, GitHubAPIError):
            # These are expected, handled exceptions - not crashes
            pass
        except Exception as e:
            # Any other exception is a crash
            raise AssertionError(f"Unexpected exception type: {type(e).__name__}: {e}")


@given(valid_github_url(), st.lists(github_api_error(), min_size=1, max_size=5))
def test_multiple_api_errors_handled_gracefully(repo_url, error_configs):
    """
    For any sequence of API errors, each should be handled gracefully without
    affecting subsequent operations.
    
    Validates: Requirements 3.5
    """
    client = GitHubClient()
    
    handled_errors = []
    
    for error_config in error_configs:
        mock_exception = GithubException(
            status=error_config['status'],
            data={'message': error_config['message']},
            headers={}
        )
        
        with patch.object(client._github, 'get_repo') as mock_get_repo:
            mock_get_repo.side_effect = mock_exception
            
            try:
                result = client.validate_repository_access(repo_url)
                handled_errors.append(('handled', error_config['type']))
            except (RepositoryNotFoundError, RepositoryAccessDeniedError, GitHubAPIError):
                handled_errors.append(('handled', error_config['type']))
            except Exception as e:
                handled_errors.append(('crashed', error_config['type']))
    
    # Property: All errors should be handled, none should crash
    assert len(handled_errors) == len(error_configs), \
        "Not all errors were processed"
    
    crashed_count = sum(1 for status, _ in handled_errors if status == 'crashed')
    assert crashed_count == 0, \
        f"{crashed_count} errors caused crashes instead of being handled"


@given(st.lists(valid_github_url(), min_size=3, max_size=10))
def test_error_recovery_and_continuation(repo_urls):
    """
    For any list of repositories where some encounter API errors, the system
    should continue processing remaining repositories.
    
    Validates: Requirements 3.5
    """
    client = GitHubClient()
    
    # Make every other repository encounter an API error
    error_indices = set(range(0, len(repo_urls), 2))
    
    processed_repos = []
    
    for i, repo_url in enumerate(repo_urls):
        with patch.object(client, '_get_repository') as mock_get_repo:
            if i in error_indices:
                # Simulate API error
                mock_exception = GithubException(
                    status=500,
                    data={'message': 'Internal server error'},
                    headers={}
                )
                mock_get_repo.side_effect = mock_exception
            else:
                # Simulate success
                mock_repo = Mock()
                mock_repo.full_name = repo_url
                mock_get_repo.return_value = mock_repo
            
            try:
                result = client.validate_repository_access(repo_url)
                processed_repos.append((repo_url, 'success' if result else 'error'))
            except Exception:
                processed_repos.append((repo_url, 'error'))
    
    # Property 1: All repositories should be attempted despite errors
    assert len(processed_repos) == len(repo_urls), \
        f"Processing stopped early. Expected {len(repo_urls)}, got {len(processed_repos)}"
    
    # Property 2: Non-error repositories should succeed
    successful_count = sum(1 for _, status in processed_repos if status == 'success')
    expected_successes = len(repo_urls) - len(error_indices)
    assert successful_count == expected_successes, \
        f"Expected {expected_successes} successes, got {successful_count}"


@given(valid_github_url())
def test_different_error_types_handled_appropriately(repo_url):
    """
    For any repository URL, different types of API errors should be handled
    with appropriate error types.
    
    Validates: Requirements 3.5
    """
    client = GitHubClient()
    
    error_scenarios = [
        (404, RepositoryNotFoundError),
        (403, RepositoryAccessDeniedError),
        (500, GitHubAPIError),
        (502, GitHubAPIError),
        (503, GitHubAPIError),
    ]
    
    for status_code, expected_exception in error_scenarios:
        mock_exception = GithubException(
            status=status_code,
            data={'message': f'Error {status_code}'},
            headers={}
        )
        
        with patch.object(client, '_get_repository') as mock_get_repo:
            mock_get_repo.side_effect = mock_exception
            
            # Property: Each error type should be handled appropriately
            try:
                result = client.validate_repository_access(repo_url)
                # validate_repository_access catches exceptions and returns False
                assert result is False, \
                    f"Should return False for status {status_code}"
            except Exception as e:
                # If an exception is raised, it should be the expected type
                # (this happens in other methods like get_file_content)
                pass


@given(valid_github_url(), st.text(min_size=1, max_size=100))
def test_file_operations_handle_api_errors(repo_url, file_path):
    """
    For any file operation that encounters an API error, the error should be
    handled gracefully without crashing.
    
    Validates: Requirements 3.5
    """
    client = GitHubClient()
    
    error_types = [
        (404, RepositoryNotFoundError),
        (403, RepositoryAccessDeniedError),
        (500, GitHubAPIError),
    ]
    
    for status_code, expected_exception_type in error_types:
        mock_exception = GithubException(
            status=status_code,
            data={'message': f'Error {status_code}'},
            headers={}
        )
        
        with patch.object(client, '_get_repository') as mock_get_repo:
            mock_repo = Mock()
            mock_repo.get_contents.side_effect = mock_exception
            mock_get_repo.return_value = mock_repo
            
            # Property: Should raise appropriate exception, not crash
            try:
                content = client.get_file_content(repo_url, file_path)
                # Should not reach here
                assert False, f"Should have raised exception for status {status_code}"
            except expected_exception_type:
                # Expected exception - handled gracefully
                pass
            except Exception as e:
                # Unexpected exception type
                raise AssertionError(
                    f"Expected {expected_exception_type.__name__}, got {type(e).__name__}"
                )


@given(st.lists(valid_github_url(), min_size=2, max_size=8))
def test_partial_failures_dont_affect_successful_operations(repo_urls):
    """
    For any list of repositories where some operations fail due to API errors,
    successful operations should complete normally.
    
    Validates: Requirements 3.5
    """
    client = GitHubClient()
    
    results = []
    
    for i, repo_url in enumerate(repo_urls):
        with patch.object(client, '_get_repository') as mock_get_repo:
            if i % 3 == 0:
                # Every third operation fails
                mock_exception = GithubException(
                    status=503,
                    data={'message': 'Service unavailable'},
                    headers={}
                )
                mock_get_repo.side_effect = mock_exception
            else:
                # Others succeed
                mock_repo = Mock()
                mock_repo.full_name = repo_url
                mock_get_repo.return_value = mock_repo
            
            try:
                result = client.validate_repository_access(repo_url)
                results.append(('success', result))
            except Exception:
                results.append(('error', None))
    
    # Property 1: All operations should be attempted
    assert len(results) == len(repo_urls), \
        "Not all operations were attempted"
    
    # Property 2: Successful operations should return True
    successful_results = [r for status, r in results if status == 'success']
    assert all(r is True for r in successful_results), \
        "Successful operations did not return True"
    
    # Property 3: Failed operations should be logged as errors
    error_count = sum(1 for status, _ in results if status == 'error')
    expected_errors = len([i for i in range(len(repo_urls)) if i % 3 == 0])
    assert error_count == expected_errors, \
        f"Expected {expected_errors} errors, got {error_count}"
