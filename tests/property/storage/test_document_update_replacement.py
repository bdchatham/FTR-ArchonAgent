"""
Property-based tests for document update replacement in change tracking.

Feature: archon-rag-system, Property 11: Document update replaces previous version
Validates: Requirements 4.4
"""

import os
import sys
from datetime import datetime, timedelta
from hypothesis import given, strategies as st, settings
from unittest.mock import MagicMock


from storage.change_tracker import ChangeTracker


# Strategies for generating test data
@st.composite
def valid_github_url(draw):
    """Generate valid GitHub repository URLs."""
    org = draw(st.from_regex(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$', fullmatch=True))
    repo = draw(st.from_regex(r'^[a-zA-Z0-9._-]{1,100}$', fullmatch=True))
    return f"https://github.com/{org}/{repo}"


@st.composite
def valid_file_path(draw):
    """Generate valid file paths."""
    # Generate path components
    num_components = draw(st.integers(min_value=1, max_value=5))
    components = [
        draw(st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='_-.'),
            min_size=1,
            max_size=20
        ))
        for _ in range(num_components)
    ]
    return '/'.join(components)


@st.composite
def valid_sha(draw):
    """Generate valid SHA hashes (40 character hex strings)."""
    return draw(st.text(alphabet='0123456789abcdef', min_size=40, max_size=40))


@st.composite
def document_update_sequence(draw):
    """Generate a sequence of updates for the same document."""
    repo = draw(valid_github_url())
    file_path = draw(valid_file_path())
    
    # Generate multiple versions (SHAs and timestamps)
    num_versions = draw(st.integers(min_value=2, max_value=5))
    base_time = datetime(2025, 1, 1, 0, 0, 0)
    
    versions = []
    for i in range(num_versions):
        sha = draw(valid_sha())
        timestamp = base_time + timedelta(hours=i)
        versions.append((sha, timestamp))
    
    return repo, file_path, versions


def create_mock_dynamodb():
    """Create a mock DynamoDB client that simulates table behavior."""
    storage = {}
    
    mock_client = MagicMock()
    
    def mock_get_item(TableName, Key):
        key_value = Key['repo_file_path']['S']
        if key_value in storage:
            return {'Item': storage[key_value]}
        return {}
    
    def mock_put_item(TableName, Item):
        key_value = Item['repo_file_path']['S']
        storage[key_value] = Item
    
    def mock_delete_item(TableName, Key):
        key_value = Key['repo_file_path']['S']
        if key_value in storage:
            del storage[key_value]
    
    mock_client.get_item.side_effect = mock_get_item
    mock_client.put_item.side_effect = mock_put_item
    mock_client.delete_item.side_effect = mock_delete_item
    
    return mock_client, storage


# Feature: archon-rag-system, Property 11: Document update replaces previous version
@given(document_update_sequence())
@settings(max_examples=100)
def test_document_update_replaces_previous_version(update_data):
    """
    For any document with the same repo_url and file_path, storing a new version 
    should replace the existing entry rather than creating a duplicate.
    
    Validates: Requirements 4.4
    """
    repo, file_path, versions = update_data
    
    # Create mock DynamoDB client
    mock_dynamodb, storage = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    # Property: After each update, there should be exactly one entry for the document
    for sha, timestamp in versions:
        tracker.update_sha(repo, file_path, sha, timestamp)
        
        # Check that only one entry exists for this document
        key = tracker._make_key(repo, file_path)
        assert key in storage, "Document should be stored"
        
        # Verify the stored SHA matches the latest update
        stored_sha = tracker.get_last_known_sha(repo, file_path)
        assert stored_sha == sha, f"Stored SHA should match latest update: expected {sha}, got {stored_sha}"
        
        # Verify there's exactly one entry (no duplicates)
        matching_keys = [k for k in storage.keys() if k == key]
        assert len(matching_keys) == 1, f"Should have exactly one entry, found {len(matching_keys)}"


@given(
    valid_github_url(),
    valid_file_path(),
    st.lists(valid_sha(), min_size=2, max_size=10, unique=True)
)
@settings(max_examples=100)
def test_multiple_updates_maintain_single_entry(repo, file_path, sha_list):
    """
    For any sequence of updates to the same document, the tracker should 
    maintain exactly one entry with the most recent SHA.
    
    Validates: Requirements 4.4
    """
    mock_dynamodb, storage = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    base_time = datetime(2025, 1, 1, 0, 0, 0)
    
    # Apply all updates
    for i, sha in enumerate(sha_list):
        timestamp = base_time + timedelta(minutes=i)
        tracker.update_sha(repo, file_path, sha, timestamp)
    
    # Property: Only one entry should exist
    key = tracker._make_key(repo, file_path)
    assert len([k for k in storage.keys() if k == key]) == 1
    
    # Property: The stored SHA should be the last one
    stored_sha = tracker.get_last_known_sha(repo, file_path)
    assert stored_sha == sha_list[-1]


@given(
    st.lists(
        st.tuples(valid_github_url(), valid_file_path(), valid_sha()),
        min_size=1,
        max_size=20,
        unique_by=lambda x: (x[0], x[1])  # Unique by repo+file_path
    )
)
@settings(max_examples=100)
def test_different_documents_stored_separately(documents):
    """
    For any set of different documents (different repo or file_path), 
    each should be stored as a separate entry.
    
    Validates: Requirements 4.4
    """
    mock_dynamodb, storage = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    timestamp = datetime(2025, 1, 1, 0, 0, 0)
    
    # Store all documents
    for repo, file_path, sha in documents:
        tracker.update_sha(repo, file_path, sha, timestamp)
    
    # Property: Number of entries should equal number of unique documents
    assert len(storage) == len(documents)
    
    # Property: Each document should be retrievable with correct SHA
    for repo, file_path, expected_sha in documents:
        stored_sha = tracker.get_last_known_sha(repo, file_path)
        assert stored_sha == expected_sha


@given(
    valid_github_url(),
    valid_file_path(),
    valid_sha(),
    valid_sha()
)
@settings(max_examples=100)
def test_update_changes_sha_value(repo, file_path, first_sha, second_sha):
    """
    For any document, updating with a new SHA should change the stored value.
    
    Validates: Requirements 4.4
    """
    # Skip if SHAs are the same (not a real update)
    if first_sha == second_sha:
        return
    
    mock_dynamodb, storage = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    timestamp1 = datetime(2025, 1, 1, 0, 0, 0)
    timestamp2 = datetime(2025, 1, 1, 1, 0, 0)
    
    # Store first version
    tracker.update_sha(repo, file_path, first_sha, timestamp1)
    assert tracker.get_last_known_sha(repo, file_path) == first_sha
    
    # Update to second version
    tracker.update_sha(repo, file_path, second_sha, timestamp2)
    
    # Property: SHA should be updated to new value
    stored_sha = tracker.get_last_known_sha(repo, file_path)
    assert stored_sha == second_sha
    assert stored_sha != first_sha
    
    # Property: Still only one entry
    key = tracker._make_key(repo, file_path)
    assert len([k for k in storage.keys() if k == key]) == 1
