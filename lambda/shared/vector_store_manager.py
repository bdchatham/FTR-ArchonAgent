"""Vector store manager for OpenSearch Serverless integration."""

import uuid
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from opensearchpy import OpenSearch, RequestsHttpConnection
from langchain_community.vectorstores import OpenSearchVectorSearch
from langchain_aws import BedrockEmbeddings


@dataclass
class VectorDocument:
    """Represents a document with embeddings for vector storage."""
    id: str
    vector: List[float]
    metadata: dict
    text: str


class VectorStoreError(Exception):
    """Base exception for vector store errors."""
    pass


class VectorStoreManager:
    """
    Manager for OpenSearch Serverless vector store operations.
    
    Handles:
    - Index creation with vector field configuration
    - Vector upsert operations with metadata
    - Similarity search with k-nearest neighbors
    - Document deletion by source
    - Integration with LangChain OpenSearch vector store
    """
    
    def __init__(
        self,
        opensearch_endpoint: str,
        index_name: str,
        embedding_model: str = "amazon.titan-embed-text-v1",
        dimensions: int = 1536,
        opensearch_client: Optional[OpenSearch] = None,
        embeddings: Optional[BedrockEmbeddings] = None
    ):
        """
        Initialize the vector store manager.
        
        Args:
            opensearch_endpoint: OpenSearch Serverless endpoint URL
            index_name: Name of the index to use
            embedding_model: Name of the Bedrock embedding model
            dimensions: Dimension size for vectors (default 1536 for Titan)
            opensearch_client: Optional pre-configured OpenSearch client (for testing)
            embeddings: Optional pre-configured embeddings object (for testing)
        """
        self.opensearch_endpoint = opensearch_endpoint
        self.index_name = index_name
        self.embedding_model = embedding_model
        self.dimensions = dimensions
        
        # Initialize OpenSearch client
        if opensearch_client is not None:
            self.client = opensearch_client
        else:
            self.client = self._create_opensearch_client()
        
        # Initialize embeddings
        if embeddings is not None:
            self.embeddings = embeddings
        else:
            self.embeddings = BedrockEmbeddings(model_id=embedding_model)
        
        # Initialize LangChain vector store (lazy initialization)
        self._langchain_store: Optional[OpenSearchVectorSearch] = None
    
    def _create_opensearch_client(self) -> OpenSearch:
        """
        Create OpenSearch client for Serverless.
        
        Returns:
            Configured OpenSearch client
        """
        return OpenSearch(
            hosts=[{'host': self.opensearch_endpoint, 'port': 443}],
            http_auth=None,  # Uses AWS SigV4 authentication
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            pool_maxsize=20
        )
    
    def create_index(self, dimensions: Optional[int] = None) -> None:
        """
        Create OpenSearch index with vector field configuration.
        
        Args:
            dimensions: Vector dimension size (uses instance default if not provided)
            
        Raises:
            VectorStoreError: If index creation fails
        """
        if dimensions is None:
            dimensions = self.dimensions
        
        # Check if index already exists
        if self.client.indices.exists(index=self.index_name):
            return
        
        # Define index mapping with vector field
        index_body = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 512
                }
            },
            "mappings": {
                "properties": {
                    "vector": {
                        "type": "knn_vector",
                        "dimension": dimensions,
                        "method": {
                            "name": "hnsw",
                            "space_type": "l2",
                            "engine": "nmslib",
                            "parameters": {
                                "ef_construction": 512,
                                "m": 16
                            }
                        }
                    },
                    "text": {
                        "type": "text"
                    },
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "repo_url": {"type": "keyword"},
                            "file_path": {"type": "keyword"},
                            "chunk_index": {"type": "integer"},
                            "last_modified": {"type": "date"},
                            "document_type": {"type": "keyword"},
                            "source_type": {"type": "keyword"},
                            "sha": {"type": "keyword"}
                        }
                    }
                }
            }
        }
        
        try:
            self.client.indices.create(index=self.index_name, body=index_body)
        except Exception as e:
            raise VectorStoreError(f"Failed to create index: {str(e)}") from e
    
    def upsert_vectors(self, vector_documents: List[VectorDocument]) -> None:
        """
        Store or update vectors with metadata in OpenSearch.
        
        Args:
            vector_documents: List of VectorDocument objects to store
            
        Raises:
            VectorStoreError: If upsert operation fails
        """
        if not vector_documents:
            return
        
        try:
            # Prepare bulk operations
            bulk_body = []
            for vec_doc in vector_documents:
                # Index operation
                bulk_body.append({
                    "index": {
                        "_index": self.index_name,
                        "_id": vec_doc.id
                    }
                })
                
                # Document body
                bulk_body.append({
                    "vector": vec_doc.vector,
                    "text": vec_doc.text,
                    "metadata": vec_doc.metadata
                })
            
            # Execute bulk operation
            response = self.client.bulk(body=bulk_body, refresh=True)
            
            # Check for errors
            if response.get('errors'):
                errors = [item for item in response['items'] if 'error' in item.get('index', {})]
                raise VectorStoreError(f"Bulk upsert had errors: {errors}")
                
        except VectorStoreError:
            raise
        except Exception as e:
            raise VectorStoreError(f"Failed to upsert vectors: {str(e)}") from e
    
    def similarity_search(
        self,
        query_vector: List[float],
        k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform k-nearest neighbors similarity search.
        
        Args:
            query_vector: Query embedding vector
            k: Number of results to return
            filter_dict: Optional metadata filters
            
        Returns:
            List of documents with metadata and scores, ordered by relevance (descending)
            
        Raises:
            VectorStoreError: If search operation fails
        """
        try:
            # Build query
            knn_query = {
                "size": k,
                "query": {
                    "knn": {
                        "vector": {
                            "vector": query_vector,
                            "k": k
                        }
                    }
                }
            }
            
            # Add filters if provided
            if filter_dict:
                knn_query["query"] = {
                    "bool": {
                        "must": [
                            {"knn": {"vector": {"vector": query_vector, "k": k}}}
                        ],
                        "filter": [
                            {"term": {f"metadata.{key}": value}}
                            for key, value in filter_dict.items()
                        ]
                    }
                }
            
            # Execute search
            response = self.client.search(
                index=self.index_name,
                body=knn_query
            )
            
            # Parse results
            results = []
            for hit in response['hits']['hits']:
                results.append({
                    'id': hit['_id'],
                    'score': hit['_score'],
                    'text': hit['_source'].get('text', ''),
                    'metadata': hit['_source'].get('metadata', {}),
                    'vector': hit['_source'].get('vector', [])
                })
            
            # Results are already ordered by score (descending) from OpenSearch
            return results
            
        except Exception as e:
            raise VectorStoreError(f"Failed to perform similarity search: {str(e)}") from e
    
    def delete_by_source(self, repo: str, file_path: str) -> int:
        """
        Delete all documents from a specific source (repo + file path).
        
        Args:
            repo: Repository URL
            file_path: File path within repository
            
        Returns:
            Number of documents deleted
            
        Raises:
            VectorStoreError: If delete operation fails
        """
        try:
            # Query to find matching documents
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"metadata.repo_url": repo}},
                            {"term": {"metadata.file_path": file_path}}
                        ]
                    }
                }
            }
            
            # Delete by query
            response = self.client.delete_by_query(
                index=self.index_name,
                body=query,
                refresh=True
            )
            
            return response.get('deleted', 0)
            
        except Exception as e:
            raise VectorStoreError(f"Failed to delete by source: {str(e)}") from e
    
    def get_langchain_store(self) -> OpenSearchVectorSearch:
        """
        Get LangChain OpenSearch vector store instance.
        
        Returns:
            Configured OpenSearchVectorSearch instance
        """
        if self._langchain_store is None:
            self._langchain_store = OpenSearchVectorSearch(
                opensearch_url=f"https://{self.opensearch_endpoint}",
                index_name=self.index_name,
                embedding_function=self.embeddings,
                http_auth=None,  # Uses AWS SigV4
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection
            )
        
        return self._langchain_store
