# Overview

## Purpose

ArchonAgent provides the inference layer for the Archon RAG system through a unified Agent CRD:

1. **Model Server** - GPU-accelerated LLM inference using vLLM with Qwen2.5-Coder-14B
2. **Orchestrator** - Transparent RAG proxy that augments chat requests with context from the Knowledge Base

Clients interact with a standard OpenAI `/v1/chat/completions` API. The orchestrator automatically retrieves relevant context and augments prompts - clients receive better answers without knowing RAG is happening.

## Deployment Model

ArchonAgent uses a **declarative CRD-based approach**:

- **Agent CRD** (`manifests/agent.yaml`) - Declares desired agent configuration
- **Platform Controller** - Watches Agent CRD and provisions infrastructure
- **ArgoCD** - Syncs Agent CRD from Git to cluster
- **GitOps** - All configuration lives in Git

The platform controller automatically provisions:
- Model server deployment with GPU resources
- Orchestrator deployment (if `spec.orchestration` is set)
- Services, ConfigMaps, and networking
- Integration with KnowledgeBase for RAG

## Archon Integration

This repository is ingested by the **Archon** RAG system, which reads all Markdown files under `.kiro/docs/` to build mental models for sourcing code and architectural information.

Documentation in this repository follows the Archon documentation contract defined in `CLAUDE.md` at the repo root.

## Key Components

- **Agent CRD** (`manifests/agent.yaml`) - Declarative agent configuration
- **RAG Orchestrator** (`src/orchestrator/`) - FastAPI service using LangChain for RAG logic
- **Platform Controller** - Reconciles Agent CRD to provision infrastructure
- **Tekton Pipeline** (`pipeline/deploy-agent.yaml`) - GitOps deployment via ArgoCD

## Related Repositories

- **ArchonKnowledgeBaseInfrastructure** - RAG knowledge base with vector storage and embedding service
- **AphexPlatformInfrastructure** - Platform infrastructure including Agent CRD controller
- **AphexPipelineResources** - Reusable Tekton tasks including `argocd-deployment`

**Source**
- `manifests/agent.yaml` - Agent CRD manifest
- `src/orchestrator/` - RAG orchestrator Python code
- `pipeline/deploy-agent.yaml` - Deployment pipeline
- `CLAUDE.md` - Documentation contract
