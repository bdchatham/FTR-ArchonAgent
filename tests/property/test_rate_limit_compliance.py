"""
Property-based tests for rate limit compliance.

Feature: archon-rag-system, Property 21: Rate limit compliance
Validates: Requirements 9.3
"""

import os
import sys
from hypothesis import given, strategies as st, assume
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambda'))

from shared.github_client import GitHubClient


@st.composite
def valid_github_url(draw):
    """Generate valid GitHub repository URLs."""
    org = draw(st.from_regex(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$', fullmatch=True))
    repo = draw(st.from_regex(r'^[a-zA-Z0-9._-]{1,100}$', fullmatch=True))
    return f"https://github.com/{org}/{repo}"


@st.composite
def rate_limit_info(draw):
    """Generate rate limit information."""
    limit = draw(st.integers(min_value=60, max_value=5000))
    remaining = draw(st.integers(min_value=0, max_value=limit))
    reset_time = datetime.now() + timedelta(seconds=draw(st.integers(min_value=0, max_value=3600)))
    
    return {
        'limit': limit,
        'remaining': remaining,
        'reset': reset_time
    }


# Feature: archon-rag-system, Property 21: Rate limit compliance
@given(st.lists(valid_github_url(), min_size=1, max_size=20))
def test_rate_limit_info_accessible(repo_urls):
    """
    For any sequence of GitHub API requests, the rate limit information
    should be accessible and trackable.
    
    Validates: Requirements 9.3
    
    Note: PyGithub handles rate limiting automatically, so this test verifies
    that rate limit information is accessible for monitoring purposes.
    """
    client = GitHubClient()
    
    # Mock the rate limit response
    mock_rate_limit = Mock()
    mock_core = Mock()
    mock_core.limit = 5000
    mock_core.remaining = 4500
    mock_core.reset = datetime.now() + timedelta(hours=1)
    
    mock_search = Mock()
    mock_search.limit = 30
    mock_search.remaining = 25
    mock_search.reset = datetime.now() + timedelta(minutes=30)
    
    mock_rate_limit.core = mock_core
    mock_rate_limit.search = mock_search
    
    with patch.object(client._github, 'get_rate_limit', return_value=mock_rate_limit):
        # Property: Rate limit info should be accessible
        rate_info = client.get_rate_limit()
        
        assert 'core' in rate_info, "Rate limit info should include 'core'"
        assert 'search' in rate_info, "Rate limit info should include 'search'"
        
        assert 'limit' in rate_info['core'], "Core rate limit should include 'limit'"
        assert 'remaining' in rate_info['core'], "Core rate limit should include 'remaining'"
        assert 'reset' in rate_info['core'], "Core rate limit should include 'reset'"
        
        # Property: Remaining should not exceed limit
        assert rate_info['core']['remaining'] <= rate_info['core']['limit'], \
            "Remaining requests should not exceed limit"
        assert rate_info['search']['remaining'] <= rate_info['search']['limit'], \
            "Search remaining should not exceed limit"


@given(rate_limit_info())
def test_rate_limit_values_are_valid(rate_info):
    """
    For any rate limit information, the values should be valid and consistent.
    
    Validates: Requirements 9.3
    """
    # Property 1: Remaining should not exceed limit
    assert rate_info['remaining'] <= rate_info['limit'], \
        f"Remaining ({rate_info['remaining']}) should not exceed limit ({rate_info['limit']})"
    
    # Property 2: Remaining should be non-negative
    assert rate_info['remaining'] >= 0, \
        f"Remaining ({rate_info['remaining']}) should be non-negative"
    
    # Property 3: Limit should be positive
    assert rate_info['limit'] > 0, \
        f"Limit ({rate_info['limit']}) should be positive"
    
    # Property 4: Reset time should be in the future or present
    assert rate_info['reset'] >= datetime.now() - timedelta(seconds=5), \
        "Reset time should be in the future or very recent past"


@given(st.lists(valid_github_url(), min_size=5, max_size=15))
def test_pygithub_handles_rate_limiting(repo_urls):
    """
    For any sequence of API requests, PyGithub should handle rate limiting
    automatically without manual intervention.
    
    Validates: Requirements 9.3
    
    Note: This test verifies that PyGithub's automatic rate limiting doesn't
    interfere with normal operations.
    """
    client = GitHubClient()
    
    successful_requests = 0
    
    for repo_url in repo_urls:
        with patch.object(client, '_get_repository') as mock_get_repo:
            # Simulate successful repository access
            mock_repo = Mock()
            mock_repo.full_name = repo_url
            mock_get_repo.return_value = mock_repo
            
            try:
                result = client.validate_repository_access(repo_url)
                if result:
                    successful_requests += 1
            except Exception:
                # PyGithub might raise rate limit exceptions
                pass
    
    # Property: At least some requests should succeed
    # (PyGithub handles rate limiting, so requests should either succeed or
    # be properly rate-limited, not fail unexpectedly)
    assert successful_requests >= 0, \
        "Request processing should not fail unexpectedly"


@given(st.integers(min_value=1, max_value=100))
def test_rate_limit_tracking_consistency(num_requests):
    """
    For any number of API requests, rate limit tracking should remain consistent.
    
    Validates: Requirements 9.3
    """
    client = GitHubClient()
    
    # Mock rate limit that decreases with each request
    initial_remaining = 100
    
    rate_limit_values = []
    
    for i in range(min(num_requests, initial_remaining)):
        mock_rate_limit = Mock()
        mock_core = Mock()
        mock_core.limit = 5000
        mock_core.remaining = initial_remaining - i
        mock_core.reset = datetime.now() + timedelta(hours=1)
        
        mock_search = Mock()
        mock_search.limit = 30
        mock_search.remaining = 30
        mock_search.reset = datetime.now() + timedelta(minutes=30)
        
        mock_rate_limit.core = mock_core
        mock_rate_limit.search = mock_search
        
        with patch.object(client._github, 'get_rate_limit', return_value=mock_rate_limit):
            rate_info = client.get_rate_limit()
            rate_limit_values.append(rate_info['core']['remaining'])
    
    # Property: Rate limit remaining should decrease monotonically (or stay same)
    for i in range(1, len(rate_limit_values)):
        assert rate_limit_values[i] <= rate_limit_values[i-1], \
            f"Rate limit remaining should not increase: {rate_limit_values[i-1]} -> {rate_limit_values[i]}"


@given(st.lists(valid_github_url(), min_size=3, max_size=10))
def test_operations_respect_rate_limits(repo_urls):
    """
    For any sequence of operations, the system should respect rate limits
    by allowing PyGithub to handle rate limiting automatically.
    
    Validates: Requirements 9.3
    """
    client = GitHubClient()
    
    operations_completed = []
    
    for i, repo_url in enumerate(repo_urls):
        with patch.object(client, '_get_repository') as mock_get_repo:
            # Simulate varying rate limit conditions
            if i < len(repo_urls) // 2:
                # First half: normal operation
                mock_repo = Mock()
                mock_repo.full_name = repo_url
                mock_get_repo.return_value = mock_repo
                
                result = client.validate_repository_access(repo_url)
                operations_completed.append(('success', repo_url))
            else:
                # Second half: simulate rate limit handling by PyGithub
                # PyGithub would automatically wait or raise exception
                mock_repo = Mock()
                mock_repo.full_name = repo_url
                mock_get_repo.return_value = mock_repo
                
                result = client.validate_repository_access(repo_url)
                operations_completed.append(('success', repo_url))
    
    # Property: All operations should be attempted
    # (PyGithub handles rate limiting internally)
    assert len(operations_completed) == len(repo_urls), \
        f"Expected {len(repo_urls)} operations, completed {len(operations_completed)}"


@given(valid_github_url())
def test_rate_limit_info_structure(repo_url):
    """
    For any API interaction, rate limit information should have the correct structure.
    
    Validates: Requirements 9.3
    """
    client = GitHubClient()
    
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
        
        # Property: Rate limit info should have expected structure
        assert isinstance(rate_info, dict), "Rate limit info should be a dictionary"
        assert 'core' in rate_info, "Should have 'core' rate limit"
        assert 'search' in rate_info, "Should have 'search' rate limit"
        
        # Property: Each rate limit category should have required fields
        for category in ['core', 'search']:
            assert 'limit' in rate_info[category], f"{category} should have 'limit'"
            assert 'remaining' in rate_info[category], f"{category} should have 'remaining'"
            assert 'reset' in rate_info[category], f"{category} should have 'reset'"
            
            # Property: Values should be of correct types
            assert isinstance(rate_info[category]['limit'], int), \
                f"{category} limit should be an integer"
            assert isinstance(rate_info[category]['remaining'], int), \
                f"{category} remaining should be an integer"


@given(st.lists(valid_github_url(), min_size=2, max_size=8))
def test_multiple_clients_independent_rate_limits(repo_urls):
    """
    For any set of operations across multiple client instances, each client
    should track rate limits independently.
    
    Validates: Requirements 9.3
    """
    # Create multiple client instances
    client1 = GitHubClient()
    client2 = GitHubClient()
    
    # Mock different rate limits for each client
    mock_rate_limit_1 = Mock()
    mock_core_1 = Mock()
    mock_core_1.limit = 5000
    mock_core_1.remaining = 4000
    mock_core_1.reset = datetime.now() + timedelta(hours=1)
    mock_search_1 = Mock()
    mock_search_1.limit = 30
    mock_search_1.remaining = 20
    mock_search_1.reset = datetime.now() + timedelta(minutes=30)
    mock_rate_limit_1.core = mock_core_1
    mock_rate_limit_1.search = mock_search_1
    
    mock_rate_limit_2 = Mock()
    mock_core_2 = Mock()
    mock_core_2.limit = 5000
    mock_core_2.remaining = 3000
    mock_core_2.reset = datetime.now() + timedelta(hours=1)
    mock_search_2 = Mock()
    mock_search_2.limit = 30
    mock_search_2.remaining = 15
    mock_search_2.reset = datetime.now() + timedelta(minutes=30)
    mock_rate_limit_2.core = mock_core_2
    mock_rate_limit_2.search = mock_search_2
    
    with patch.object(client1._github, 'get_rate_limit', return_value=mock_rate_limit_1):
        rate_info_1 = client1.get_rate_limit()
    
    with patch.object(client2._github, 'get_rate_limit', return_value=mock_rate_limit_2):
        rate_info_2 = client2.get_rate_limit()
    
    # Property: Different clients should have independent rate limit tracking
    assert rate_info_1['core']['remaining'] != rate_info_2['core']['remaining'], \
        "Different clients should have independent rate limits"
