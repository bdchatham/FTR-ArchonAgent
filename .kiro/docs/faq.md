# FAQ

## General Questions

### What is this repository for?

ArchonAgent provides the inference layer for the Archon RAG system. It consists of two components:
- **RAG Orchestrator**: Transparent proxy that augments chat requests with context from the Knowledge Base
- **vLLM Model Server**: GPU-accelerated LLM inference using Qwen2.5-Coder-14B

Clients interact with a standard OpenAI `/v1/chat/completions` API and receive context-aware responses without knowing RAG is happening.

### How does this fit into the larger system?

ArchonAgent is the top of the inference stack:
- **ArchonKnowledgeBaseInfrastructure** provides the `/v1/retrieve` endpoint for context retrieval
- **AphexServiceClients** provides the `QueryClient` with retry logic
- **AphexPlatformInfrastructure** provides the GPU RuntimeClass and deployment infrastructure

The orchestrator retrieves context from the Knowledge Base, augments prompts, and forwards to vLLM for inference.

### Why are the orchestrator and model server separate?

The components are deliberately split into separate namespaces for:
- **Independent scaling**: Scale orchestrator for request volume, model server for inference throughput
- **Independent updates**: Update RAG logic without restarting expensive GPU workloads
- **Resource isolation**: Orchestrator failures don't affect model server availability
- **Cost optimization**: Run multiple lightweight orchestrators with different RAG strategies against one model server

