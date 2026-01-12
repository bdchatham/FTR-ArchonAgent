"""PostgreSQL change tracker for document state management."""

import asyncio
from typing import Optional
from datetime import datetime
import structlog
import asyncpg

logger = structlog.get_logger()


class ChangeTracker:
    """Tracks document changes using PostgreSQL."""
    
    def __init__(self, db_url: str):
        """Initialize change tracker."""
        self.db_url = db_url
        self._pool = None
    
    async def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.db_url)
        return self._pool
    
    async def get_last_sha(self, repo_file_path: str) -> Optional[str]:
        """
        Get the last known SHA for a document.
        
        Args:
            repo_file_path: Composite key "{repo_url}#{file_path}"
            
        Returns:
            Last known SHA or None if not found
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval(
                    "SELECT sha FROM document_state WHERE repo_file_path = $1",
                    repo_file_path
                )
                return result
                
        except Exception as e:
            logger.error("Failed to get last SHA", 
                        repo_file_path=repo_file_path, 
                        error=str(e))
            return None
    
    async def update_document_state(
        self, 
        repo_file_path: str, 
        sha: str, 
        last_modified: datetime
    ):
        """
        Update document state after processing.
        
        Args:
            repo_file_path: Composite key "{repo_url}#{file_path}"
            sha: Document SHA hash
            last_modified: Document last modified time
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO document_state 
                    (repo_file_path, sha, last_modified, last_checked)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (repo_file_path) 
                    DO UPDATE SET 
                        sha = EXCLUDED.sha,
                        last_modified = EXCLUDED.last_modified,
                        last_checked = EXCLUDED.last_checked
                """, repo_file_path, sha, last_modified, datetime.now())
                
                logger.debug("Document state updated", 
                           repo_file_path=repo_file_path, 
                           sha=sha)
                
        except Exception as e:
            logger.error("Failed to update document state", 
                        repo_file_path=repo_file_path, 
                        error=str(e))
            raise
    
    async def has_changed(self, repo_file_path: str, current_sha: str) -> bool:
        """
        Check if document has changed.
        
        Args:
            repo_file_path: Composite key "{repo_url}#{file_path}"
            current_sha: Current document SHA
            
        Returns:
            True if document has changed
        """
        last_sha = await self.get_last_sha(repo_file_path)
        return last_sha != current_sha
    
    async def close(self):
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
