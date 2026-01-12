"""Document monitor workflow orchestration."""

import time
from typing import Dict, Any, List
import structlog

from archon.monitor.github_client import GitHubClient
from archon.storage.change_tracker import ChangeTracker
from archon.storage.vector_store import VectorStoreManager
from archon.ingestion.pipeline import IngestionPipeline

logger = structlog.get_logger()


class DocumentMonitorWorkflow:
    """Orchestrates document monitoring workflow."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize workflow with configuration."""
        self.config = config
        self.github_client = GitHubClient(config["github_token"])
        self.change_tracker = ChangeTracker(config["tracker_db_url"])
        self.vector_store = VectorStoreManager(config["vector_db_url"])
        self.ingestion_pipeline = IngestionPipeline(
            vector_store=self.vector_store,
            embedding_service_url=config["vllm_base_url"],
            embedding_model=config["embedding_model"],
            chunk_size=int(config["chunk_size"]),
            chunk_overlap=int(config["chunk_overlap"])
        )
        
    async def execute(self) -> Dict[str, Any]:
        """Execute the monitoring workflow."""
        results = {
            "repositories_checked": 0,
            "documents_processed": 0,
            "documents_changed": 0,
            "errors": 0
        }
        
        repositories = self.config["repositories"]
        logger.info("Starting workflow", repository_count=len(repositories))
        
        for repo_config in repositories:
            try:
                repo_results = await self._process_repository(repo_config)
                results["repositories_checked"] += 1
                results["documents_processed"] += repo_results["documents_processed"]
                results["documents_changed"] += repo_results["documents_changed"]
                
            except Exception as e:
                logger.error("Repository processing failed", 
                           repo_url=repo_config.get("url", "unknown"),
                           error=str(e))
                results["errors"] += 1
        
        return results
    
    async def _process_repository(self, repo_config: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single repository."""
        repo_url = repo_config["url"]
        branch = repo_config.get("branch", "main")
        paths = repo_config.get("paths", [".kiro/docs"])
        
        logger.info("Processing repository", repo_url=repo_url, branch=branch)
        
        results = {"documents_processed": 0, "documents_changed": 0}
        
        for path in paths:
            try:
                # Fetch documents from GitHub
                documents = await self.github_client.fetch_documents(
                    repo_url=repo_url,
                    branch=branch,
                    path=path
                )
                
                for document in documents:
                    results["documents_processed"] += 1
                    
                    # Check if document has changed
                    if await self._has_document_changed(document):
                        results["documents_changed"] += 1
                        
                        # Process through ingestion pipeline
                        await self.ingestion_pipeline.process_document(document)
                        
                        # Update change tracker
                        await self.change_tracker.update_document_state(
                            repo_file_path=f"{repo_url}#{document.file_path}",
                            sha=document.sha,
                            last_modified=document.last_modified
                        )
                        
                        logger.info("Document processed", 
                                   repo_url=repo_url,
                                   file_path=document.file_path)
                    
            except Exception as e:
                logger.error("Path processing failed", 
                           repo_url=repo_url, 
                           path=path, 
                           error=str(e))
                raise
        
        return results
    
    async def _has_document_changed(self, document) -> bool:
        """Check if document has changed since last processing."""
        repo_file_path = f"{document.repo_url}#{document.file_path}"
        
        last_sha = await self.change_tracker.get_last_sha(repo_file_path)
        return last_sha != document.sha
