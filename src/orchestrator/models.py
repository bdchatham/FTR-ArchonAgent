"""Pydantic models for RAG Orchestrator API."""

from typing import Optional
from pydantic import BaseModel


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


class HealthResponse(BaseModel):
    """Health check response."""
    status: str


class ReadyResponse(BaseModel):
    """Readiness check response."""
    status: str
    knowledge_base: str
    vllm: str
    rag_enabled: bool
