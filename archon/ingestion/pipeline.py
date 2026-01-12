"""Document ingestion pipeline for processing and storing documents."""

import hashlib
from typing import List, Dict, Any
from dataclasses import dataclass
import structlog
import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = structlog.get_logger()


@dataclass
class DocumentChunk:
    """Represents a chunk of a document."""
    document_id: str
    chunk_index: int
    text: str
    start_char: int
    end_char: int
    metadata: Dict[str, Any]


@dataclass
class VectorDocument:
    """Represents a document with embeddings for vector storage."""
    id: str
    vector: List[float]
    text: str
    metadata: Dict[str, Any]


class IngestionPipeline:
    """Processes documents through chunking, embedding, and storage."""
    
    def __init__(
        self,
        vector_store,
        embedding_service_url: str,
        embedding_model: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200
    ):
        """Initialize ingestion pipeline."""
        self.vector_store = vector_store
        self.embedding_service_url = embedding_service_url
        self.embedding_model = embedding_model
        
        # Initialize text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
        
        logger.info("Ingestion pipeline initialized",
                   embedding_service_url=embedding_service_url,
                   embedding_model=embedding_model,
                   chunk_size=chunk_size,
                   chunk_overlap=chunk_overlap)
    
    async def process_document(self, document) -> int:
        """
        Process a document through the full ingestion pipeline.
        
        Args:
            document: Document object to process
            
        Returns:
            Number of chunks processed
        """
        try:
            logger.info("Processing document", 
                       repo_url=document.repo_url,
                       file_path=document.file_path)
            
            # Step 1: Chunk the document
            chunks = self._chunk_document(document)
            
            # Step 2: Generate embeddings for chunks
            vector_docs = await self._embed_chunks(chunks)
            
            # Step 3: Store in vector database
            await self._store_vectors(vector_docs)
            
            logger.info("Document processed successfully",
                       repo_url=document.repo_url,
                       file_path=document.file_path,
                       chunks_count=len(chunks))
            
            return len(chunks)
            
        except Exception as e:
            logger.error("Document processing failed",
                        repo_url=document.repo_url,
                        file_path=document.file_path,
                        error=str(e))
            raise
    
    def _chunk_document(self, document) -> List[DocumentChunk]:
        """Split document into chunks."""
        try:
            # Split text into chunks
            text_chunks = self.text_splitter.split_text(document.content)
            
            # Create DocumentChunk objects
            chunks = []
            current_pos = 0
            
            for i, chunk_text in enumerate(text_chunks):
                # Find chunk position in original text
                start_pos = document.content.find(chunk_text, current_pos)
                if start_pos == -1:
                    start_pos = current_pos
                
                end_pos = start_pos + len(chunk_text)
                current_pos = end_pos
                
                # Create chunk with metadata
                chunk = DocumentChunk(
                    document_id=self._generate_document_id(document),
                    chunk_index=i,
                    text=chunk_text,
                    start_char=start_pos,
                    end_char=end_pos,
                    metadata={
                        "repo_url": document.repo_url,
                        "file_path": document.file_path,
                        "sha": document.sha,
                        "last_modified": document.last_modified.isoformat(),
                        "document_type": document.document_type,
                        "source_type": document.source_type,
                        "chunk_index": i,
                        "total_chunks": len(text_chunks)
                    }
                )
                chunks.append(chunk)
            
            return chunks
            
        except Exception as e:
            logger.error("Document chunking failed", error=str(e))
            raise
    
    async def _embed_chunks(self, chunks: List[DocumentChunk]) -> List[VectorDocument]:
        """Generate embeddings for document chunks."""
        try:
            vector_docs = []
            
            # Prepare texts for batch embedding
            texts = [chunk.text for chunk in chunks]
            
            # Generate embeddings via vLLM
            embeddings = await self._generate_embeddings(texts)
            
            # Create VectorDocument objects
            for chunk, embedding in zip(chunks, embeddings):
                vector_doc = VectorDocument(
                    id=self._generate_chunk_id(chunk),
                    vector=embedding,
                    text=chunk.text,
                    metadata=chunk.metadata
                )
                vector_docs.append(vector_doc)
            
            return vector_docs
            
        except Exception as e:
            logger.error("Chunk embedding failed", error=str(e))
            raise
    
    async def _generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using vLLM service."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.embedding_service_url}/v1/embeddings",
                    json={
                        "input": texts,
                        "model": self.embedding_model
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=30.0
                )
                response.raise_for_status()
                
                result = response.json()
                embeddings = [item["embedding"] for item in result["data"]]
                
                logger.debug("Embeddings generated", 
                           texts_count=len(texts),
                           embeddings_count=len(embeddings))
                
                return embeddings
                
        except Exception as e:
            logger.error("Embedding generation failed", error=str(e))
            raise
    
    async def _store_vectors(self, vector_docs: List[VectorDocument]):
        """Store vector documents in the vector database."""
        try:
            # Convert to format expected by vector store
            documents = []
            for vector_doc in vector_docs:
                documents.append({
                    "id": vector_doc.id,
                    "vector": vector_doc.vector,
                    "text": vector_doc.text,
                    "metadata": vector_doc.metadata
                })
            
            # Upsert to vector store
            self.vector_store.upsert_documents(documents)
            
            logger.debug("Vectors stored", count=len(documents))
            
        except Exception as e:
            logger.error("Vector storage failed", error=str(e))
            raise
    
    def _generate_document_id(self, document) -> str:
        """Generate unique document ID."""
        content = f"{document.repo_url}#{document.file_path}#{document.sha}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _generate_chunk_id(self, chunk: DocumentChunk) -> str:
        """Generate unique chunk ID."""
        content = f"{chunk.document_id}#{chunk.chunk_index}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
