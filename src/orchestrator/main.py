"""FastAPI application for RAG Orchestrator."""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from .config import settings
from .models import (
    ChatCompletionRequest,
    ChatMessage,
    HealthResponse,
    ReadyResponse,
)
from .rag_chain import RAGChain

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global RAG chain instance
rag_chain: RAGChain


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global rag_chain
    rag_chain = RAGChain(settings)
    logger.info(f"RAG Orchestrator started (RAG enabled: {settings.rag_enabled})")
    logger.info(f"Knowledge Base URL: {settings.knowledge_base_url}")
    logger.info(f"vLLM URL: {settings.vllm_url}")
    yield
    await rag_chain.close()
    logger.info("RAG Orchestrator shutdown")


app = FastAPI(
    title="Archon RAG Orchestrator",
    description="Transparent RAG proxy for OpenAI-compatible chat completions",
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

    # Check Knowledge Base
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.knowledge_base_url}/health")
            if response.status_code != 200:
                kb_status = "unhealthy"
    except Exception:
        kb_status = "unavailable"

    # Check vLLM
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.vllm_url}/health")
            if response.status_code != 200:
                vllm_status = "unhealthy"
    except Exception:
        vllm_status = "unavailable"

    # vLLM must be healthy, KB can be degraded
    if vllm_status != "healthy":
        raise HTTPException(
            status_code=503,
            detail=f"vLLM unavailable: {vllm_status}",
        )

    status = "ready" if kb_status == "healthy" else "degraded"

    return ReadyResponse(
        status=status,
        knowledge_base=kb_status,
        vllm=vllm_status,
        rag_enabled=settings.rag_enabled and kb_status == "healthy",
    )


async def stream_vllm_response(
    request_data: dict,
    request_id: str,
) -> AsyncGenerator[bytes, None]:
    """Stream response from vLLM."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST",
            f"{settings.vllm_url}/v1/chat/completions",
            json=request_data,
        ) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                logger.error(
                    f"[{request_id}] vLLM error: {response.status_code} - {error_body}"
                )
                yield f"data: {error_body.decode()}\n\n".encode()
                return

            async for chunk in response.aiter_bytes():
                yield chunk


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, req: Request):
    """OpenAI-compatible chat completions endpoint with transparent RAG."""
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    logger.info(f"[{request_id}] Received chat completion request")

    # Process messages through RAG pipeline
    rag_start = time.time()
    try:
        augmented_messages = await rag_chain.process_messages(request.messages)
        rag_latency = time.time() - rag_start
        logger.info(f"[{request_id}] RAG processing took {rag_latency:.2f}s")
    except Exception as e:
        logger.warning(f"[{request_id}] RAG processing failed, using original: {e}")
        augmented_messages = request.messages
        rag_latency = time.time() - rag_start

    # Build request for vLLM
    vllm_request = {
        "model": request.model,
        "messages": [msg.model_dump() for msg in augmented_messages],
        "stream": request.stream,
    }

    # Add optional parameters
    if request.max_tokens is not None:
        vllm_request["max_tokens"] = request.max_tokens
    if request.temperature is not None:
        vllm_request["temperature"] = request.temperature
    if request.top_p is not None:
        vllm_request["top_p"] = request.top_p
    if request.stop is not None:
        vllm_request["stop"] = request.stop

    # Handle streaming
    if request.stream:
        logger.info(f"[{request_id}] Streaming response from vLLM")
        return StreamingResponse(
            stream_vllm_response(vllm_request, request_id),
            media_type="text/event-stream",
        )

    # Non-streaming request
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{settings.vllm_url}/v1/chat/completions",
                json=vllm_request,
            )

            total_latency = time.time() - start_time
            logger.info(
                f"[{request_id}] Request completed in {total_latency:.2f}s "
                f"(RAG: {rag_latency:.2f}s, vLLM: {total_latency - rag_latency:.2f}s)"
            )

            if response.status_code != 200:
                logger.error(
                    f"[{request_id}] vLLM error: {response.status_code} - {response.text}"
                )
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json() if response.text else "vLLM error",
                )

            return response.json()

    except httpx.HTTPError as e:
        logger.error(f"[{request_id}] vLLM connection error: {e}")
        raise HTTPException(
            status_code=503,
            detail="vLLM service unavailable",
        )


@app.get("/v1/models")
async def list_models():
    """Proxy /v1/models to vLLM."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.vllm_url}/v1/models")
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Failed to list models: {e}")
        raise HTTPException(status_code=503, detail="vLLM service unavailable")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
