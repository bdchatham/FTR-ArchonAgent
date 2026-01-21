"""Tests for Pydantic models."""

import pytest
from archon.query.models import (
    ChatMessage,
    ChatCompletionRequest,
    ChatCompletionChoice,
    ChatCompletionUsage,
    ChatCompletionResponse,
    HealthResponse,
    ReadinessResponse,
)


class TestChatMessage:
    """Tests for ChatMessage model."""

    def test_create_chat_message(self):
        """Test creating a chat message."""
        msg = ChatMessage(role="user", content="Hello")
        
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_chat_message_serialization(self):
        """Test chat message serializes to dict."""
        msg = ChatMessage(role="assistant", content="Hi there!")
        
        data = msg.model_dump()
        
        assert data == {"role": "assistant", "content": "Hi there!"}


class TestChatCompletionRequest:
    """Tests for ChatCompletionRequest model."""

    def test_create_request_with_defaults(self):
        """Test creating request with default values."""
        messages = [ChatMessage(role="user", content="Test")]
        request = ChatCompletionRequest(messages=messages)
        
        assert request.model == "archon"
        assert request.temperature == 0.7
        assert request.max_tokens == 2048
        assert len(request.messages) == 1

    def test_create_request_with_custom_values(self):
        """Test creating request with custom values."""
        messages = [ChatMessage(role="user", content="Test")]
        request = ChatCompletionRequest(
            messages=messages,
            model="custom-model",
            temperature=0.5,
            max_tokens=1024,
        )
        
        assert request.model == "custom-model"
        assert request.temperature == 0.5
        assert request.max_tokens == 1024


class TestChatCompletionResponse:
    """Tests for ChatCompletionResponse model."""

    def test_create_response(self):
        """Test creating a complete response."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatMessage(role="assistant", content="Response"),
            finish_reason="stop",
        )
        usage = ChatCompletionUsage(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )
        response = ChatCompletionResponse(
            id="test-id",
            created=1234567890,
            model="archon",
            choices=[choice],
            usage=usage,
        )
        
        assert response.id == "test-id"
        assert response.object == "chat.completion"
        assert len(response.choices) == 1
        assert response.usage.total_tokens == 30


class TestHealthResponse:
    """Tests for HealthResponse model."""

    def test_create_health_response(self):
        """Test creating health response."""
        response = HealthResponse(
            status="healthy",
            vector_db="connected",
            timestamp=1234567890,
        )
        
        assert response.status == "healthy"
        assert response.vector_db == "connected"


class TestReadinessResponse:
    """Tests for ReadinessResponse model."""

    def test_create_readiness_response(self):
        """Test creating readiness response."""
        response = ReadinessResponse(status="ready", timestamp=1234567890)
        
        assert response.status == "ready"
        assert response.timestamp == 1234567890
