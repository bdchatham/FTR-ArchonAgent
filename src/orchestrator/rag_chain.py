"""RAG chain using LangChain for context augmentation and LLM calls."""

import logging
from typing import AsyncIterator, List

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from aphex_clients import QueryClient

from .config import Settings
from .models import ChatMessage
from .retriever import KnowledgeBaseRetriever

logger = logging.getLogger(__name__)

CONTEXT_TEMPLATE = """## Relevant Context

The following information was retrieved from the knowledge base:

{context}

Use this context to inform your response. If the context doesn't contain relevant information, rely on your general knowledge."""


class RAGChain:
    """RAG chain using LangChain for orchestration."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._query_client: QueryClient | None = None
        self._retriever: KnowledgeBaseRetriever | None = None
        self._llm: ChatOpenAI | None = None

    async def initialize(self):
        """Initialize clients and chain components."""
        self._query_client = QueryClient(
            base_url=self.settings.query_url,
            timeout=self.settings.rag_retrieval_timeout,
        )
        
        self._retriever = KnowledgeBaseRetriever(
            query_client=self._query_client,
            k=self.settings.rag_context_chunks,
            score_threshold=self.settings.rag_similarity_threshold,
        )
        
        self._llm = ChatOpenAI(
            base_url=f"{self.settings.model_url}/v1",
            api_key="not-needed",
            model=self.settings.model_name,
            streaming=True,
        )

    async def close(self):
        """Close clients."""
        if self._query_client:
            await self._query_client._client.aclose()

    def _format_context(self, documents: List[Document]) -> str:
        """Format retrieved documents into context string."""
        if not documents:
            return ""
        
        parts = []
        for doc in documents:
            source = doc.metadata.get("source", "unknown")
            source_name = source.split("/")[-1] if "/" in source else source
            parts.append(f"**Source:** {source_name}\n{doc.page_content}")
        
        context = "\n\n---\n\n".join(parts)
        return CONTEXT_TEMPLATE.format(context=context)

    def _convert_messages(self, messages: List[ChatMessage]):
        """Convert API messages to LangChain message types."""
        converted = []
        for msg in messages:
            if msg.role == "system":
                converted.append(SystemMessage(content=msg.content))
            elif msg.role == "user":
                converted.append(HumanMessage(content=msg.content))
            elif msg.role == "assistant":
                converted.append(AIMessage(content=msg.content))
        return converted

    def _extract_query(self, messages: List[ChatMessage]) -> str:
        """Extract query from last user message."""
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content
        return ""

    def _augment_messages(
        self,
        messages: List[ChatMessage],
        context: str,
    ) -> List[ChatMessage]:
        """Inject context into messages."""
        if not context:
            return messages

        augmented = []
        system_found = False

        for msg in messages:
            if msg.role == "system" and not system_found:
                augmented.append(
                    ChatMessage(
                        role="system",
                        content=f"{msg.content}\n\n{context}",
                    )
                )
                system_found = True
            else:
                augmented.append(msg)

        if not system_found:
            augmented.insert(0, ChatMessage(role="system", content=context))

        return augmented

    async def process_messages(
        self,
        messages: List[ChatMessage],
    ) -> List[ChatMessage]:
        """Process messages through RAG pipeline."""
        if not self.settings.rag_enabled:
            return messages

        query = self._extract_query(messages)
        if not query:
            return messages

        documents = await self._retriever._aretrieve(query)
        if not documents:
            return messages

        context = self._format_context(documents)
        return self._augment_messages(messages, context)

    async def stream_response(
        self,
        messages: List[ChatMessage],
    ) -> AsyncIterator[str]:
        """Stream LLM response for augmented messages."""
        langchain_messages = self._convert_messages(messages)
        
        async for chunk in self._llm.astream(langchain_messages):
            if chunk.content:
                yield chunk.content

    async def generate_response(self, messages: List[ChatMessage]) -> str:
        """Generate complete LLM response for augmented messages."""
        langchain_messages = self._convert_messages(messages)
        response = await self._llm.ainvoke(langchain_messages)
        return response.content
