"""
Property-based tests for configuration parsing.

Feature: archon-rag-system, Property 1: Configuration parsing completeness
Validates: Requirements 1.1
"""

import tempfile
import os
from hypothesis import given, strategies as st
import yaml
import sys


from config.config_manager import ConfigManager, ConfigValidationError


# Strategies for generating valid configuration components
@st.composite
def valid_github_url(draw):
    """Generate valid GitHub repository URLs."""
    # GitHub org/user names: alphanumeric, hyphens (no leading/trailing hyphens)
    org = draw(st.from_regex(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$', fullmatch=True))
    # GitHub repo names: alphanumeric, hyphens, underscores, dots
    repo = draw(st.from_regex(r'^[a-zA-Z0-9._-]{1,100}$', fullmatch=True))
    return f"https://github.com/{org}/{repo}"


@st.composite
def valid_repository_config(draw):
    """Generate valid repository configuration."""
    url = draw(valid_github_url())
    branch = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='_-./'),
        min_size=1,
        max_size=50
    ))
    paths = draw(st.lists(
        st.text(min_size=1, max_size=100),
        min_size=1,
        max_size=5
    ))
    return {
        'url': url,
        'branch': branch,
        'paths': paths
    }


@st.composite
def valid_config_dict(draw):
    """Generate valid configuration dictionary."""
    repositories = draw(st.lists(valid_repository_config(), min_size=1, max_size=10))
    
    return {
        'version': '1.0',
        'repositories': repositories,
        'infrastructure': {
            'cron_schedule': draw(st.sampled_from(['rate(1 hour)', 'rate(30 minutes)', 'cron(0 */6 * * ? *)'])),
            'lambda_memory': draw(st.integers(min_value=128, max_value=10240)),
            'lambda_timeout': draw(st.integers(min_value=1, max_value=900)),
            'vector_db_dimensions': draw(st.integers(min_value=1, max_value=4096))
        },
        'models': {
            'embedding_model': 'amazon.titan-embed-text-v1',
            'llm_model': 'anthropic.claude-3-haiku-20240307',
            'llm_temperature': draw(st.floats(min_value=0.0, max_value=1.0)),
            'max_tokens': draw(st.integers(min_value=1, max_value=4096)),
            'retrieval_k': draw(st.integers(min_value=1, max_value=20))
        }
    }


# Feature: archon-rag-system, Property 1: Configuration parsing completeness
@given(valid_config_dict())
def test_configuration_parsing_completeness(config_dict):
    """
    For any valid YAML/JSON configuration file, parsing should successfully 
    extract all repository configurations with their URLs, branches, and paths.
    
    Validates: Requirements 1.1
    """
    # Create temporary YAML file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_dict, f)
        temp_path = f.name
    
    try:
        # Load configuration
        manager = ConfigManager()
        config = manager.load_config(temp_path)
        
        # Property: All repositories should be parsed with complete information
        assert len(config.repositories) == len(config_dict['repositories'])
        
        for i, repo in enumerate(config.repositories):
            expected_repo = config_dict['repositories'][i]
            
            # Each repository must have URL, branch, and paths
            assert repo.url == expected_repo['url']
            assert repo.branch == expected_repo['branch']
            assert repo.paths == expected_repo['paths']
        
        # Infrastructure config should be complete
        assert config.infrastructure.cron_schedule == config_dict['infrastructure']['cron_schedule']
        assert config.infrastructure.lambda_memory == config_dict['infrastructure']['lambda_memory']
        assert config.infrastructure.lambda_timeout == config_dict['infrastructure']['lambda_timeout']
        assert config.infrastructure.vector_db_dimensions == config_dict['infrastructure']['vector_db_dimensions']
        
        # Model config should be complete
        assert config.models.embedding_model == config_dict['models']['embedding_model']
        assert config.models.llm_model == config_dict['models']['llm_model']
        assert config.models.llm_temperature == config_dict['models']['llm_temperature']
        assert config.models.max_tokens == config_dict['models']['max_tokens']
        assert config.models.retrieval_k == config_dict['models']['retrieval_k']
        
    finally:
        # Clean up temporary file
        os.unlink(temp_path)


@given(st.lists(valid_repository_config(), min_size=1, max_size=5))
def test_multiple_repositories_parsed_independently(repo_configs):
    """
    For any list of repository configurations, each should be parsed 
    independently with all its properties intact.
    
    Validates: Requirements 1.1
    """
    config_dict = {
        'version': '1.0',
        'repositories': repo_configs,
        'infrastructure': {
            'cron_schedule': 'rate(1 hour)',
            'lambda_memory': 1024,
            'lambda_timeout': 300,
            'vector_db_dimensions': 1536
        },
        'models': {
            'embedding_model': 'amazon.titan-embed-text-v1',
            'llm_model': 'anthropic.claude-3-haiku-20240307',
            'llm_temperature': 0.7,
            'max_tokens': 2048,
            'retrieval_k': 5
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_dict, f)
        temp_path = f.name
    
    try:
        manager = ConfigManager()
        config = manager.load_config(temp_path)
        
        # Property: Number of parsed repositories equals input
        assert len(config.repositories) == len(repo_configs)
        
        # Property: Each repository maintains its distinct configuration
        for i, repo in enumerate(config.repositories):
            assert repo.url == repo_configs[i]['url']
            assert repo.branch == repo_configs[i]['branch']
            assert repo.paths == repo_configs[i]['paths']
            
    finally:
        os.unlink(temp_path)
