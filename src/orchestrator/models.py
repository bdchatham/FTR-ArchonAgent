"""Pydantic models for RAG Orchestrator."""

from typing import Optional
from pydantic import BaseModel


# OpenAI-compatible chat completion models

class ChatMessage(BaseModel):
    """A single message in a chat conversation."""
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""
    model: str
    messages: list[ChatMessage]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    stream: Optional[bool] = False
    stop: Optional[str | list[str]] = None


class ChatCompletionChoice(BaseModel):
    """A single completion choice."""
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


class ChatCompletionUsage(BaseModel):
    """Token usage statistics."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: Optional[ChatCompletionUsage] = None


# Knowledge Base retrieval models

class RetrievalRequest(BaseModel):
    """Request to Knowledge Base /v1/retrieve endpoint."""
    query: str
    k: int = 5


class RetrievalChunk(BaseModel):
    """A retrieved document chunk."""
    content: str
    source: str
    chunk_index: Optional[int] = None
    score: float


class RetrievalResponse(BaseModel):
    """Response from Knowledge Base /v1/retrieve endpoint."""
    chunks: list[RetrievalChunk]
    query: str


# Health check models

class HealthResponse(BaseModel):
    """Health check response."""
    status: str


class ReadyResponse(BaseModel):
    """Readiness check response."""
    status: str
    knowledge_base: str
    vllm: str
    rag_enabled: bool
