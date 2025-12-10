"""
Property-based tests for permission error handling.

Feature: archon-rag-system, Property 20: Permission error handling
Validates: Requirements 9.2
"""

import os
import sys
from hypothesis import given, strategies as st, settings
from unittest.mock import Mock, patch
from datetime import datetime, timezone


from config.config_manager import Config, RepositoryConfig, InfrastructureConfig, ModelConfig
from git.github_client import (
    GitHubClient,
    RepositoryAccessDeniedError,
    RepositoryNotFoundError,
    GitHubAPIError
)
from storage.change_tracker import ChangeTracker
from ingestion.ingestion_pipeline import IngestionPipeline
from monitor.document_monitor import DocumentMonitor


@st.composite
def valid_github_url(draw):
    """Generate valid GitHub repository URLs."""
    org = draw(st.from_regex(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$', fullmatch=True))
    repo = draw(st.from_regex(r'^[a-zA-Z0-9._-]{1,100}$', fullmatch=True))
    return f"https://github.com/{org}/{repo}"


@st.composite
def repository_config_with_errors(draw):
    """Generate repository configs with error scenarios."""
    num_repos = draw(st.integers(min_value=2, max_value=10))
    repos = []
    
    for _ in range(num_repos):
        url = draw(valid_github_url())
        branch = draw(st.sampled_from(['main', 'master']))
        error_type = draw(st.sampled_from([
            None,  # No error
            'access_denied',
            'not_found',
            'api_error'
        ]))
        
        repos.append({
            'config': RepositoryConfig(
                url=url,
                branch=branch,
                paths=['.kiro/']
            ),
            'error_type': error_type
        })
    
    return repos


@st.composite
def config_with_error_repositories(draw):
    """Generate Config with repositories that may have errors."""
    repo_data = draw(repository_config_with_errors())
    
    infra = InfrastructureConfig(
        cron_schedule='rate(1 hour)',
        lambda_memory=1024,
        lambda_timeout=300,
        vector_db_dimensions=1536
    )
    
    models = ModelConfig(
        embedding_model='amazon.titan-embed-text-v1',
        llm_model='anthropic.claude-3-haiku-20240307',
        llm_temperature=0.7,
        max_tokens=2048,
        retrieval_k=5
    )
    
    config = Config(
        version='1.0',
        repositories=[r['config'] for r in repo_data],
        infrastructure=infra,
        models=models
    )
    
    return config, repo_data


# Feature: archon-rag-system, Property 20: Permission error handling
@given(config_with_error_repositories())
@settings(max_examples=100)
def test_permission_error_handling(config_and_data):
    """
    For any repository access failure due to permissions, the system should 
    log the error and skip that repository without crashing.
    
    Validates: Requirements 9.2
    """
    config, repo_data = config_and_data
    
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Track which repositories were attempted
    attempted_repos = []
    successful_repos = []
    
    # Build a dictionary of URL -> error_type (first occurrence wins for duplicates)
    url_error_map = {}
    for repo_info in repo_data:
        url = repo_info['config'].url
        if url not in url_error_map:
            url_error_map[url] = repo_info['error_type']
    
    def mock_validate_access(repo_url):
        attempted_repos.append(repo_url)
        
        error_type = url_error_map.get(repo_url, 'not_found')
        
        if error_type == 'access_denied' or error_type == 'not_found' or error_type == 'api_error':
            return False
        elif error_type is None:
            successful_repos.append(repo_url)
            return True
        else:
            return False
    
    github_client.validate_repository_access = mock_validate_access
    github_client.get_directory_contents = Mock(return_value=[])
    
    # Create monitor
    monitor = DocumentMonitor(
        config=config,
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Execute monitoring - should not crash
    result = monitor.execute()
    
    # Property 1: All repositories should be attempted
    assert len(attempted_repos) == len(config.repositories), \
        f"Expected {len(config.repositories)} attempts, got {len(attempted_repos)}"
    
    # Property 2: Execution should complete without crashing
    assert result is not None, \
        "Monitoring execution returned None (crashed)"
    
    # Property 3: Errors should be logged for inaccessible repositories
    # Count configs whose URL has an error
    expected_errors = sum(1 for r in repo_data if url_error_map.get(r['config'].url) is not None)
    assert len(result.errors) == expected_errors, \
        f"Expected {expected_errors} errors logged, got {len(result.errors)}"
    
    # Property 4: Successful repositories should be processed
    # Count configs whose URL has no error
    expected_successful_count = sum(1 for r in repo_data if url_error_map.get(r['config'].url) is None)
    assert len(successful_repos) == expected_successful_count, \
        f"Expected {expected_successful_count} successful repos, got {len(successful_repos)}"


@given(st.lists(valid_github_url(), min_size=3, max_size=10))
@settings(max_examples=100)
def test_permission_error_does_not_stop_processing(repo_urls):
    """
    For any list of repositories where some have permission errors, processing 
    should continue for all repositories.
    
    Validates: Requirements 9.2
    """
    # Create repository configs
    repo_configs = [
        RepositoryConfig(url=url, branch='main', paths=['.kiro/'])
        for url in repo_urls
    ]
    
    config = Config(
        version='1.0',
        repositories=repo_configs,
        infrastructure=InfrastructureConfig(
            cron_schedule='rate(1 hour)',
            lambda_memory=1024,
            lambda_timeout=300,
            vector_db_dimensions=1536
        ),
        models=ModelConfig(
            embedding_model='amazon.titan-embed-text-v1',
            llm_model='anthropic.claude-3-haiku-20240307',
            llm_temperature=0.7,
            max_tokens=2048,
            retrieval_k=5
        )
    )
    
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Track processing
    attempted_repos = []
    
    # Make middle repository fail with permission error
    middle_index = len(repo_urls) // 2
    
    def mock_validate_access(repo_url):
        attempted_repos.append(repo_url)
        index = repo_urls.index(repo_url)
        return index != middle_index
    
    github_client.validate_repository_access = mock_validate_access
    github_client.get_directory_contents = Mock(return_value=[])
    
    # Create monitor
    monitor = DocumentMonitor(
        config=config,
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Execute monitoring
    result = monitor.execute()
    
    # Property: All repositories should be attempted despite middle failure
    assert len(attempted_repos) == len(repo_urls), \
        f"Expected {len(repo_urls)} attempts, got {len(attempted_repos)}"
    
    # Property: Repositories after the failed one should still be processed
    repos_after_failure = len(repo_urls) - middle_index - 1
    assert len(attempted_repos) > middle_index, \
        "Processing stopped after permission error"


@given(valid_github_url())
@settings(max_examples=100)
def test_permission_error_logged_and_skipped(repo_url):
    """
    For any repository with permission error, the error should be logged and 
    the repository skipped.
    
    Validates: Requirements 9.2
    """
    # Create config with single repository
    config = Config(
        version='1.0',
        repositories=[RepositoryConfig(
            url=repo_url,
            branch='main',
            paths=['.kiro/']
        )],
        infrastructure=InfrastructureConfig(
            cron_schedule='rate(1 hour)',
            lambda_memory=1024,
            lambda_timeout=300,
            vector_db_dimensions=1536
        ),
        models=ModelConfig(
            embedding_model='amazon.titan-embed-text-v1',
            llm_model='anthropic.claude-3-haiku-20240307',
            llm_temperature=0.7,
            max_tokens=2048,
            retrieval_k=5
        )
    )
    
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Simulate permission error
    github_client.validate_repository_access = Mock(return_value=False)
    
    # Track if directory contents were fetched (should not be)
    directory_fetches = []
    
    def mock_get_directory_contents(url, path, branch):
        directory_fetches.append(url)
        return []
    
    github_client.get_directory_contents = mock_get_directory_contents
    
    # Create monitor
    monitor = DocumentMonitor(
        config=config,
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Execute monitoring
    result = monitor.execute()
    
    # Property 1: Error should be logged
    assert len(result.errors) > 0, \
        "No error logged for permission failure"
    
    # Property 2: Error message should mention the repository
    error_mentions_repo = any(repo_url in error for error in result.errors)
    assert error_mentions_repo, \
        f"Error message doesn't mention repository: {result.errors}"
    
    # Property 3: Repository should be skipped (no directory fetch)
    assert len(directory_fetches) == 0, \
        "Repository with permission error had directory fetched"
    
    # Property 4: repositories_checked should be 0
    assert result.repositories_checked == 0, \
        "Repository with permission error was counted as checked"


@given(config_with_error_repositories())
@settings(max_examples=100)
def test_multiple_permission_errors_all_logged(config_and_data):
    """
    For any set of repositories with multiple permission errors, all errors 
    should be logged.
    
    Validates: Requirements 9.2
    """
    config, repo_data = config_and_data
    
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Build a dictionary of URL -> error_type (first occurrence wins for duplicates)
    url_error_map = {}
    for repo_info in repo_data:
        url = repo_info['config'].url
        if url not in url_error_map:
            url_error_map[url] = repo_info['error_type']
    
    def mock_validate_access(repo_url):
        # Only succeed if no error
        error_type = url_error_map.get(repo_url, 'not_found')
        return error_type is None
    
    github_client.validate_repository_access = mock_validate_access
    github_client.get_directory_contents = Mock(return_value=[])
    
    # Create monitor
    monitor = DocumentMonitor(
        config=config,
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Execute monitoring
    result = monitor.execute()
    
    # Property: Number of errors should match number of inaccessible repositories
    # Count configs whose URL has an error
    expected_errors = sum(1 for r in repo_data if url_error_map.get(r['config'].url) is not None)
    assert len(result.errors) == expected_errors, \
        f"Expected {expected_errors} errors, got {len(result.errors)}"
    
    # Property: Each error should be a non-empty string
    for error in result.errors:
        assert isinstance(error, str) and len(error) > 0, \
            "Error should be non-empty string"
