"""Workspace provisioning for Kiro CLI execution.

This module creates filesystem workspaces containing:
- Cloned Git repositories for required packages
- context.md with issue details and knowledge context
- task.md with implementation task summary

Workspaces are cleaned up after a configurable retention period.
"""