See [architecture.md](architecture.md#component-separation) for detailed rationale.

### What model is used?

**Qwen2.5-Coder-14B-Instruct-GPTQ-Int4** - A 14B parameter code-optimized LLM quantized to 4-bit for efficient GPU usage.

**Why this model?**
- Code-optimized for technical documentation
- 4-bit quantization fits in 16-24Gi GPU memory
- Good balance of quality and resource requirements
- OpenAI-compatible API via vLLM

## Development Questions

### How do I set up my development environment?

**Prerequisites**:
- Python 3.11+
- Docker (for building images)
- kubectl with cluster access
- NVIDIA GPU (for vLLM)

**Local development**:
```bash
# Install orchestrator dependencies
pip install -r requirements-orchestrator.txt

# Run orchestrator locally (requires KB and vLLM running)
export KNOWLEDGE_BASE_URL="http://query.archon-knowledge-base.svc.cluster.local:8080"
export VLLM_URL="http://vllm.archon-model-server.svc.cluster.local:8000"
cd src/orchestrator
uvicorn main:app --reload --port 8080
```

### How do I run tests?

Currently no automated tests. Manual testing:
```bash
# Test health endpoints
curl http://localhost:8080/health
curl http://localhost:8080/ready

# Test chat completion
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 50}'
```

### How do I build and push container images?

```bash
# Build orchestrator image
docker build -f Dockerfile.orchestrator -t ghcr.io/bdchatham/archon-rag-orchestrator:latest .

# Push to registry
docker push ghcr.io/bdchatham/archon-rag-orchestrator:latest
```

The vLLM image is pulled directly from Docker Hub (`vllm/vllm-openai:v0.14.1-cu130`).

## Operational Questions

### How do I deploy changes?

**Via ArgoCD** (recommended):
1. Update manifests in Git
2. Commit and push to mainline
3. ArgoCD syncs automatically

**Via Tekton Pipeline**:
```bash
kubectl create -f pipeline/deploy-orchestrator.yaml
```

**Manual**:
```bash
kubectl apply -k manifests/orchestrator/
```

### What should I do if the orchestrator is not ready?

**Symptoms**: `/ready` returns 503

**Diagnosis**:
```bash
curl http://localhost:8080/ready
kubectl logs -n archon-orchestrator -l app=archon-rag
```

**Common causes**:
- vLLM not ready (GPU loading) - wait 15-30 minutes for first startup
- KB unavailable - orchestrator will work in degraded mode (no RAG)

**Resolution**: Check vLLM status: `kubectl get pods -n archon-model-server -l app=vllm`

### What should I do if responses don't include context?

**Symptoms**: Responses don't reference documentation

**Diagnosis**:
```bash
# Check orchestrator logs for retrieval
kubectl logs -n archon-orchestrator -l app=archon-rag | grep -i retriev

# Check KB health
kubectl get pods -n archon-knowledge-base
```

**Common causes**:
- KB service unavailable
- Similarity threshold too high
- No relevant documents in KB

**Resolution**:
1. Verify KB is running: `kubectl get pods -n archon-knowledge-base`
2. Lower `RAG_SIMILARITY_THRESHOLD` in configmap (default: 0.5)
3. Verify documents are ingested in KB

### How do I disable RAG temporarily?

Set `RAG_ENABLED=false` in orchestrator configmap:
```bash
kubectl patch configmap archon-rag-config -n archon-orchestrator \
  --type merge -p '{"data":{"RAG_ENABLED":"false"}}'
kubectl rollout restart deployment/archon-rag -n archon-orchestrator
```

Or bypass the orchestrator entirely by calling vLLM directly at `http://vllm.home.local`.

### How do I scale the orchestrator?

The orchestrator is stateless and can scale horizontally:
```bash
kubectl scale deployment/archon-rag -n archon-orchestrator --replicas=3
```

vLLM is single-replica per GPU. For more throughput, add GPU nodes.

### What if vLLM runs out of memory?

**Symptoms**: vLLM pod crashes with OOM

**Resolution**:
1. Reduce `gpu_memory_utilization` in vLLM configmap (default: 0.90)
2. Reduce `max_model_len` in vLLM configmap (default: 8192)
3. Consider a smaller model

## Archon-Specific Questions

### How is this repository ingested by Archon?

Archon reads all Markdown files under `.kiro/docs/` from this public GitHub repository. The documentation in this repository becomes part of the Knowledge Base that the RAG orchestrator retrieves from.

**Self-referential**: This repository documents itself, and that documentation is ingested by Archon, which uses it to answer questions about itself.

### How do I update documentation?

Update the relevant files under `.kiro/docs/` and ensure changes are grounded in code. Include "Source" references to relevant files.

**Documentation structure**:
- `overview.md` - High-level purpose and context
- `architecture.md` - System design and components
- `operations.md` - Deployment and troubleshooting
- `api.md` - API contracts and interfaces
- `data-models.md` - Configuration and data structures
- `faq.md` - Common questions (this file)

### How does graceful degradation work?

The orchestrator degrades gracefully when dependencies are unavailable:

| Scenario | Behavior |
|----------|----------|
| KB unreachable | Forward to vLLM without augmentation |
| KB timeout (>10s) | Forward to vLLM without augmentation (after retries) |
| KB returns empty | Forward to vLLM without augmentation |
| vLLM unreachable | Return 503 Service Unavailable |

The `QueryClient` from `aphex-service-clients` provides automatic retry with exponential backoff on transient failures.

### What are the key configuration parameters?

**RAG Configuration** (orchestrator):
- `RAG_ENABLED`: Enable/disable RAG (default: true)
- `RAG_CONTEXT_CHUNKS`: Number of chunks to retrieve (default: 5)
- `RAG_SIMILARITY_THRESHOLD`: Minimum similarity score (default: 0.5)
- `RAG_RETRIEVAL_TIMEOUT`: KB timeout in seconds (default: 10.0)

**vLLM Configuration**:
- `gpu_memory_utilization`: VRAM usage fraction (default: 0.90)
- `max_model_len`: Maximum context length (default: 8192)
- `quantization`: Quantization method (default: gptq_marlin)

See [data-models.md](data-models.md) for complete configuration reference.

**Source**
- `CLAUDE.md` - Documentation contract
- `.kiro/steering/archon-docs.md` - Documentation standards
- `src/orchestrator/` - Orchestrator implementation
- `manifests/` - Kubernetes manifests
