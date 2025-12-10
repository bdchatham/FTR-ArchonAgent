"""
Property-based tests for GitHub URL validation.

Feature: archon-rag-system, Property 2: GitHub URL validation
Validates: Requirements 1.2
"""

import os
import sys
from hypothesis import given, strategies as st, assume


from config.config_manager import ConfigManager


# Strategies for generating URLs
@st.composite
def valid_github_url(draw):
    """Generate valid GitHub repository URLs."""
    # GitHub org/user names: alphanumeric, hyphens (no leading/trailing hyphens)
    org = draw(st.from_regex(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$', fullmatch=True))
    # GitHub repo names: alphanumeric, hyphens, underscores, dots
    repo = draw(st.from_regex(r'^[a-zA-Z0-9._-]{1,100}$', fullmatch=True))
    trailing_slash = draw(st.booleans())
    url = f"https://github.com/{org}/{repo}"
    if trailing_slash:
        url += "/"
    return url


@st.composite
def invalid_github_url(draw):
    """Generate invalid GitHub URLs."""
    choice = draw(st.integers(min_value=0, max_value=6))
    
    if choice == 0:
        # Wrong protocol
        return draw(st.sampled_from([
            "http://github.com/org/repo",
            "ftp://github.com/org/repo",
            "github.com/org/repo"
        ]))
    elif choice == 1:
        # Wrong domain
        return draw(st.sampled_from([
            "https://gitlab.com/org/repo",
            "https://bitbucket.org/org/repo",
            "https://github.io/org/repo"
        ]))
    elif choice == 2:
        # Missing parts
        return draw(st.sampled_from([
            "https://github.com/",
            "https://github.com/org",
            "https://github.com/org/"
        ]))
    elif choice == 3:
        # Too many parts
        return "https://github.com/org/repo/extra/parts"
    elif choice == 4:
        # Invalid characters in org/repo
        org = draw(st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='@#$%'),
            min_size=1,
            max_size=10
        ))
        assume('@' in org or '#' in org or '$' in org or '%' in org)
        return f"https://github.com/{org}/repo"
    elif choice == 5:
        # Empty string or None-like
        return draw(st.sampled_from(["", "   ", "null"]))
    else:
        # Random invalid URL
        return draw(st.text(max_size=100))


# Feature: archon-rag-system, Property 2: GitHub URL validation
@given(valid_github_url())
def test_valid_github_urls_accepted(url):
    """
    For any valid GitHub repository URL, the validator should return True.
    
    Validates: Requirements 1.2
    """
    # Property: All valid GitHub URLs should be accepted
    assert ConfigManager.validate_github_url(url) is True


@given(invalid_github_url())
def test_invalid_github_urls_rejected(url):
    """
    For any invalid URL string, the validator should return False.
    
    Validates: Requirements 1.2
    """
    # Property: All invalid URLs should be rejected
    assert ConfigManager.validate_github_url(url) is False


@given(st.text())
def test_url_validation_correctness(url_string):
    """
    For any string input, the URL validator should correctly identify 
    valid GitHub repository URLs and reject invalid formats.
    
    Validates: Requirements 1.2
    """
    result = ConfigManager.validate_github_url(url_string)
    
    # Property: If accepted, must match GitHub URL format
    if result:
        # Must start with https://github.com/
        assert url_string.rstrip('/').startswith("https://github.com/")
        
        # Must have at least org and repo parts
        parts = url_string.rstrip('/').split('/')
        assert len(parts) >= 5  # ['https:', '', 'github.com', 'org', 'repo']
        
        # Org and repo parts should not be empty
        assert parts[3]  # org
        assert parts[4]  # repo
    else:
        # If rejected, should not be a valid GitHub URL format
        # (either wrong format, missing parts, or invalid characters)
        pass


@given(st.none() | st.integers() | st.floats() | st.booleans())
def test_non_string_inputs_rejected(non_string_input):
    """
    For any non-string input, the validator should return False.
    
    Validates: Requirements 1.2
    """
    # Property: Non-string inputs should always be rejected
    assert ConfigManager.validate_github_url(non_string_input) is False


@given(valid_github_url())
def test_trailing_slash_normalization(url):
    """
    For any valid GitHub URL, the validator should accept it with or 
    without a trailing slash.
    
    Validates: Requirements 1.2
    """
    url_without_slash = url.rstrip('/')
    url_with_slash = url_without_slash + '/'
    
    # Property: Both forms should be valid
    assert ConfigManager.validate_github_url(url_without_slash) is True
    assert ConfigManager.validate_github_url(url_with_slash) is True
