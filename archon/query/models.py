"""Pydantic models for query service API."""

from typing import List
from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = "archon"
    temperature: float = 0.7
    max_tokens: int = 2048


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: ChatCompletionUsage


class HealthResponse(BaseModel):
    status: str
    vector_db: str
    timestamp: int


class ReadinessResponse(BaseModel):
    status: str
    timestamp: int
