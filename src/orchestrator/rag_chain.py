"""LangChain RAG chain for context augmentation."""

import logging
from typing import Optional

import httpx
from langchain_openai import ChatOpenAI

from .config import Settings
from .models import ChatMessage, RetrievalChunk, RetrievalResponse

logger = logging.getLogger(__name__)


class RAGChain:
    """RAG chain that retrieves context and augments prompts."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = ChatOpenAI(
            base_url=f"{settings.vllm_url}/v1",
            api_key="not-needed",
            model="Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
        )
        self._http_client: Optional[httpx.AsyncClient] = None

    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.rag_retrieval_timeout)
            )
        return self._http_client

    async def close(self):
        """Close HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def retrieve_context(self, query: str) -> list[RetrievalChunk]:
        """Retrieve relevant context from Knowledge Base."""
        if not self.settings.rag_enabled:
            return []

        try:
            client = await self.get_http_client()
            response = await client.post(
                f"{self.settings.knowledge_base_url}/v1/retrieve",
                json={"query": query, "k": self.settings.rag_context_chunks},
            )
            response.raise_for_status()

            data = RetrievalResponse(**response.json())
            
            # Filter by similarity threshold
            chunks = [
                chunk for chunk in data.chunks
                if chunk.score >= self.settings.rag_similarity_threshold
            ]
            
            logger.info(
                f"Retrieved {len(chunks)} chunks (filtered from {len(data.chunks)}) "
                f"for query: {query[:50]}..."
            )
            return chunks

        except httpx.TimeoutException:
            logger.warning(
                f"Knowledge Base retrieval timed out after "
                f"{self.settings.rag_retrieval_timeout}s"
            )
            return []
        except httpx.HTTPError as e:
            logger.warning(f"Knowledge Base retrieval failed: {e}")
            return []
        except Exception as e:
            logger.warning(f"Unexpected error during retrieval: {e}")
            return []

    def build_context_prompt(self, chunks: list[RetrievalChunk]) -> str:
        """Build context string from retrieved chunks."""
        if not chunks:
            return ""

        context_parts = [
            "## Relevant Context",
            "",
            "The following information was retrieved from the knowledge base:",
            "",
        ]

        for chunk in chunks:
            # Extract filename from source path
            source_name = chunk.source.split("/")[-1] if "/" in chunk.source else chunk.source
            context_parts.append(f"**Source:** {source_name}")
            context_parts.append(chunk.content)
            context_parts.append("---")
            context_parts.append("")

        context_parts.append(
            "Use this context to inform your response. "
            "If the context doesn't contain relevant information, "
            "rely on your general knowledge."
        )

        return "\n".join(context_parts)

    def augment_messages(
        self,
        messages: list[ChatMessage],
        context: str,
    ) -> list[ChatMessage]:
        """Augment messages with retrieved context."""
        if not context:
            return messages

        augmented = []
        system_found = False

        for msg in messages:
            if msg.role == "system" and not system_found:
                # Append context to existing system message
                augmented.append(
                    ChatMessage(
                        role="system",
                        content=f"{msg.content}\n\n{context}",
                    )
                )
                system_found = True
            else:
                augmented.append(msg)

        # If no system message, prepend one with context
        if not system_found:
            augmented.insert(
                0,
                ChatMessage(role="system", content=context),
            )

        return augmented

    def extract_query(self, messages: list[ChatMessage]) -> str:
        """Extract the user's query from the last user message."""
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content
        return ""

    async def process_messages(
        self,
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        """Process messages through RAG pipeline."""
        if not self.settings.rag_enabled:
            logger.debug("RAG disabled, returning original messages")
            return messages

        # Extract query from last user message
        query = self.extract_query(messages)
        if not query:
            logger.debug("No user message found, returning original messages")
            return messages

        # Retrieve context
        chunks = await self.retrieve_context(query)
        if not chunks:
            logger.debug("No context retrieved, returning original messages")
            return messages

        # Build context prompt and augment messages
        context = self.build_context_prompt(chunks)
        augmented = self.augment_messages(messages, context)

        logger.info(f"Augmented messages with {len(chunks)} context chunks")
        return augmented
