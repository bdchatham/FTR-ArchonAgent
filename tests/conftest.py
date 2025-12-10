"""Pytest configuration for all tests."""

import sys
import os

# Add lambda directory to Python path for all tests
lambda_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lambda'))
if lambda_dir not in sys.path:
    sys.path.insert(0, lambda_dir)
