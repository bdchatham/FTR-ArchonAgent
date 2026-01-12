"""FastAPI server for Archon query service."""

import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import structlog
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from archon.query.service import QueryService, QueryServiceError
from archon.query.metrics import QueryMetrics
from archon.query.models import ChatCompletionRequest, ChatCompletionResponse, HealthResponse, ReadinessResponse
from archon.query.rag_chain import ArchonRAGChain
from archon.storage.vector_store import VectorStoreManager
from archon.common.config import load_config

logger = structlog.get_logger()

# Global components
query_service: Optional[QueryService] = None
vector_store_manager: Optional[VectorStoreManager] = None
metrics = QueryMetrics()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    global query_service, vector_store_manager
    
    logger.info("Starting Archon query service")
    
    # Load configuration
    config = load_config()
    
    # Initialize vector store manager
    vector_store_manager = VectorStoreManager(
        qdrant_url=config["vector_db_url"]
    )
    
    # Initialize RAG chain
    rag_chain = ArchonRAGChain(
        vector_store_manager=vector_store_manager,
        vllm_base_url=config["vllm_base_url"],
        llm_model=config["llm_model"],
        embedding_model=config["embedding_model"],
        temperature=float(config["temperature"]),
        max_tokens=int(config["max_tokens"]),
        retrieval_k=int(config["retrieval_k"])
    )
    
    # Initialize query service
    query_service = QueryService(rag_chain)
    
    logger.info("Archon query service initialized")
    yield
    
    logger.info("Shutting down Archon query service")


app = FastAPI(
    title="Archon Query Service",
    description="OpenAI-compatible RAG API for documentation retrieval",
    version="0.1.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completions endpoint."""
    start_time = time.time()
    
    try:
        response = await query_service.process_chat_completion(request)
        
        # Record success metrics
        duration = time.time() - start_time
        metrics.record_request_success(duration)
        
        return response
        
    except QueryServiceError as e:
        metrics.record_request_error()
        logger.error("Query service error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    
    except Exception as e:
        metrics.record_request_error()
        logger.error("Unexpected error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    try:
        vector_db_status = "connected" if vector_store_manager and vector_store_manager.is_healthy() else "disconnected"
        
        if vector_db_status == "disconnected":
            return Response(
                content='{"status": "unhealthy", "vector_db": "disconnected"}',
                status_code=503,
                media_type="application/json"
            )
        
        return HealthResponse(
            status="healthy",
            vector_db=vector_db_status,
            timestamp=int(time.time())
        )
    
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return Response(
            content=f'{{"status": "unhealthy", "error": "{str(e)}"}}',
            status_code=503,
            media_type="application/json"
        )


@app.get("/ready", response_model=ReadinessResponse)
async def readiness_check():
    """Readiness check endpoint."""
    try:
        if not query_service or not vector_store_manager:
            return Response(
                content='{"status": "not ready", "reason": "services not initialized"}',
                status_code=503,
                media_type="application/json"
            )
        
        return ReadinessResponse(
            status="ready",
            timestamp=int(time.time())
        )
    
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        return Response(
            content=f'{{"status": "not ready", "error": "{str(e)}"}}',
            status_code=503,
            media_type="application/json"
        )


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
