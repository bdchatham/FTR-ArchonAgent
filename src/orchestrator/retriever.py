"""LangChain retriever that wraps the Knowledge Base QueryClient."""

import asyncio
import logging
from typing import List

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from aphex_clients import QueryClient

logger = logging.getLogger(__name__)


class KnowledgeBaseRetriever(BaseRetriever):
    """LangChain retriever backed by the Archon Knowledge Base.
    
    Wraps QueryClient to provide a LangChain-compatible retriever interface.
    This enables integration with LangChain's RAG patterns and future
    features like conversation memory and tool calling.
    """
    
    query_client: QueryClient
    k: int = 5
    score_threshold: float = 0.5

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        """Sync retrieval - runs async method in event loop."""
        return asyncio.run(self._aretrieve(query))

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        """Async retrieval from Knowledge Base."""
        return await self._aretrieve(query)

    async def _aretrieve(self, query: str) -> List[Document]:
        """Retrieve and convert to LangChain Documents."""
        try:
            chunks = await self.query_client.retrieve(query, k=self.k)
            
            documents = [
                Document(
                    page_content=chunk.content,
                    metadata={
                        "source": chunk.source,
                        "chunk_index": chunk.chunk_index,
                        "score": chunk.score,
                    },
                )
                for chunk in chunks
                if chunk.score >= self.score_threshold
            ]
            
            logger.info(
                f"Retrieved {len(documents)} documents "
                f"(filtered from {len(chunks)}) for query: {query[:50]}..."
            )
            return documents
            
        except Exception as e:
            logger.warning(f"Knowledge Base retrieval failed: {e}")
            return []
