"""
Property-based tests for document content extraction.

Feature: archon-rag-system, Property 6: Document content extraction
Validates: Requirements 3.3
"""

import os
import sys
from hypothesis import given, strategies as st, settings
from unittest.mock import Mock, patch
from datetime import datetime, timezone

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lambda'))

from shared.config_manager import RepositoryConfig
from shared.github_client import GitHubClient, FileMetadata
from shared.change_tracker import ChangeTracker
from shared.ingestion_pipeline import IngestionPipeline, Document
from monitor.document_monitor import DocumentMonitor


@st.composite
def valid_github_url(draw):
    """Generate valid GitHub repository URLs."""
    org = draw(st.from_regex(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$', fullmatch=True))
    repo = draw(st.from_regex(r'^[a-zA-Z0-9._-]{1,100}$', fullmatch=True))
    return f"https://github.com/{org}/{repo}"


@st.composite
def file_metadata_list(draw):
    """Generate list of file metadata."""
    num_files = draw(st.integers(min_value=1, max_value=10))
    files = []
    
    for i in range(num_files):
        path = draw(st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='/-_.'),
            min_size=5,
            max_size=50
        ))
        sha = draw(st.text(
            alphabet=st.characters(whitelist_categories=('Nd',), whitelist_characters='abcdef'),
            min_size=40,
            max_size=40
        ))
        size = draw(st.integers(min_value=1, max_value=100000))
        url = f"https://github.com/org/repo/blob/main/{path}"
        
        files.append(FileMetadata(
            path=path,
            sha=sha,
            size=size,
            url=url
        ))
    
    return files


@st.composite
def document_content(draw):
    """Generate document content."""
    return draw(st.text(min_size=10, max_size=5000))


# Feature: archon-rag-system, Property 6: Document content extraction
@given(
    valid_github_url(),
    file_metadata_list(),
    st.lists(document_content(), min_size=1, max_size=10)
)
@settings(max_examples=100)
def test_document_content_extraction(repo_url, file_metadata, contents):
    """
    For any detected document change, the system should successfully extract 
    the complete file content.
    
    Validates: Requirements 3.3
    """
    # Ensure we have matching content for each file
    while len(contents) < len(file_metadata):
        contents.append("Default content for testing")
    contents = contents[:len(file_metadata)]
    
    # Create repository config
    repo_config = RepositoryConfig(
        url=repo_url,
        branch='main',
        paths=['.kiro/']
    )
    
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Track extracted content
    extracted_documents = []
    
    def mock_get_directory_contents(url, path, branch):
        return file_metadata
    
    # Build a map of file_path -> content (first occurrence wins for duplicates)
    path_content_map = {}
    for i, fm in enumerate(file_metadata):
        if fm.path not in path_content_map:
            path_content_map[fm.path] = contents[i]
    
    def mock_get_file_content(url, file_path, branch):
        return path_content_map.get(file_path, "default content")
    
    github_client.get_directory_contents = mock_get_directory_contents
    github_client.get_file_content = mock_get_file_content
    
    # Create monitor (we'll test fetch_repository_contents directly)
    monitor = DocumentMonitor(
        config=Mock(),
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Fetch repository contents
    documents = monitor.fetch_repository_contents(repo_config)
    
    # Property 1: Should extract content for all files
    assert len(documents) == len(file_metadata), \
        f"Expected {len(file_metadata)} documents, got {len(documents)}"
    
    # Property 2: Each document should have complete content
    for doc in documents:
        assert doc.content is not None, \
            f"Document {doc.file_path} has None content"
        assert len(doc.content) > 0, \
            f"Document {doc.file_path} has empty content"
    
    # Property 3: Content should match what was fetched
    for doc in documents:
        expected_content = path_content_map[doc.file_path]
        assert doc.content == expected_content, \
            f"Document content mismatch for {doc.file_path}"
    
    # Property 4: All documents should have required metadata
    for doc in documents:
        assert doc.repo_url == repo_url, \
            f"Document has wrong repo_url: {doc.repo_url}"
        assert doc.file_path in [fm.path for fm in file_metadata], \
            f"Document has unexpected file_path: {doc.file_path}"
        assert doc.sha in [fm.sha for fm in file_metadata], \
            f"Document has unexpected sha: {doc.sha}"


@given(valid_github_url(), file_metadata_list())
@settings(max_examples=100)
def test_content_extraction_completeness(repo_url, file_metadata):
    """
    For any list of files, content extraction should attempt all files even 
    if some fail.
    
    Validates: Requirements 3.3
    """
    # Create repository config
    repo_config = RepositoryConfig(
        url=repo_url,
        branch='main',
        paths=['.kiro/']
    )
    
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    # Track content fetch attempts
    fetch_attempts = []
    
    def mock_get_directory_contents(url, path, branch):
        return file_metadata
    
    def mock_get_file_content(url, file_path, branch):
        fetch_attempts.append(file_path)
        # Make every other file fail
        if len(fetch_attempts) % 2 == 0:
            from shared.github_client import GitHubAPIError
            raise GitHubAPIError("Simulated fetch failure")
        return f"Content for {file_path}"
    
    github_client.get_directory_contents = mock_get_directory_contents
    github_client.get_file_content = mock_get_file_content
    
    # Create monitor
    monitor = DocumentMonitor(
        config=Mock(),
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Fetch repository contents
    documents = monitor.fetch_repository_contents(repo_config)
    
    # Property: All files should be attempted
    assert len(fetch_attempts) == len(file_metadata), \
        f"Expected {len(file_metadata)} fetch attempts, got {len(fetch_attempts)}"
    
    # Property: Successfully fetched documents should have content
    for doc in documents:
        assert doc.content is not None and len(doc.content) > 0, \
            f"Document {doc.file_path} missing content"


@given(valid_github_url(), st.text(min_size=100, max_size=10000))
@settings(max_examples=100)
def test_content_extraction_preserves_full_text(repo_url, content):
    """
    For any document content, extraction should preserve the complete text 
    without truncation or modification.
    
    Validates: Requirements 3.3
    """
    # Create file metadata
    file_metadata = [FileMetadata(
        path='.kiro/test.md',
        sha='abc123' * 7,  # 40 chars
        size=len(content),
        url=f"{repo_url}/blob/main/.kiro/test.md"
    )]
    
    # Create repository config
    repo_config = RepositoryConfig(
        url=repo_url,
        branch='main',
        paths=['.kiro/']
    )
    
    # Create mock components
    github_client = Mock(spec=GitHubClient)
    change_tracker = Mock(spec=ChangeTracker)
    ingestion_pipeline = Mock(spec=IngestionPipeline)
    
    github_client.get_directory_contents = Mock(return_value=file_metadata)
    github_client.get_file_content = Mock(return_value=content)
    
    # Create monitor
    monitor = DocumentMonitor(
        config=Mock(),
        github_client=github_client,
        change_tracker=change_tracker,
        ingestion_pipeline=ingestion_pipeline
    )
    
    # Fetch repository contents
    documents = monitor.fetch_repository_contents(repo_config)
    
    # Property: Extracted content should exactly match original
    assert len(documents) == 1, "Should extract exactly one document"
    assert documents[0].content == content, \
        "Extracted content doesn't match original"
    assert len(documents[0].content) == len(content), \
        f"Content length mismatch: expected {len(content)}, got {len(documents[0].content)}"
