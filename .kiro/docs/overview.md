# Overview

## Purpose

ArchonAgent provides the inference layer for the Archon RAG system:

1. **RAG Orchestrator** - Transparent proxy that augments chat requests with context from the Knowledge Base
2. **vLLM Model Server** - GPU-accelerated LLM inference using Qwen2.5-Coder-14B

Clients interact with a standard OpenAI `/v1/chat/completions` API. The orchestrator automatically retrieves relevant context and augments prompts - clients receive better answers without knowing RAG is happening.

## Archon Integration

This repository is ingested by the **Archon** RAG system, which reads all Markdown files under `.kiro/docs/` to build mental models for sourcing code and architectural information.

Documentation in this repository follows the Archon documentation contract defined in `CLAUDE.md` at the repo root.

## Key Components

- **RAG Orchestrator** (`src/orchestrator/`) - FastAPI service using LangChain for RAG logic
- **vLLM Model Server** - GPU-accelerated inference engine with OpenAI-compatible API
- **ConfigMap** - Externalized configuration for both services
- **Tekton Pipeline** - GitOps deployment via ArgoCD

The orchestrator and model server are deployed as separate components in different namespaces (`archon-orchestrator` and `archon-model-server`). This separation enables independent scaling, updates, and resource management.

## Deployment

The services run in Kubernetes with:
- RAG Orchestrator as a lightweight Python service
- vLLM with NVIDIA GPU access via `nvidia` RuntimeClass
- Kubernetes manifests in `manifests/orchestrator/` and `manifests/model-server/`
- ArgoCD Application for GitOps sync

## Related Repositories

- **ArchonKnowledgeBaseInfrastructure** - RAG knowledge base with vector storage and embedding service
- **AphexPlatformInfrastructure** - Platform infrastructure including GPU RuntimeClass
- **AphexPipelineResources** - Reusable Tekton tasks including `argocd-deployment`

**Source**
- `src/orchestrator/` - RAG orchestrator Python code
- `manifests/orchestrator/` - Orchestrator Kubernetes manifests
- `manifests/model-server/` - vLLM Kubernetes manifests
- `CLAUDE.md` - Documentation contract
