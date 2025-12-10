"""Configuration management for Archon RAG system."""

import re
from dataclasses import dataclass
from typing import List, Optional
import yaml


@dataclass
class RepositoryConfig:
    """Configuration for a GitHub repository to monitor."""
    url: str
    branch: str
    paths: List[str]


@dataclass
class InfrastructureConfig:
    """Infrastructure configuration parameters."""
    cron_schedule: str
    lambda_memory: int
    lambda_timeout: int
    vector_db_dimensions: int


@dataclass
class ModelConfig:
    """Model configuration parameters."""
    embedding_model: str
    llm_model: str
    llm_temperature: float
    max_tokens: int
    retrieval_k: int


@dataclass
class Config:
    """Complete system configuration."""
    version: str
    repositories: List[RepositoryConfig]
    infrastructure: InfrastructureConfig
    models: ModelConfig


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


class ConfigManager:
    """Manages loading and validation of YAML configuration files."""
    
    GITHUB_URL_PATTERN = re.compile(
        r'^https://github\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+/?$'
    )
    
    def __init__(self):
        """Initialize the ConfigManager."""
        self._config: Optional[Config] = None
    
    def load_config(self, config_path: str) -> Config:
        """
        Load configuration from a YAML file.
        
        Args:
            config_path: Path to the YAML configuration file
            
        Returns:
            Parsed and validated Config object
            
        Raises:
            ConfigValidationError: If configuration is invalid
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If YAML parsing fails
        """
        try:
            with open(config_path, 'r') as f:
                config_dict = yaml.safe_load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        except yaml.YAMLError as e:
            raise ConfigValidationError(f"Failed to parse YAML: {e}")
        
        if not config_dict:
            raise ConfigValidationError("Configuration file is empty")
        
        config = self._parse_config(config_dict)
        self.validate_config(config)
        self._config = config
        return config
    
    def _parse_config(self, config_dict: dict) -> Config:
        """
        Parse configuration dictionary into Config object.
        
        Args:
            config_dict: Dictionary from parsed YAML
            
        Returns:
            Config object
            
        Raises:
            ConfigValidationError: If required fields are missing
        """
        try:
            # Parse repositories
            repos_data = config_dict.get('repositories', [])
            repositories = [
                RepositoryConfig(
                    url=repo['url'],
                    branch=repo.get('branch', 'main'),
                    paths=repo.get('paths', ['.kiro/'])
                )
                for repo in repos_data
            ]
            
            # Parse infrastructure config
            infra_data = config_dict.get('infrastructure', {})
            infrastructure = InfrastructureConfig(
                cron_schedule=infra_data.get('cron_schedule', 'rate(1 hour)'),
                lambda_memory=infra_data.get('lambda_memory', 1024),
                lambda_timeout=infra_data.get('lambda_timeout', 300),
                vector_db_dimensions=infra_data.get('vector_db_dimensions', 1536)
            )
            
            # Parse model config
            models_data = config_dict.get('models', {})
            models = ModelConfig(
                embedding_model=models_data.get('embedding_model', 'amazon.titan-embed-text-v1'),
                llm_model=models_data.get('llm_model', 'anthropic.claude-3-haiku-20240307'),
                llm_temperature=models_data.get('llm_temperature', 0.7),
                max_tokens=models_data.get('max_tokens', 2048),
                retrieval_k=models_data.get('retrieval_k', 5)
            )
            
            return Config(
                version=config_dict.get('version', '1.0'),
                repositories=repositories,
                infrastructure=infrastructure,
                models=models
            )
        except KeyError as e:
            raise ConfigValidationError(f"Missing required configuration field: {e}")
        except (TypeError, ValueError) as e:
            raise ConfigValidationError(f"Invalid configuration value: {e}")
    
    def validate_config(self, config: Config) -> bool:
        """
        Validate configuration object.
        
        Args:
            config: Config object to validate
            
        Returns:
            True if valid
            
        Raises:
            ConfigValidationError: If validation fails
        """
        # Validate repositories
        if not config.repositories:
            raise ConfigValidationError("At least one repository must be configured")
        
        for repo in config.repositories:
            if not self.validate_github_url(repo.url):
                raise ConfigValidationError(f"Invalid GitHub URL: {repo.url}")
            
            if not repo.branch:
                raise ConfigValidationError(f"Branch cannot be empty for repository: {repo.url}")
            
            if not repo.paths:
                raise ConfigValidationError(f"At least one path must be specified for repository: {repo.url}")
        
        # Validate infrastructure
        if config.infrastructure.lambda_memory < 128:
            raise ConfigValidationError("Lambda memory must be at least 128 MB")
        
        if config.infrastructure.lambda_timeout < 1:
            raise ConfigValidationError("Lambda timeout must be at least 1 second")
        
        if config.infrastructure.vector_db_dimensions < 1:
            raise ConfigValidationError("Vector DB dimensions must be positive")
        
        # Validate models
        if config.models.llm_temperature < 0 or config.models.llm_temperature > 1:
            raise ConfigValidationError("LLM temperature must be between 0 and 1")
        
        if config.models.max_tokens < 1:
            raise ConfigValidationError("Max tokens must be positive")
        
        if config.models.retrieval_k < 1:
            raise ConfigValidationError("Retrieval k must be positive")
        
        return True
    
    @classmethod
    def validate_github_url(cls, url: str) -> bool:
        """
        Validate GitHub repository URL format.
        
        Args:
            url: URL string to validate
            
        Returns:
            True if valid GitHub URL, False otherwise
        """
        if not url or not isinstance(url, str):
            return False
        
        # Remove trailing slash for matching
        url_normalized = url.rstrip('/')
        
        return bool(cls.GITHUB_URL_PATTERN.match(url_normalized))
    
    def get_repositories(self) -> List[RepositoryConfig]:
        """
        Get list of configured repositories.
        
        Returns:
            List of RepositoryConfig objects
            
        Raises:
            RuntimeError: If config hasn't been loaded
        """
        if self._config is None:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")
        return self._config.repositories
    
    def get_infrastructure_params(self) -> InfrastructureConfig:
        """
        Get infrastructure configuration parameters.
        
        Returns:
            InfrastructureConfig object
            
        Raises:
            RuntimeError: If config hasn't been loaded
        """
        if self._config is None:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")
        return self._config.infrastructure
    
    def get_model_config(self) -> ModelConfig:
        """
        Get model configuration parameters.
        
        Returns:
            ModelConfig object
            
        Raises:
            RuntimeError: If config hasn't been loaded
        """
        if self._config is None:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")
        return self._config.models
