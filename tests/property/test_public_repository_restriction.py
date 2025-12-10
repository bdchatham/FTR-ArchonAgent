"""
Property-based tests for public repository restriction.

Feature: archon-rag-system, Property 19: Public repository restriction
Validates: Requirements 9.1
"""

import os
import sys
from hypothesis import given, strategies as st, settings
from unittest.mock import Mock, patch
from datetime import datetime, timezone

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambda'))

from shared.config_manager import Config, RepositoryConfig, InfrastructureConfig, ModelConfig
from shared.github_client import GitHubClient, RepositoryAccessDeniedError
from shared.change_tracker import ChangeTracker
from shared.ingestion_pipeline import IngestionPipeline
from monitor.document_monitor import DocumentMonitor


@st.composite
def valid_github_url(draw):
    """Generate valid GitHub repository URLs."""
    org = draw(st.from_regex(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$', fullmatch=True))
    repo = draw(st.from_regex(r'^[a-zA-Z0-9._-]{1,100}$', fullmatch=True))
    return f"https://github.com/{org}/{repo}"


@st.composite
def repository_config_with_access_flags(draw):
    """Generate repository configs with public/private flags."""
    num_repos = draw(st.integers(min_value=1, max_value=10))
    repos = []
    
    for _ in range(num_repos):
        url = draw(valid_github_url())
        branch = draw(st.sampled_from(['main', 'master']))
        is_public = draw(st.booleans())
        
        repos.append({
            'config': RepositoryConfig(
                url=url,
                branch=branch,
                paths=['.kiro/']
            ),
            'is_public': is_public
        })
    
    return repos


@st.composite
def config_with_mixed_repositories(draw):
    """Generate Config with mix of public and private repositories."""
    repo_data = draw(repository_config_with_access_flags())
    
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


# Feature: archon-rag-system, Property 19: Public repository restriction
@given(config_with_mixed_repositories())
@settings(max_examples=100)
def test_public_repository_restriction(config_and_data):
    """
    For any repository URL in the configuration, the system should only 
    process repositories that are publicly accessible.
    
    Validates: Requirements 9.1
    """
    config, repo_data = config_and_data
    
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Track which repositories were processed
    processed_repos = []
    
    # Build a dictionary of URL -> is_public (first occurrence wins for duplicates)
    url_access_map = {}
    for repo_info in repo_data:
        url = repo_info['config'].url
        if url not in url_access_map:
            url_access_map[url] = repo_info['is_public']
    
    def mock_validate_access(repo_url):
        # Return the access level for this URL
        return url_access_map.get(repo_url, False)
    
    def mock_get_directory_contents(url, path, branch):
        # Only called for repos that passed validation
        processed_repos.append(url)
        return []
    
    github_client.validate_repository_access = mock_validate_access
    github_client.get_directory_contents = mock_get_directory_contents
    
    # Ensure at least one repo is public for the test to be meaningful
    if not any(r['is_public'] for r in repo_data):
        # Skip this test case if no public repos
        return
    
    # Create monitor
    monitor = DocumentMonitor(
        config=config,
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Execute monitoring
    result = monitor.execute()
    
    # Property 1: Only public repositories should have content fetched
    # For each config, check if its URL is public. If so, it should be fetched.
    expected_fetches = sum(1 for r in repo_data if url_access_map.get(r['config'].url, False))
    assert len(processed_repos) == expected_fetches, \
        f"Expected {expected_fetches} public repo fetches, got {len(processed_repos)}"
    
    # Property 2: All processed repos should be public
    for repo_url in processed_repos:
        assert url_access_map.get(repo_url, False), \
            f"Private repository was processed: {repo_url}"
    
    # Property 3: Private repos should generate errors (one per config entry with private URL)
    expected_errors = sum(1 for r in repo_data if not url_access_map.get(r['config'].url, False))
    assert len(result.errors) == expected_errors, \
        f"Expected {expected_errors} errors for private repos, got {len(result.errors)}"


@given(st.lists(valid_github_url(), min_size=1, max_size=10))
@settings(max_examples=100)
def test_only_public_repositories_accessed(repo_urls):
    """
    For any list of repository URLs, only those that are publicly accessible 
    should have their contents fetched.
    
    Validates: Requirements 9.1
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
    
    # Track content fetch attempts
    content_fetches = []
    
    # Make every other repository "private"
    def mock_validate_access(repo_url):
        index = repo_urls.index(repo_url)
        return index % 2 == 0  # Even indices are public
    
    def mock_get_directory_contents(url, path, branch):
        content_fetches.append(url)
        return []
    
    github_client.validate_repository_access = mock_validate_access
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
    
    # Property: Only public repos should have content fetched
    # Build map of URL -> is_public (based on first occurrence)
    url_public_map = {}
    for i, url in enumerate(repo_urls):
        if url not in url_public_map:
            url_public_map[url] = (i % 2 == 0)
    
    # Count expected fetches: one per config entry with a public URL
    expected_fetches = sum(1 for i, url in enumerate(repo_urls) if url_public_map[url])
    assert len(content_fetches) == expected_fetches, \
        f"Expected {expected_fetches} content fetches, got {len(content_fetches)}"
    
    # Property: All fetched repos should be public
    for url in content_fetches:
        assert url_public_map[url], \
            f"Private repository had content fetched: {url}"


@given(valid_github_url())
@settings(max_examples=100)
def test_private_repository_not_processed(repo_url):
    """
    For any private repository, the system should not process its contents.
    
    Validates: Requirements 9.1
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
    
    # Track processing attempts
    directory_fetches = []
    document_ingestions = []
    
    # Make repository private (not accessible)
    github_client.validate_repository_access = Mock(return_value=False)
    
    def mock_get_directory_contents(url, path, branch):
        directory_fetches.append(url)
        return []
    
    def mock_ingest_document(doc):
        document_ingestions.append(doc)
        return 1
    
    github_client.get_directory_contents = mock_get_directory_contents
    ingestion_pipeline.ingest_document = mock_ingest_document
    
    # Create monitor
    monitor = DocumentMonitor(
        config=config,
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Execute monitoring
    result = monitor.execute()
    
    # Property: Private repository should not have directory fetched
    assert len(directory_fetches) == 0, \
        f"Private repository had directory fetched: {repo_url}"
    
    # Property: Private repository should not have documents ingested
    assert len(document_ingestions) == 0, \
        f"Private repository had documents ingested: {repo_url}"
    
    # Property: Result should show 0 repositories checked
    assert result.repositories_checked == 0, \
        f"Private repository was counted as checked"
    
    # Property: Result should contain an error
    assert len(result.errors) > 0, \
        "No error logged for inaccessible private repository"
