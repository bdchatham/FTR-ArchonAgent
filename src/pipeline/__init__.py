"""Agent orchestration pipeline for processing GitHub issues to pull requests.

This package implements Phase 3 of the Archon Agent Pipeline, providing:
- GitHub webhook handling and issue intake
- Pipeline state machine with PostgreSQL persistence
- LLM-based issue classification
- Two-layer knowledge retrieval (vector + code graph)
- Workspace provisioning for Kiro CLI execution
- Pull request creation and GitHub integration
"""
