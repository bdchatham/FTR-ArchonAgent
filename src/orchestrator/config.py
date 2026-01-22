"""Configuration for RAG Orchestrator."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Orchestrator configuration from environment variables."""

    # Service URLs
    knowledge_base_url: str = "http://query.archon-knowledge-base.svc.cluster.local:8080"
    vllm_url: str = "http://vllm.archon-system.svc.cluster.local:8000"

    # Model settings
    model_name: str = "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4"

    # RAG settings
    rag_enabled: bool = True
    rag_context_chunks: int = 5
    rag_similarity_threshold: float = 0.5
    rag_retrieval_timeout: float = 10.0

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8080

    class Config:
        env_prefix = ""


settings = Settings()
