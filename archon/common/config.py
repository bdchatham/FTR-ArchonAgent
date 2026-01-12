"""Configuration loading utilities."""

import os
import json
from typing import Dict, Any
import structlog

logger = structlog.get_logger()


def load_config() -> Dict[str, Any]:
    """
    Load configuration from environment variables.
    
    Returns:
        Dictionary containing configuration values
    """
    config = {
        "vector_db_url": os.getenv("VECTOR_DB_URL", "http://qdrant:6333"),
        "tracker_db_url": os.getenv("TRACKER_DB_URL", "postgresql://archon:password@postgres:5432/archon"),
        "vllm_base_url": os.getenv("VLLM_BASE_URL", "http://vllm:8000"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
        "llm_model": os.getenv("LLM_MODEL", "microsoft/DialoGPT-medium"),
        "retrieval_k": os.getenv("RETRIEVAL_K", "5"),
        "max_tokens": os.getenv("MAX_TOKENS", "2048"),
        "temperature": os.getenv("TEMPERATURE", "0.7"),
        "chunk_size": os.getenv("CHUNK_SIZE", "1000"),
        "chunk_overlap": os.getenv("CHUNK_OVERLAP", "200"),
        "repositories": os.getenv("REPOSITORIES", "[]"),
        "github_token": os.getenv("GITHUB_TOKEN", ""),
    }
    
    # Parse repositories JSON
    try:
        config["repositories"] = json.loads(config["repositories"])
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse repositories JSON", error=str(e))
        config["repositories"] = []
    
    logger.info("Configuration loaded", 
                vector_db_url=config["vector_db_url"],
                vllm_base_url=config["vllm_base_url"],
                embedding_model=config["embedding_model"],
                repositories_count=len(config["repositories"]))
    
    return config
