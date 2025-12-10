"""Document ingestion pipeline for processing and storing documents."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
import time
import hashlib
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_aws import BedrockEmbeddings


@dataclass
class Document:
    """Represents a document from a repository."""
    repo_url: str
    file_path: str
    content: str
    sha: str
    last_modified: datetime
    document_type: str = "kiro_doc"
    source_type: str = "github"


@dataclass
class DocumentChunk:
    """Represents a chunk of a document."""
    document: Document
    chunk_index: int
    text: str
    start_char: int
    end_char: int


@dataclass
class VectorDocument:
    """Represents a document with embeddings for vector storage."""
    id: str
    vector: List[float]
    metadata: dict
    text: str


class IngestionError(Exception):
    """Base exception for ingestion pipeline errors."""
    pass


class EmbeddingGenerationError(IngestionError):
    """Raised when embedding generation fails."""
    pass


class IngestionPipeline:
    """
    Pipeline for processing documents and storing in vector database.
    
    Handles:
    - Document chunking using LangChain
    - Embedding generation using AWS Bedrock
    - Retry logic with exponential backoff
    - Document preprocessing
    """
    
    # Chunking parameters
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200
    
    # Default retry parameters
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_INITIAL_BACKOFF = 1.0  # 1 second
    DEFAULT_MAX_BACKOFF = 16.0  # 16 seconds
    

    
    def __init__(
        self,
        embedding_model: str = "amazon.titan-embed-text-v1",
        vector_store=None,
        bedrock_client=None,
        embeddings=None,
        max_retries: int = None,
        initial_backoff: float = None,
        max_backoff: float = None
    ):
        """
        Initialize the ingestion pipeline.
        
        Args:
            embedding_model: Name of the Bedrock embedding model
            vector_store: Optional vector store manager
            bedrock_client: Optional boto3 Bedrock client (for testing)
            embeddings: Optional pre-configured embeddings object (for testing)
            max_retries: Maximum number of retry attempts (defaults to 3)
            initial_backoff: Initial backoff delay in seconds (defaults to 1.0)
            max_backoff: Maximum backoff delay in seconds (defaults to 16.0)
        """
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        
        # Configure retry parameters
        self.max_retries = max_retries if max_retries is not None else self.DEFAULT_MAX_RETRIES
        self.initial_backoff = initial_backoff if initial_backoff is not None else self.DEFAULT_INITIAL_BACKOFF
        self.max_backoff = max_backoff if max_backoff is not None else self.DEFAULT_MAX_BACKOFF
        
        # Initialize embeddings with Bedrock or use provided embeddings
        if embeddings is not None:
            self.embeddings = embeddings
        else:
            self.embeddings = BedrockEmbeddings(
                model_id=embedding_model,
                client=bedrock_client
            )
        
        # Initialize text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.CHUNK_SIZE,
            chunk_overlap=self.CHUNK_OVERLAP,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
    
    def preprocess_document(self, document: Document) -> Document:
        """
        Preprocess document content before chunking.
        
        Args:
            document: Document to preprocess
            
        Returns:
            Document with preprocessed content
        """
        content = document.content
        
        # Normalize whitespace
        content = re.sub(r'\r\n', '\n', content)
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        return Document(
            repo_url=document.repo_url,
            file_path=document.file_path,
            content=content,
            sha=document.sha,
            last_modified=document.last_modified,
            document_type=document.document_type,
            source_type=document.source_type
        )
    
    def chunk_document(self, document: Document) -> List[DocumentChunk]:
        """
        Chunk document into smaller pieces for embedding.
        
        Args:
            document: Document to chunk
            
        Returns:
            List of DocumentChunk objects
        """
        # Split text into chunks
        chunks = self.text_splitter.split_text(document.content)
        
        # Create DocumentChunk objects with metadata
        document_chunks = []
        current_pos = 0
        
        for i, chunk_text in enumerate(chunks):
            # Find the position of this chunk in the original text
            start_char = document.content.find(chunk_text, current_pos)
            if start_char == -1:
                start_char = current_pos
            end_char = start_char + len(chunk_text)
            
            document_chunks.append(DocumentChunk(
                document=document,
                chunk_index=i,
                text=chunk_text,
                start_char=start_char,
                end_char=end_char
            ))
            
            current_pos = end_char
        
        return document_chunks
    
    def generate_embeddings(self, text: str) -> List[float]:
        """
        Generate embeddings for text using AWS Bedrock with retry logic.
        
        Args:
            text: Text to embed
            
        Returns:
            List of embedding values
            
        Raises:
            EmbeddingGenerationError: If embedding generation fails after retries
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                # Generate embedding using LangChain Bedrock integration
                embedding = self.embeddings.embed_query(text)
                return embedding
                
            except Exception as e:
                last_exception = e
                
                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    sleep_time = min(self.initial_backoff * (2 ** attempt), self.max_backoff)
                    time.sleep(sleep_time)
                    continue
                else:
                    raise EmbeddingGenerationError(
                        f"Failed to generate embedding after {self.max_retries} retries: {str(e)}"
                    ) from e
        
        # Should not reach here, but just in case
        if last_exception:
            raise EmbeddingGenerationError(
                f"Failed to generate embedding after {self.max_retries} retries"
            ) from last_exception
    
    def create_vector_documents(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]]
    ) -> List[VectorDocument]:
        """
        Create vector documents from chunks and embeddings.
        
        Args:
            chunks: List of document chunks
            embeddings: List of embedding vectors
            
        Returns:
            List of VectorDocument objects
        """
        if len(chunks) != len(embeddings):
            raise IngestionError(
                f"Mismatch between chunks ({len(chunks)}) and embeddings ({len(embeddings)})"
            )
        
        vector_docs = []
        
        for chunk, embedding in zip(chunks, embeddings):
            # Generate unique ID for this chunk
            doc_id = hashlib.sha256(
                f"{chunk.document.repo_url}#{chunk.document.file_path}#{chunk.chunk_index}".encode()
            ).hexdigest()
            
            # Create metadata
            metadata = {
                'repo_url': chunk.document.repo_url,
                'file_path': chunk.document.file_path,
                'chunk_index': chunk.chunk_index,
                'last_modified': chunk.document.last_modified.isoformat(),
                'document_type': chunk.document.document_type,
                'source_type': chunk.document.source_type,
                'sha': chunk.document.sha
            }
            
            vector_docs.append(VectorDocument(
                id=doc_id,
                vector=embedding,
                metadata=metadata,
                text=chunk.text
            ))
        
        return vector_docs
    
    def store_embeddings(
        self,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]]
    ) -> None:
        """
        Store embeddings in vector database.
        
        Args:
            chunks: List of document chunks
            embeddings: List of embedding vectors
            
        Raises:
            IngestionError: If vector store is not configured
        """
        if self.vector_store is None:
            raise IngestionError("Vector store not configured")
        
        # Create vector documents
        vector_docs = self.create_vector_documents(chunks, embeddings)
        
        # Store in vector database
        self.vector_store.upsert_vectors(vector_docs)
    
    def ingest_document(self, document: Document) -> int:
        """
        Process and ingest a complete document.
        
        Args:
            document: Document to ingest
            
        Returns:
            Number of chunks processed
            
        Raises:
            EmbeddingGenerationError: If embedding generation fails
            IngestionError: If ingestion fails
        """
        # Preprocess document
        processed_doc = self.preprocess_document(document)
        
        # Chunk document
        chunks = self.chunk_document(processed_doc)
        
        if not chunks:
            return 0
        
        # Generate embeddings for each chunk
        embeddings = []
        for chunk in chunks:
            embedding = self.generate_embeddings(chunk.text)
            embeddings.append(embedding)
        
        # Store embeddings if vector store is configured
        if self.vector_store:
            self.store_embeddings(chunks, embeddings)
        
        return len(chunks)
