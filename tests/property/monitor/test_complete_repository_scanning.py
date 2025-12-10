"""
Property-based tests for complete repository scanning.

Feature: archon-rag-system, Property 5: Complete repository scanning
Validates: Requirements 3.1
"""

import os
import sys
from hypothesis import given, strategies as st, settings
from unittest.mock import Mock, patch
from datetime import datetime, timezone


from config.config_manager import Config, RepositoryConfig, InfrastructureConfig, ModelConfig
from git.github_client import GitHubClient
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
def repository_config_list(draw):
    """Generate list of repository configurations."""
    num_repos = draw(st.integers(min_value=1, max_value=10))
    repos = []
    
    for _ in range(num_repos):
        url = draw(valid_github_url())
        branch = draw(st.sampled_from(['main', 'master', 'develop']))
        paths = draw(st.lists(
            st.sampled_from(['.kiro/', 'docs/', '.kiro/architecture/']),
            min_size=1,
            max_size=3
        ))
        
        repos.append(RepositoryConfig(
            url=url,
            branch=branch,
            paths=paths
        ))
    
    return repos


@st.composite
def config_with_repositories(draw):
    """Generate complete Config with repositories."""
    repos = draw(repository_config_list())
    
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
    
    return Config(
        version='1.0',
        repositories=repos,
        infrastructure=infra,
        models=models
    )


# Feature: archon-rag-system, Property 5: Complete repository scanning
@given(config_with_repositories())
@settings(max_examples=100)
def test_complete_repository_scanning(config):
    """
    For any list of configured repositories, the monitor should check each 
    repository exactly once per execution.
    
    Validates: Requirements 3.1
    """
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Track which repositories were checked
    checked_repos = []
    
    def mock_validate_access(repo_url):
        checked_repos.append(repo_url)
        return True
    
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
    
    # Property 1: All repository configs should be checked
    assert len(checked_repos) == len(config.repositories), \
        f"Expected {len(config.repositories)} repos checked, got {len(checked_repos)}"
    
    # Property 2: Each repository config should be checked in order
    for i, repo_config in enumerate(config.repositories):
        assert checked_repos[i] == repo_config.url, \
            f"Repository at position {i} doesn't match: expected {repo_config.url}, got {checked_repos[i]}"
    
    # Property 3: repositories_checked in result should match successful validations
    # (all repos in this test pass validation)
    assert result.repositories_checked == len(config.repositories), \
        f"Result shows {result.repositories_checked} repos checked, expected {len(config.repositories)}"


@given(config_with_repositories())
@settings(max_examples=100)
def test_repository_scanning_order_independence(config):
    """
    For any list of repositories, all should be scanned regardless of order.
    
    Validates: Requirements 3.1
    """
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Track scan order
    scan_order = []
    
    def mock_validate_access(repo_url):
        scan_order.append(repo_url)
        return True
    
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
    
    # Property: All repositories should be in scan order
    assert len(scan_order) == len(config.repositories), \
        "Not all repositories were scanned"
    
    # Property: Scan order should match config order
    for i, repo_config in enumerate(config.repositories):
        assert scan_order[i] == repo_config.url, \
            f"Repository at position {i} doesn't match expected order"


@given(config_with_repositories())
@settings(max_examples=100)
def test_repository_scanning_with_failures(config):
    """
    For any list of repositories, even if some fail validation, all should 
    be attempted.
    
    Validates: Requirements 3.1
    """
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Track attempts
    attempted_repos = []
    
    def mock_validate_access(repo_url):
        attempted_repos.append(repo_url)
        # Make every other repository fail
        return len(attempted_repos) % 2 == 1
    
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
    
    # Property: All repository configs should be attempted despite failures
    assert len(attempted_repos) == len(config.repositories), \
        f"Expected {len(config.repositories)} attempts, got {len(attempted_repos)}"
    
    # Property: Each repository config should be attempted in order
    for i, repo_config in enumerate(config.repositories):
        assert attempted_repos[i] == repo_config.url, \
            f"Repository at position {i} doesn't match: expected {repo_config.url}, got {attempted_repos[i]}"
