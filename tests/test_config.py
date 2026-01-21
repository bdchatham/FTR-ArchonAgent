"""Tests for configuration loading."""

import pytest
from archon.common.config import load_config


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_defaults(self):
        """Test that default values are loaded when env vars not set."""
        config = load_config()
        
        assert config["vector_db_url"] == "http://qdrant:6333"
        assert config["tracker_db_url"] == "postgresql://archon:password@postgres:5432/archon"
        assert config["vllm_base_url"] == "http://vllm:8000"
        assert config["retrieval_k"] == "5"
        assert config["repositories"] == []

    def test_load_config_from_env(self, sample_config_env):
        """Test that config loads from environment variables."""
        config = load_config()
        
        assert config["vector_db_url"] == "http://test-qdrant:6333"
        assert config["vllm_base_url"] == "http://test-vllm:8000"
        assert config["github_token"] == "test-token"

    def test_load_config_parses_repositories(self, sample_config_env):
        """Test that repositories JSON is parsed correctly."""
        config = load_config()
        
        assert config["repositories"] == ["org/repo1", "org/repo2"]
        assert len(config["repositories"]) == 2

    def test_load_config_invalid_repositories_json(self, monkeypatch):
        """Test that invalid repositories JSON defaults to empty list."""
        monkeypatch.setenv("REPOSITORIES", "not-valid-json")
        
        config = load_config()
        
        assert config["repositories"] == []
