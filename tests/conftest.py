"""Pytest configuration and shared fixtures."""

import os
import pytest


@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    """Reset environment variables before each test."""
    # Clear any existing config-related env vars
    env_vars = [
        "VECTOR_DB_URL",
        "TRACKER_DB_URL", 
        "VLLM_BASE_URL",
        "EMBEDDING_MODEL",
        "LLM_MODEL",
        "RETRIEVAL_K",
        "MAX_TOKENS",
        "TEMPERATURE",
        "CHUNK_SIZE",
        "CHUNK_OVERLAP",
        "REPOSITORIES",
        "GITHUB_TOKEN",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def sample_config_env(monkeypatch):
    """Set up sample configuration environment variables."""
    monkeypatch.setenv("VECTOR_DB_URL", "http://test-qdrant:6333")
    monkeypatch.setenv("VLLM_BASE_URL", "http://test-vllm:8000")
    monkeypatch.setenv("REPOSITORIES", '["org/repo1", "org/repo2"]')
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
