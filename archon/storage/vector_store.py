"""Qdrant vector store client for Archon."""

from typing import List, Dict, Any, Optional
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from langchain_community.vectorstores import Qdrant

logger = structlog.get_logger()


class VectorStoreManager:
    """Manages Qdrant vector database operations."""
    
    def __init__(self, qdrant_url: str, collection_name: str = "archon-docs"):
        """
        Initialize vector store manager.
        
        Args:
            qdrant_url: Qdrant server URL
            collection_name: Name of the collection to use
        """
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.client = QdrantClient(url=qdrant_url)
        self._langchain_store = None
        
    def is_healthy(self) -> bool:
        """Check if Qdrant is accessible."""
        try:
            self.client.get_collections()
            return True
        except Exception as e:
            logger.error("Qdrant health check failed", error=str(e))
            return False
    
    def get_langchain_store(self) -> Qdrant:
        """Get LangChain-compatible Qdrant store."""
        if self._langchain_store is None:
            self._langchain_store = Qdrant(
                client=self.client,
                collection_name=self.collection_name,
                embeddings=None  # Will be set by RAG chain
            )
        return self._langchain_store
    
    def similarity_search(
        self, 
        query_vector: List[float], 
        k: int = 5,
        score_threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform similarity search.
        
        Args:
            query_vector: Query embedding vector
            k: Number of results to return
            score_threshold: Minimum similarity score
            
        Returns:
            List of search results with text, metadata, and scores
        """
        try:
            search_result = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=k,
                score_threshold=score_threshold
            )
            
            results = []
            for point in search_result:
                results.append({
                    "text": point.payload.get("text", ""),
                    "metadata": {
                        "repo_url": point.payload.get("repo_url", ""),
                        "file_path": point.payload.get("file_path", ""),
                        "chunk_index": point.payload.get("chunk_index", 0),
                        "sha": point.payload.get("sha", ""),
                        "last_modified": point.payload.get("last_modified", ""),
                    },
                    "score": point.score
                })
            
            return results
            
        except Exception as e:
            logger.error("Vector search failed", error=str(e))
            raise
    
    def upsert_documents(self, documents: List[Dict[str, Any]]) -> None:
        """
        Upsert documents into the vector store.
        
        Args:
            documents: List of documents with id, vector, text, and metadata
        """
        try:
            points = []
            for doc in documents:
                points.append(PointStruct(
                    id=doc["id"],
                    vector=doc["vector"],
                    payload={
                        "text": doc["text"],
                        "repo_url": doc["metadata"].get("repo_url", ""),
                        "file_path": doc["metadata"].get("file_path", ""),
                        "chunk_index": doc["metadata"].get("chunk_index", 0),
                        "sha": doc["metadata"].get("sha", ""),
                        "last_modified": doc["metadata"].get("last_modified", ""),
                    }
                ))
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )
            
            logger.info("Upserted documents", count=len(documents))
            
        except Exception as e:
            logger.error("Document upsert failed", error=str(e))
            raise
