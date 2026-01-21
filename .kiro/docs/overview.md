# Overview

## Purpose

ArchonAgent is a GPU-accelerated vLLM model server that provides OpenAI-compatible LLM inference for the Archon RAG system. It serves as the compute backbone for generating responses to user queries using the Qwen2.5-Coder-14B-Instruct model.

The Agent focuses purely on LLM inference. Embedding generation is handled by the Knowledge Base (ArchonKnowledgeBaseInfrastructure), which has its own self-contained Embedding Service.

## Archon Integration

This repository is ingested by the **Archon** RAG system, which reads all Markdown files under `.kiro/docs/` to build mental models for sourcing code and architectural information.

Documentation in this repository follows the Archon documentation contract defined in `CLAUDE.md` at the repo root.

## Key Components

- **vLLM Model Server** - GPU-accelerated inference engine with OpenAI-compatible API
- **ConfigMap** - Externalized model configuration (model name, VRAM utilization, context length)
- **PersistentVolumeClaim** - Model cache storage to avoid re-downloading on restarts
- **Tekton Pipeline** - GitOps deployment via ArgoCD

## Deployment

The service runs in Kubernetes with:
- NVIDIA GPU access via `nvidia` RuntimeClass
- Kubernetes manifests in `manifests/model-server/`
- Tekton pipeline in `pipeline/`
- ArgoCD Application for GitOps sync

## Related Repositories

- **ArchonKnowledgeBaseInfrastructure** - RAG knowledge base with vector storage and embedding service
- **AphexPlatformInfrastructure** - Platform infrastructure including GPU RuntimeClass
- **AphexPipelineResources** - Reusable Tekton tasks including `argocd-deployment`

**Source**
- `manifests/model-server/` - Kubernetes deployment manifests
- `pipeline/` - Tekton pipeline definitions
- `CLAUDE.md` - Documentation contract
