"""Basic unit tests for ChangeTracker functionality."""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Lambda directory added to path via conftest.py

from storage.change_tracker import ChangeTracker, DynamoDBThrottlingError, DynamoDBConnectionError
from botocore.exceptions import ClientError


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


def test_get_last_known_sha_returns_none_for_new_document():
    """Test that get_last_known_sha returns None for documents not yet tracked."""
    mock_dynamodb, _ = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    sha = tracker.get_last_known_sha('https://github.com/org/repo', '.kiro/doc.md')
    assert sha is None


def test_update_sha_stores_document():
    """Test that update_sha successfully stores a document."""
    mock_dynamodb, storage = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    repo = 'https://github.com/org/repo'
    file_path = '.kiro/doc.md'
    sha = 'abc123def456'
    timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    tracker.update_sha(repo, file_path, sha, timestamp)
    
    # Verify document is stored
    retrieved_sha = tracker.get_last_known_sha(repo, file_path)
    assert retrieved_sha == sha


def test_has_changed_returns_true_for_new_document():
    """Test that has_changed returns True for documents not yet tracked."""
    mock_dynamodb, _ = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    changed = tracker.has_changed('https://github.com/org/repo', '.kiro/doc.md', 'abc123')
    assert changed is True


def test_has_changed_returns_false_for_unchanged_document():
    """Test that has_changed returns False when SHA matches."""
    mock_dynamodb, _ = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    repo = 'https://github.com/org/repo'
    file_path = '.kiro/doc.md'
    sha = 'abc123def456'
    timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    tracker.update_sha(repo, file_path, sha, timestamp)
    
    changed = tracker.has_changed(repo, file_path, sha)
    assert changed is False


def test_has_changed_returns_true_for_changed_document():
    """Test that has_changed returns True when SHA differs."""
    mock_dynamodb, _ = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    repo = 'https://github.com/org/repo'
    file_path = '.kiro/doc.md'
    old_sha = 'abc123def456'
    new_sha = 'xyz789uvw012'
    timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    tracker.update_sha(repo, file_path, old_sha, timestamp)
    
    changed = tracker.has_changed(repo, file_path, new_sha)
    assert changed is True


def test_delete_document_removes_tracking():
    """Test that delete_document removes tracking information."""
    mock_dynamodb, storage = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    repo = 'https://github.com/org/repo'
    file_path = '.kiro/doc.md'
    sha = 'abc123def456'
    timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    tracker.update_sha(repo, file_path, sha, timestamp)
    assert tracker.get_last_known_sha(repo, file_path) == sha
    
    tracker.delete_document(repo, file_path)
    assert tracker.get_last_known_sha(repo, file_path) is None


def test_make_key_creates_composite_key():
    """Test that _make_key creates proper composite keys."""
    mock_dynamodb, _ = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    key = tracker._make_key('https://github.com/org/repo', '.kiro/doc.md')
    assert key == 'https://github.com/org/repo#.kiro/doc.md'
    assert '#' in key


def test_get_document_state_returns_complete_info():
    """Test that get_document_state returns all document information."""
    mock_dynamodb, _ = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    repo = 'https://github.com/org/repo'
    file_path = '.kiro/doc.md'
    sha = 'abc123def456'
    timestamp = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    content_hash = 'hash123'
    
    tracker.update_sha(repo, file_path, sha, timestamp, content_hash)
    
    state = tracker.get_document_state(repo, file_path)
    assert state is not None
    assert state.sha == sha
    assert state.content_hash == content_hash
    assert state.repo_file_path == tracker._make_key(repo, file_path)


def test_get_document_state_returns_none_for_new_document():
    """Test that get_document_state returns None for untracked documents."""
    mock_dynamodb, _ = create_mock_dynamodb()
    tracker = ChangeTracker(table_name='test-table', dynamodb_client=mock_dynamodb)
    
    state = tracker.get_document_state('https://github.com/org/repo', '.kiro/doc.md')
    assert state is None
