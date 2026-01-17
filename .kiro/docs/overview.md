# Overview

## Purpose

ArchonAgent is a Python-based RAG (Retrieval-Augmented Generation) system that monitors GitHub repositories for documentation changes and provides intelligent query capabilities. It consists of monitoring, ingestion, storage, and query components that work together to maintain an up-to-date knowledge base of system documentation.

## Archon Integration

This repository is ingested by the **Archon** RAG system, which reads all Markdown files under `.kiro/docs/` to build mental models for sourcing code and architectural information.

Documentation in this repository follows the Archon documentation contract defined in `CLAUDE.md` at the repo root.

## Key Components

- **Monitor Module** (`archon/monitor/`) - GitHub repository monitoring and workflow tracking
- **Ingestion Module** (`archon/ingestion/`) - Document processing and embedding pipeline  
- **Storage Module** (`archon/storage/`) - Vector database and change tracking
- **Query Module** (`archon/query/`) - RAG-based query processing and API server
- **Common Module** (`archon/common/`) - Shared configuration and utilities

## Deployment

The service is designed to run in Kubernetes with:
- Containerized Python services (Docker configurations in `docker/`)
- Kubernetes manifests for deployment (`manifests/`)
- Tekton pipeline integration (`aphex-pipeline/`)

## Related Repositories

- **AphexPlatformInfrastructure** - Platform infrastructure and GitOps configuration
- **AphexCLI** - Command-line tool for pipeline and organization management

**Source**
- `archon/` directory structure
- `docker/` containerization configs  
- `manifests/` Kubernetes deployment specs
- `aphex-pipeline/pipeline.yaml`
