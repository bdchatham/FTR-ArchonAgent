"""Change tracking for monitoring document updates using DynamoDB."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import boto3
from botocore.exceptions import ClientError, BotoCoreError
import time


@dataclass
class DocumentState:
    """State information for a tracked document."""
    repo_file_path: str
    sha: str
    last_modified: datetime
    last_checked: datetime
    content_hash: str


class ChangeTrackerError(Exception):
    """Base exception for change tracker errors."""
    pass


class DynamoDBThrottlingError(ChangeTrackerError):
    """Raised when DynamoDB throttling occurs."""
    pass


class DynamoDBConnectionError(ChangeTrackerError):
    """Raised when DynamoDB connection fails."""
    pass


class ChangeTracker:
    """
    Tracks document versions using DynamoDB to detect changes.
    
    DynamoDB Schema:
        Table: archon-document-tracker
        Partition Key: repo_file_path (String) - format: "{repo_url}#{file_path}"
        Attributes:
            - sha (String)
            - last_modified (String - ISO timestamp)
            - last_checked (String - ISO timestamp)
            - content_hash (String)
    """
    
    MAX_RETRIES = 3
    INITIAL_BACKOFF = 0.1  # 100ms
    MAX_BACKOFF = 5.0  # 5 seconds
    
    def __init__(self, table_name: str, dynamodb_client=None):
        """
        Initialize ChangeTracker.
        
        Args:
            table_name: Name of the DynamoDB table
            dynamodb_client: Optional boto3 DynamoDB client (for testing)
        """
        self.table_name = table_name
        self._dynamodb = dynamodb_client or boto3.client('dynamodb')
    
    def _make_key(self, repo: str, file_path: str) -> str:
        """
        Create partition key from repo and file path.
        
        Args:
            repo: Repository URL
            file_path: File path within repository
            
        Returns:
            Composite key string
        """
        return f"{repo}#{file_path}"
    
    def _retry_with_backoff(self, operation, *args, **kwargs):
        """
        Execute DynamoDB operation with exponential backoff retry.
        
        Args:
            operation: Function to execute
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation
            
        Returns:
            Result of operation
            
        Raises:
            DynamoDBThrottlingError: If throttling persists after retries
            DynamoDBConnectionError: If connection fails
        """
        backoff = self.INITIAL_BACKOFF
        last_exception = None
        
        for attempt in range(self.MAX_RETRIES):
            try:
                return operation(*args, **kwargs)
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                
                if error_code in ['ProvisionedThroughputExceededException', 'ThrottlingException']:
                    last_exception = e
                    if attempt < self.MAX_RETRIES - 1:
                        # Exponential backoff with jitter
                        sleep_time = min(backoff * (2 ** attempt), self.MAX_BACKOFF)
                        time.sleep(sleep_time)
                        continue
                    else:
                        raise DynamoDBThrottlingError(
                            f"DynamoDB throttling after {self.MAX_RETRIES} retries"
                        ) from e
                else:
                    # Non-throttling error
                    raise DynamoDBConnectionError(
                        f"DynamoDB error: {error_code} - {e.response.get('Error', {}).get('Message', str(e))}"
                    ) from e
            except BotoCoreError as e:
                raise DynamoDBConnectionError(
                    f"DynamoDB connection error: {str(e)}"
                ) from e
        
        # Should not reach here, but just in case
        if last_exception:
            raise DynamoDBThrottlingError(
                f"DynamoDB throttling after {self.MAX_RETRIES} retries"
            ) from last_exception
    
    def get_last_known_sha(self, repo: str, file_path: str) -> Optional[str]:
        """
        Get the last known SHA for a document.
        
        Args:
            repo: Repository URL
            file_path: File path within repository
            
        Returns:
            SHA string if document is tracked, None otherwise
            
        Raises:
            DynamoDBThrottlingError: If throttling persists
            DynamoDBConnectionError: If connection fails
        """
        key = self._make_key(repo, file_path)
        
        def get_item():
            response = self._dynamodb.get_item(
                TableName=self.table_name,
                Key={'repo_file_path': {'S': key}}
            )
            return response
        
        response = self._retry_with_backoff(get_item)
        
        if 'Item' in response:
            return response['Item'].get('sha', {}).get('S')
        return None
    
    def update_sha(
        self, 
        repo: str, 
        file_path: str, 
        sha: str, 
        timestamp: datetime,
        content_hash: Optional[str] = None
    ) -> None:
        """
        Update the SHA and timestamp for a document.
        
        Args:
            repo: Repository URL
            file_path: File path within repository
            sha: New SHA hash
            timestamp: Last modified timestamp
            content_hash: Optional content hash
            
        Raises:
            DynamoDBThrottlingError: If throttling persists
            DynamoDBConnectionError: If connection fails
        """
        key = self._make_key(repo, file_path)
        now = datetime.now(timezone.utc).isoformat()
        
        item = {
            'repo_file_path': {'S': key},
            'sha': {'S': sha},
            'last_modified': {'S': timestamp.isoformat()},
            'last_checked': {'S': now}
        }
        
        if content_hash:
            item['content_hash'] = {'S': content_hash}
        
        def put_item():
            self._dynamodb.put_item(
                TableName=self.table_name,
                Item=item
            )
        
        self._retry_with_backoff(put_item)
    
    def has_changed(self, repo: str, file_path: str, current_sha: str) -> bool:
        """
        Check if a document has changed based on SHA comparison.
        
        Args:
            repo: Repository URL
            file_path: File path within repository
            current_sha: Current SHA hash from GitHub
            
        Returns:
            True if document has changed or is new, False otherwise
            
        Raises:
            DynamoDBThrottlingError: If throttling persists
            DynamoDBConnectionError: If connection fails
        """
        last_sha = self.get_last_known_sha(repo, file_path)
        
        # If no previous SHA, document is new (changed)
        if last_sha is None:
            return True
        
        # Compare SHAs
        return last_sha != current_sha
    
    def get_document_state(self, repo: str, file_path: str) -> Optional[DocumentState]:
        """
        Get complete state information for a document.
        
        Args:
            repo: Repository URL
            file_path: File path within repository
            
        Returns:
            DocumentState if document is tracked, None otherwise
            
        Raises:
            DynamoDBThrottlingError: If throttling persists
            DynamoDBConnectionError: If connection fails
        """
        key = self._make_key(repo, file_path)
        
        def get_item():
            response = self._dynamodb.get_item(
                TableName=self.table_name,
                Key={'repo_file_path': {'S': key}}
            )
            return response
        
        response = self._retry_with_backoff(get_item)
        
        if 'Item' not in response:
            return None
        
        item = response['Item']
        
        return DocumentState(
            repo_file_path=key,
            sha=item.get('sha', {}).get('S', ''),
            last_modified=datetime.fromisoformat(item.get('last_modified', {}).get('S', '')),
            last_checked=datetime.fromisoformat(item.get('last_checked', {}).get('S', '')),
            content_hash=item.get('content_hash', {}).get('S', '')
        )
    
    def delete_document(self, repo: str, file_path: str) -> None:
        """
        Delete tracking information for a document.
        
        Args:
            repo: Repository URL
            file_path: File path within repository
            
        Raises:
            DynamoDBThrottlingError: If throttling persists
            DynamoDBConnectionError: If connection fails
        """
        key = self._make_key(repo, file_path)
        
        def delete_item():
            self._dynamodb.delete_item(
                TableName=self.table_name,
                Key={'repo_file_path': {'S': key}}
            )
        
        self._retry_with_backoff(delete_item)
