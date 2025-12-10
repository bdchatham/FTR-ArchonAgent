"""
Property-based tests for monitoring result completeness.

Feature: archon-rag-system, Property 7: Monitoring result completeness
Validates: Requirements 3.4
"""

import os
import sys
from hypothesis import given, strategies as st, settings
from unittest.mock import Mock
from datetime import datetime, timezone

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambda'))

from shared.config_manager import Config, RepositoryConfig, InfrastructureConfig, ModelConfig
from shared.github_client import GitHubClient, FileMetadata
from shared.change_tracker import ChangeTracker
from shared.ingestion_pipeline import IngestionPipeline, Document
from monitor.document_monitor import DocumentMonitor, MonitoringResult


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
        paths = ['.kiro/']
        
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


# Feature: archon-rag-system, Property 7: Monitoring result completeness
@given(config_with_repositories())
@settings(max_examples=100)
def test_monitoring_result_completeness(config):
    """
    For any monitoring execution, the result should include counts of 
    repositories checked, documents processed, and any errors encountered.
    
    Validates: Requirements 3.4
    """
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Configure mocks
    github_client.validate_repository_access = Mock(return_value=True)
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
    
    # Property 1: Result should be a MonitoringResult instance
    assert isinstance(result, MonitoringResult), \
        f"Result should be MonitoringResult, got {type(result)}"
    
    # Property 2: Result should have repositories_checked field
    assert hasattr(result, 'repositories_checked'), \
        "Result missing repositories_checked field"
    assert isinstance(result.repositories_checked, int), \
        "repositories_checked should be an integer"
    assert result.repositories_checked >= 0, \
        "repositories_checked should be non-negative"
    
    # Property 3: Result should have documents_processed field
    assert hasattr(result, 'documents_processed'), \
        "Result missing documents_processed field"
    assert isinstance(result.documents_processed, int), \
        "documents_processed should be an integer"
    assert result.documents_processed >= 0, \
        "documents_processed should be non-negative"
    
    # Property 4: Result should have documents_updated field
    assert hasattr(result, 'documents_updated'), \
        "Result missing documents_updated field"
    assert isinstance(result.documents_updated, int), \
        "documents_updated should be an integer"
    assert result.documents_updated >= 0, \
        "documents_updated should be non-negative"
    
    # Property 5: Result should have errors field
    assert hasattr(result, 'errors'), \
        "Result missing errors field"
    assert isinstance(result.errors, list), \
        "errors should be a list"
    
    # Property 6: Result should have execution_time field
    assert hasattr(result, 'execution_time'), \
        "Result missing execution_time field"
    assert isinstance(result.execution_time, (int, float)), \
        "execution_time should be numeric"
    assert result.execution_time >= 0, \
        "execution_time should be non-negative"


@given(config_with_repositories(), st.integers(min_value=0, max_value=10))
@settings(max_examples=100)
def test_monitoring_result_tracks_errors(config, num_errors):
    """
    For any monitoring execution with errors, the result should include all 
    error messages.
    
    Validates: Requirements 3.4
    """
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Configure mocks to generate errors for some repositories
    error_count = 0
    
    def mock_validate_access(repo_url):
        nonlocal error_count
        if error_count < num_errors and error_count < len(config.repositories):
            error_count += 1
            return False  # Fail validation
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
    
    # Property: Number of errors should match expected
    expected_errors = min(num_errors, len(config.repositories))
    assert len(result.errors) == expected_errors, \
        f"Expected {expected_errors} errors, got {len(result.errors)}"
    
    # Property: Each error should be a non-empty string
    for error in result.errors:
        assert isinstance(error, str), \
            f"Error should be string, got {type(error)}"
        assert len(error) > 0, \
            "Error message should not be empty"


@given(config_with_repositories())
@settings(max_examples=100)
def test_monitoring_result_counts_accuracy(config):
    """
    For any monitoring execution, the counts in the result should accurately 
    reflect what was processed.
    
    Validates: Requirements 3.4
    """
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Track actual processing
    validated_repos = []
    fetched_documents = []
    
    def mock_validate_access(repo_url):
        validated_repos.append(repo_url)
        return True
    
    # Create some test documents
    test_files = [
        FileMetadata(
            path='.kiro/test.md',
            sha='abc123' * 7,
            size=100,
            url='https://github.com/org/repo/test.md'
        )
    ]
    
    def mock_get_directory_contents(url, path, branch):
        return test_files
    
    def mock_get_file_content(url, file_path, branch):
        fetched_documents.append(file_path)
        return "Test content"
    
    github_client.validate_repository_access = mock_validate_access
    github_client.get_directory_contents = mock_get_directory_contents
    github_client.get_file_content = mock_get_file_content
    
    # Mock change tracker to say all documents changed
    change_tracker.has_changed = Mock(return_value=True)
    change_tracker.update_sha = Mock()
    
    # Mock ingestion pipeline
    ingestion_pipeline.ingest_document = Mock(return_value=1)
    
    # Create monitor
    monitor = DocumentMonitor(
        config=config,
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Execute monitoring
    result = monitor.execute()
    
    # Property: repositories_checked should match validated repos
    assert result.repositories_checked == len(validated_repos), \
        f"Expected {len(validated_repos)} repos checked, got {result.repositories_checked}"
    
    # Property: documents_processed should match fetched documents
    expected_docs = len(fetched_documents)
    assert result.documents_processed == expected_docs, \
        f"Expected {expected_docs} docs processed, got {result.documents_processed}"
    
    # Property: documents_updated should not exceed documents_processed
    assert result.documents_updated <= result.documents_processed, \
        "documents_updated should not exceed documents_processed"


@given(config_with_repositories())
@settings(max_examples=100)
def test_monitoring_result_execution_time_measured(config):
    """
    For any monitoring execution, the result should include a measured 
    execution time.
    
    Validates: Requirements 3.4
    """
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    github_client.validate_repository_access = Mock(return_value=True)
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
    
    # Property: execution_time should be positive
    assert result.execution_time > 0, \
        f"execution_time should be positive, got {result.execution_time}"
    
    # Property: execution_time should be reasonable (less than 1 hour for tests)
    assert result.execution_time < 3600, \
        f"execution_time seems unreasonably high: {result.execution_time}s"
