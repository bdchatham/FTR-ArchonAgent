"""Document monitor for checking repository changes and ingesting documents."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
import sys
import os

# Add lambda directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config.config_manager import Config, RepositoryConfig
from git.github_client import (
    GitHubClient,
    GitHubClientError,
    RepositoryNotFoundError,
    RepositoryAccessDeniedError,
    GitHubAPIError,
    FileMetadata
)
from storage.change_tracker import ChangeTracker, ChangeTrackerError
from ingestion.ingestion_pipeline import IngestionPipeline, Document, IngestionError


# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class MonitoringResult:
    """Results from a monitoring execution."""
    repositories_checked: int
    documents_processed: int
    documents_updated: int
    errors: List[str]
    execution_time: float


class DocumentMonitorError(Exception):
    """Base exception for document monitor errors."""
    pass


class DocumentMonitor:
    """
    Orchestrates monitoring workflow for checking repository changes.
    
    Responsibilities:
    - Check all configured repositories for .kiro/ document changes
    - Detect changes using ChangeTracker
    - Fetch changed document content
    - Process documents through ingestion pipeline
    - Track execution metrics and errors
    """
    
    def __init__(
        self,
        config: Config,
        github_client: GitHubClient,
        change_tracker: ChangeTracker,
        ingestion_pipeline: IngestionPipeline
    ):
        """
        Initialize DocumentMonitor.
        
        Args:
            config: System configuration
            github_client: GitHub API client
            change_tracker: Change tracking service
            ingestion_pipeline: Document ingestion pipeline
        """
        self.config = config
        self.github_client = github_client
        self.change_tracker = change_tracker
        self.ingestion_pipeline = ingestion_pipeline
    
    def execute(self) -> MonitoringResult:
        """
        Execute monitoring workflow for all configured repositories.
        
        Returns:
            MonitoringResult with execution metrics
        """
        start_time = datetime.now(timezone.utc)
        
        repositories_checked = 0
        documents_processed = 0
        documents_updated = 0
        errors = []
        
        logger.info(f"Starting monitoring execution for {len(self.config.repositories)} repositories")
        
        # Process each repository independently
        for repo_config in self.config.repositories:
            try:
                logger.info(f"Checking repository: {repo_config.url}")
                
                # Validate repository access (checks if repository is public and accessible)
                try:
                    is_accessible = self.github_client.validate_repository_access(repo_config.url)
                except Exception as e:
                    error_msg = f"Failed to validate access for {repo_config.url}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    continue
                
                if not is_accessible:
                    error_msg = f"Repository not accessible (may be private or not found): {repo_config.url}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    continue
                
                repositories_checked += 1
                
                # Fetch repository contents
                documents = self.fetch_repository_contents(repo_config)
                logger.info(f"Found {len(documents)} documents in {repo_config.url}")
                
                # Detect changes
                changed_documents = self.detect_changes(documents)
                logger.info(f"Detected {len(changed_documents)} changed documents")
                
                # Process changed documents
                processed_count = self.process_changed_documents(changed_documents)
                documents_processed += len(changed_documents)
                documents_updated += processed_count
                
            except (RepositoryNotFoundError, RepositoryAccessDeniedError) as e:
                # Log error and continue with next repository
                error_msg = f"Access error for {repo_config.url}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
                
            except GitHubAPIError as e:
                # Log API error and continue
                error_msg = f"GitHub API error for {repo_config.url}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
                
            except ChangeTrackerError as e:
                # Log change tracker error and continue
                error_msg = f"Change tracking error for {repo_config.url}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
                
            except IngestionError as e:
                # Log ingestion error and continue
                error_msg = f"Ingestion error for {repo_config.url}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
                
            except Exception as e:
                # Log unexpected error and continue
                error_msg = f"Unexpected error for {repo_config.url}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                continue
        
        end_time = datetime.now(timezone.utc)
        execution_time = (end_time - start_time).total_seconds()
        
        result = MonitoringResult(
            repositories_checked=repositories_checked,
            documents_processed=documents_processed,
            documents_updated=documents_updated,
            errors=errors,
            execution_time=execution_time
        )
        
        logger.info(
            f"Monitoring execution completed: "
            f"{repositories_checked} repos checked, "
            f"{documents_processed} docs processed, "
            f"{documents_updated} docs updated, "
            f"{len(errors)} errors, "
            f"{execution_time:.2f}s"
        )
        
        return result
    
    def fetch_repository_contents(self, repo: RepositoryConfig) -> List[Document]:
        """
        Fetch all documents from configured paths in a repository.
        
        Args:
            repo: Repository configuration
            
        Returns:
            List of Document objects
            
        Raises:
            GitHubClientError: If fetching fails
        """
        documents = []
        
        for path in repo.paths:
            try:
                # Get directory contents
                file_metadata_list = self.github_client.get_directory_contents(
                    repo.url,
                    path,
                    repo.branch
                )
                
                # Fetch content for each file
                for file_metadata in file_metadata_list:
                    try:
                        content = self.github_client.get_file_content(
                            repo.url,
                            file_metadata.path,
                            repo.branch
                        )
                        
                        # Create Document object
                        document = Document(
                            repo_url=repo.url,
                            file_path=file_metadata.path,
                            content=content,
                            sha=file_metadata.sha,
                            last_modified=datetime.now(timezone.utc),
                            document_type="kiro_doc",
                            source_type="github"
                        )
                        
                        documents.append(document)
                        
                    except GitHubClientError as e:
                        logger.warning(f"Failed to fetch content for {file_metadata.path}: {e}")
                        continue
                        
            except GitHubClientError as e:
                logger.warning(f"Failed to fetch directory {path}: {e}")
                continue
        
        return documents
    
    def detect_changes(self, documents: List[Document]) -> List[Document]:
        """
        Detect which documents have changed since last check.
        
        Args:
            documents: List of documents to check
            
        Returns:
            List of changed documents
            
        Raises:
            ChangeTrackerError: If change detection fails
        """
        changed_documents = []
        
        for document in documents:
            try:
                if self.change_tracker.has_changed(
                    document.repo_url,
                    document.file_path,
                    document.sha
                ):
                    changed_documents.append(document)
                    logger.debug(f"Document changed: {document.file_path}")
                else:
                    logger.debug(f"Document unchanged: {document.file_path}")
                    
            except ChangeTrackerError as e:
                logger.warning(
                    f"Failed to check changes for {document.file_path}: {e}"
                )
                # Assume changed if we can't check
                changed_documents.append(document)
        
        return changed_documents
    
    def process_changed_documents(self, documents: List[Document]) -> int:
        """
        Process changed documents through ingestion pipeline.
        
        Args:
            documents: List of changed documents
            
        Returns:
            Number of successfully processed documents
            
        Raises:
            IngestionError: If processing fails
        """
        processed_count = 0
        
        for document in documents:
            try:
                # Ingest document
                chunk_count = self.ingestion_pipeline.ingest_document(document)
                logger.info(
                    f"Ingested {document.file_path}: {chunk_count} chunks"
                )
                
                # Update change tracker
                self.change_tracker.update_sha(
                    document.repo_url,
                    document.file_path,
                    document.sha,
                    document.last_modified
                )
                
                processed_count += 1
                
            except IngestionError as e:
                logger.error(
                    f"Failed to ingest {document.file_path}: {e}"
                )
                # Continue with next document
                continue
                
            except ChangeTrackerError as e:
                logger.error(
                    f"Failed to update change tracker for {document.file_path}: {e}"
                )
                # Document was ingested but tracking failed
                # Still count as processed
                processed_count += 1
                continue
        
        return processed_count


def lambda_handler(event, context):
    """
    AWS Lambda handler for document monitoring.
    
    This function is triggered by EventBridge on a schedule to monitor
    configured repositories for documentation changes.
    
    Args:
        event: EventBridge event (not used)
        context: Lambda context object
        
    Returns:
        dict: Response with status code and monitoring results
    """
    try:
        # Load configuration
        from config.config_manager import ConfigManager
        config_manager = ConfigManager()
        config = config_manager.load_config(os.environ.get('CONFIG_PATH', '/var/task/config/config.yaml'))
        
        # Initialize components
        github_client = GitHubClient(access_token=os.environ.get('GITHUB_TOKEN'))
        change_tracker = ChangeTracker(table_name=os.environ.get('DYNAMODB_TABLE', 'archon-document-tracker'))
        
        # Initialize ingestion pipeline (requires embeddings and vector store)
        from ingestion.ingestion_pipeline import IngestionPipeline
        from storage.vector_store_manager import VectorStoreManager
        from langchain_aws import BedrockEmbeddings
        
        embeddings = BedrockEmbeddings(
            model_id=config.models.embedding_model,
            region_name=os.environ.get('AWS_REGION', 'us-east-1')
        )
        
        vector_store = VectorStoreManager(
            opensearch_endpoint=os.environ['OPENSEARCH_ENDPOINT'],
            index_name=os.environ.get('OPENSEARCH_INDEX', 'archon-documents')
        )
        
        ingestion_pipeline = IngestionPipeline(
            embeddings=embeddings,
            vector_store=vector_store
        )
        
        # Create monitor
        monitor = DocumentMonitor(
            config=config,
            github_client=github_client,
            change_tracker=change_tracker,
            ingestion_pipeline=ingestion_pipeline
        )
        
        # Execute monitoring
        result = monitor.execute()
        
        # Return success response
        return {
            'statusCode': 200,
            'body': {
                'message': 'Monitoring completed successfully',
                'repositories_checked': result.repositories_checked,
                'documents_processed': result.documents_processed,
                'documents_updated': result.documents_updated,
                'errors': result.errors,
                'execution_time': result.execution_time
            }
        }
        
    except Exception as e:
        logger.error(f"Lambda handler error: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': {
                'message': 'Monitoring failed',
                'error': str(e)
            }
        }
    
    def execute(self) -> MonitoringResult:
        """
        Execute monitoring workflow for all configured repositories.
        
        Returns:
            MonitoringResult with execution metrics
        """
        start_time = datetime.now(timezone.utc)
        
        repositories_checked = 0
        documents_processed = 0
        documents_updated = 0
        errors = []
        
        logger.info(f"Starting monitoring execution for {len(self.config.repositories)} repositories")
        
        # Process each repository independently
        for repo_config in self.config.repositories:
            try:
                logger.info(f"Checking repository: {repo_config.url}")
                
                # Validate repository access (checks if repository is public and accessible)
                try:
                    is_accessible = self.github_client.validate_repository_access(repo_config.url)
                except Exception as e:
                    error_msg = f"Failed to validate access for {repo_config.url}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    continue
                
                if not is_accessible:
                    error_msg = f"Repository not accessible (may be private or not found): {repo_config.url}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    continue
                
                repositories_checked += 1
                
                # Fetch repository contents
                documents = self.fetch_repository_contents(repo_config)
                logger.info(f"Found {len(documents)} documents in {repo_config.url}")
                
                # Detect changes
                changed_documents = self.detect_changes(documents)
                logger.info(f"Detected {len(changed_documents)} changed documents")
                
                # Process changed documents
                processed_count = self.process_changed_documents(changed_documents)
                documents_processed += len(changed_documents)
                documents_updated += processed_count
                
            except (RepositoryNotFoundError, RepositoryAccessDeniedError) as e:
                # Log error and continue with next repository
                error_msg = f"Access error for {repo_config.url}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
                
            except GitHubAPIError as e:
                # Log API error and continue
                error_msg = f"GitHub API error for {repo_config.url}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
                
            except ChangeTrackerError as e:
                # Log change tracker error and continue
                error_msg = f"Change tracking error for {repo_config.url}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
                
            except IngestionError as e:
                # Log ingestion error and continue
                error_msg = f"Ingestion error for {repo_config.url}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
                
            except Exception as e:
                # Log unexpected error and continue
                error_msg = f"Unexpected error for {repo_config.url}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                continue
        
        end_time = datetime.now(timezone.utc)
        execution_time = (end_time - start_time).total_seconds()
        
        result = MonitoringResult(
            repositories_checked=repositories_checked,
            documents_processed=documents_processed,
            documents_updated=documents_updated,
            errors=errors,
            execution_time=execution_time
        )
        
        logger.info(
            f"Monitoring execution completed: "
            f"{repositories_checked} repos checked, "
            f"{documents_processed} docs processed, "
            f"{documents_updated} docs updated, "
            f"{len(errors)} errors, "
            f"{execution_time:.2f}s"
        )
        
        return result
    
    def fetch_repository_contents(self, repo: RepositoryConfig) -> List[Document]:
        """
        Fetch all documents from configured paths in a repository.
        
        Args:
            repo: Repository configuration
            
        Returns:
            List of Document objects
            
        Raises:
            GitHubClientError: If fetching fails
        """
        documents = []
        
        for path in repo.paths:
            try:
                # Get directory contents
                file_metadata_list = self.github_client.get_directory_contents(
                    repo.url,
                    path,
                    repo.branch
                )
                
                # Fetch content for each file
                for file_metadata in file_metadata_list:
                    try:
                        content = self.github_client.get_file_content(
                            repo.url,
                            file_metadata.path,
                            repo.branch
                        )
                        
                        # Create Document object
                        document = Document(
                            repo_url=repo.url,
                            file_path=file_metadata.path,
                            content=content,
                            sha=file_metadata.sha,
                            last_modified=datetime.now(timezone.utc),
                            document_type="kiro_doc",
                            source_type="github"
                        )
                        
                        documents.append(document)
                        
                    except GitHubClientError as e:
                        logger.warning(f"Failed to fetch content for {file_metadata.path}: {e}")
                        continue
                        
            except GitHubClientError as e:
                logger.warning(f"Failed to fetch directory {path}: {e}")
                continue
        
        return documents
    
    def detect_changes(self, documents: List[Document]) -> List[Document]:
        """
        Detect which documents have changed since last check.
        
        Args:
            documents: List of documents to check
            
        Returns:
            List of changed documents
            
        Raises:
            ChangeTrackerError: If change detection fails
        """
        changed_documents = []
        
        for document in documents:
            try:
                if self.change_tracker.has_changed(
                    document.repo_url,
                    document.file_path,
                    document.sha
                ):
                    changed_documents.append(document)
                    logger.debug(f"Document changed: {document.file_path}")
                else:
                    logger.debug(f"Document unchanged: {document.file_path}")
                    
            except ChangeTrackerError as e:
                logger.warning(
                    f"Failed to check changes for {document.file_path}: {e}"
                )
                # Assume changed if we can't check
                changed_documents.append(document)
        
        return changed_documents
    
    def process_changed_documents(self, documents: List[Document]) -> int:
        """
        Process changed documents through ingestion pipeline.
        
        Args:
            documents: List of changed documents
            
        Returns:
            Number of successfully processed documents
            
        Raises:
            IngestionError: If processing fails
        """
        processed_count = 0
        
        for document in documents:
            try:
                # Ingest document
                chunk_count = self.ingestion_pipeline.ingest_document(document)
                logger.info(
                    f"Ingested {document.file_path}: {chunk_count} chunks"
                )
                
                # Update change tracker
                self.change_tracker.update_sha(
                    document.repo_url,
                    document.file_path,
                    document.sha,
                    document.last_modified
                )
                
                processed_count += 1
                
            except IngestionError as e:
                logger.error(
                    f"Failed to ingest {document.file_path}: {e}"
                )
                # Continue with next document
                continue
                
            except ChangeTrackerError as e:
                logger.error(
                    f"Failed to update change tracker for {document.file_path}: {e}"
                )
                # Document was ingested but tracking failed
                # Still count as processed
                processed_count += 1
                continue
        
        return processed_count
