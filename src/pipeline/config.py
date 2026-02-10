"""Pipeline configuration using pydantic-settings.

This module defines the PipelineSettings class that reads configuration
from environment variables with the PIPELINE_ prefix. All required fields
must be set via environment variables for the pipeline to start.

Requirements:
- 10.1: Read configuration from environment variables
- 10.2: GitHub webhook secret, GitHub API token, workspace base path,
        kiro-cli path, timeouts, retention periods
- 10.3: LLM endpoint URL, model name
- 10.4: Reference a KnowledgeBase resource by namespace and name
"""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    """Agent pipeline configuration from environment variables.

    All environment variables are prefixed with PIPELINE_ (e.g., PIPELINE_GITHUB_TOKEN).

    Required fields (must be set via environment variables):
    - github_webhook_secret: Secret for validating GitHub webhook signatures
    - github_token: GitHub API token for creating comments, PRs, etc.
    - llm_url: URL of the LLM endpoint for issue classification
    - database_url: PostgreSQL connection string for state persistence
    """

    model_config = SettingsConfigDict(
        env_prefix="PIPELINE_",
        case_sensitive=False,
    )

    # -------------------------------------------------------------------------
    # GitHub Configuration
    # -------------------------------------------------------------------------
    # Secret for validating GitHub webhook signatures (Requirement 10.2)
    github_webhook_secret: str

    # GitHub API token for creating comments, PRs, labels (Requirement 10.2)
    github_token: str

    # Base URL for GitHub API (supports GitHub Enterprise)
    github_base_url: str = "https://api.github.com"

    # -------------------------------------------------------------------------
    # Workspace Configuration
    # -------------------------------------------------------------------------
    # Base path for creating workspace directories (Requirement 10.2)
    workspace_base_path: str = "/var/lib/archon/workspaces"

    # Number of days to retain workspaces before cleanup (Requirement 10.2)
    workspace_retention_days: int = 7

    # -------------------------------------------------------------------------
    # Kiro CLI Configuration
    # -------------------------------------------------------------------------
    # Path to the kiro-cli executable (Requirement 10.2)
    kiro_cli_path: str = "/usr/local/bin/kiro-cli"

    # Timeout in seconds for kiro-cli execution (Requirement 10.2)
    kiro_timeout_seconds: int = 3600

    # -------------------------------------------------------------------------
    # LLM Configuration
    # -------------------------------------------------------------------------
    # URL of the LLM endpoint for issue classification (Requirement 10.3)
    llm_url: str

    # Model name for LLM inference (Requirement 10.3)
    llm_model: str = "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4"

    # -------------------------------------------------------------------------
    # Knowledge Base Configuration
    # -------------------------------------------------------------------------
    # Kubernetes namespace of the KnowledgeBase resource (Requirement 10.4)
    knowledge_base_namespace: str = "archon-system"

    # Name of the KnowledgeBase resource (Requirement 10.4)
    knowledge_base_name: str = "archon-workspace"

    # -------------------------------------------------------------------------
    # Database Configuration
    # -------------------------------------------------------------------------
    # PostgreSQL connection string for state persistence
    database_url: str

    # -------------------------------------------------------------------------
    # Server Configuration
    # -------------------------------------------------------------------------
    # Host address to bind the server to
    host: str = "0.0.0.0"

    # Port number for the server
    port: int = 8080

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("github_webhook_secret")
    @classmethod
    def validate_webhook_secret(cls, v: str) -> str:
        """Validate that webhook secret is not empty."""
        if not v or not v.strip():
            raise ValueError("github_webhook_secret cannot be empty")
        return v

    @field_validator("github_token")
    @classmethod
    def validate_github_token(cls, v: str) -> str:
        """Validate that GitHub token is not empty."""
        if not v or not v.strip():
            raise ValueError("github_token cannot be empty")
        return v

    @field_validator("llm_url")
    @classmethod
    def validate_llm_url(cls, v: str) -> str:
        """Validate that LLM URL is a valid URL format."""
        if not v or not v.strip():
            raise ValueError("llm_url cannot be empty")
        if not v.startswith(("http://", "https://")):
            raise ValueError("llm_url must start with http:// or https://")
        return v

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Validate that database URL is not empty and has valid format."""
        if not v or not v.strip():
            raise ValueError("database_url cannot be empty")
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                "database_url must start with postgresql:// or postgres://"
            )
        return v

    @field_validator("workspace_base_path")
    @classmethod
    def validate_workspace_path(cls, v: str) -> str:
        """Validate that workspace base path is an absolute path."""
        path = Path(v)
        if not path.is_absolute():
            raise ValueError("workspace_base_path must be an absolute path")
        return v

    @field_validator("workspace_retention_days")
    @classmethod
    def validate_retention_days(cls, v: int) -> int:
        """Validate that retention days is positive."""
        if v < 1:
            raise ValueError("workspace_retention_days must be at least 1")
        return v

    @field_validator("kiro_timeout_seconds")
    @classmethod
    def validate_kiro_timeout(cls, v: int) -> int:
        """Validate that kiro timeout is positive."""
        if v < 1:
            raise ValueError("kiro_timeout_seconds must be at least 1")
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate that port is in valid range."""
        if not 1 <= v <= 65535:
            raise ValueError("port must be between 1 and 65535")
        return v


def get_settings() -> PipelineSettings:
    """Create and return PipelineSettings instance.

    This function creates a new PipelineSettings instance, which reads
    configuration from environment variables. It will raise a validation
    error if required fields are missing or invalid.

    Returns:
        PipelineSettings: Configured settings instance.

    Raises:
        pydantic.ValidationError: If required fields are missing or invalid.
    """
    return PipelineSettings()
