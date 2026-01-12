"""Query service business logic."""

import time
from typing import Dict, Any
import structlog

from archon.query.rag_chain import ArchonRAGChain, RAGChainError
from archon.query.models import ChatCompletionRequest, ChatCompletionResponse, ChatCompletionChoice, ChatMessage, ChatCompletionUsage

logger = structlog.get_logger()


class QueryServiceError(Exception):
    """Base exception for query service errors."""
    pass


class QueryService:
    """Handles query processing business logic."""
    
    def __init__(self, rag_chain: ArchonRAGChain):
        """Initialize query service."""
        self.rag_chain = rag_chain
    
    async def process_chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """
        Process chat completion request.
        
        Args:
            request: Chat completion request
            
        Returns:
            Chat completion response
            
        Raises:
            QueryServiceError: If processing fails
        """
        try:
            # Extract user query
            user_messages = [msg for msg in request.messages if msg.role == "user"]
            if not user_messages:
                raise QueryServiceError("No user message found")
            
            query = user_messages[-1].content
            
            logger.info("Processing query", query=query[:100])
            
            # Execute RAG pipeline
            result = self.rag_chain.invoke(query)
            
            # Create response
            response = ChatCompletionResponse(
                id=f"chatcmpl-{int(time.time())}",
                created=int(time.time()),
                model=request.model,
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatMessage(
                            role="assistant",
                            content=result["result"]
                        ),
                        finish_reason="stop"
                    )
                ],
                usage=ChatCompletionUsage(
                    prompt_tokens=len(query.split()),
                    completion_tokens=len(result["result"].split()),
                    total_tokens=len(query.split()) + len(result["result"].split())
                )
            )
            
            logger.info("Query processed successfully", 
                       sources=len(result.get("source_documents", [])))
            
            return response
            
        except RAGChainError as e:
            logger.error("RAG chain error", error=str(e))
            raise QueryServiceError(f"RAG processing failed: {str(e)}") from e
        
        except Exception as e:
            logger.error("Unexpected error", error=str(e))
            raise QueryServiceError("Internal processing error") from e
