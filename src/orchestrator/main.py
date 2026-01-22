"""FastAPI application for RAG Orchestrator."""

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from aphex_clients import QueryClient

from .config import settings
from .models import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatMessage,
    HealthResponse,
    ReadyResponse,
)
from .rag_chain import RAGChain

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

rag_chain: RAGChain


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global rag_chain
    rag_chain = RAGChain(settings)
    await rag_chain.initialize()
    logger.info(f"RAG Orchestrator started (RAG enabled: {settings.rag_enabled})")
    logger.info(f"Knowledge Base URL: {settings.knowledge_base_url}")
    logger.info(f"vLLM URL: {settings.vllm_url}")
    logger.info(f"Model: {settings.model_name}")
    yield
    await rag_chain.close()
    logger.info("RAG Orchestrator shutdown")


app = FastAPI(
    title="Archon RAG Orchestrator",
    description="OpenAI-compatible chat completions with transparent RAG augmentation",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health():
    """Liveness check endpoint."""
    return HealthResponse(status="healthy")


@app.get("/ready", response_model=ReadyResponse)
async def ready():
    """Readiness check endpoint."""
    kb_status = "healthy"
    vllm_status = "healthy"

    async with QueryClient(base_url=settings.knowledge_base_url, timeout=2.0) as client:
        if not await client.health_check():
            kb_status = "unavailable"

    # vLLM health check via LangChain would require a test call
    # For now, assume healthy if we got this far

    if vllm_status != "healthy":
        raise HTTPException(status_code=503, detail=f"vLLM unavailable: {vllm_status}")

    status = "ready" if kb_status == "healthy" else "degraded"

    return ReadyResponse(
        status=status,
        knowledge_base=kb_status,
        vllm=vllm_status,
        rag_enabled=settings.rag_enabled and kb_status == "healthy",
    )


async def stream_sse_response(
    request: ChatCompletionRequest,
    augmented_messages: list[ChatMessage],
    request_id: str,
) -> AsyncGenerator[bytes, None]:
    """Stream response as Server-Sent Events."""
    response_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())
    
    async for token in rag_chain.stream_response(augmented_messages):
        chunk = {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": request.model,
            "choices": [{
                "index": 0,
                "delta": {"content": token},
                "finish_reason": None,
            }],
        }
        yield f"data: {json.dumps(chunk)}\n\n".encode()
    
    final_chunk = {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": request.model,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
    }
    yield f"data: {json.dumps(final_chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions with transparent RAG."""
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    logger.info(f"[{request_id}] Received chat completion request")

    rag_start = time.time()
    try:
        augmented_messages = await rag_chain.process_messages(request.messages)
        rag_latency = time.time() - rag_start
        logger.info(f"[{request_id}] RAG processing took {rag_latency:.2f}s")
    except Exception as e:
        logger.warning(f"[{request_id}] RAG processing failed, using original: {e}")
        augmented_messages = request.messages
        rag_latency = time.time() - rag_start

    if request.stream:
        logger.info(f"[{request_id}] Streaming response")
        return StreamingResponse(
            stream_sse_response(request, augmented_messages, request_id),
            media_type="text/event-stream",
        )

    try:
        llm_start = time.time()
        content = await rag_chain.generate_response(augmented_messages)
        llm_latency = time.time() - llm_start
        total_latency = time.time() - start_time

        logger.info(
            f"[{request_id}] Request completed in {total_latency:.2f}s "
            f"(RAG: {rag_latency:.2f}s, LLM: {llm_latency:.2f}s)"
        )

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            ),
        )

    except Exception as e:
        logger.error(f"[{request_id}] LLM call failed: {e}")
        raise HTTPException(status_code=503, detail="LLM service unavailable")


@app.get("/v1/models")
async def list_models():
    """List available models."""
    return {
        "object": "list",
        "data": [
            {
                "id": settings.model_name,
                "object": "model",
                "owned_by": "archon",
            }
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
