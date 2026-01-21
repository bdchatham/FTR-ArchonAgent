# Archon Agent

GPU-accelerated vLLM model server providing embeddings and inference for the Archon RAG system.

## Architecture

Archon is split into two separate deployments:

1. **Agent (this repo)** - vLLM model server for embeddings and inference
2. **Knowledge Base** ([ArchonKnowledgeBaseInfrastructure](https://github.com/bdchatham/ArchonKnowledgeBaseInfrastructure)) - RAG query and ingestion services

```
┌─────────────────────────────────────────────────────────────┐
│                     archon-system namespace                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                    vLLM Model Server                    ││
│  │                                                         ││
│  │  • /v1/embeddings - Vector embeddings (BGE)            ││
│  │  • /v1/completions - Text generation (Qwen)            ││
│  │  • /v1/chat/completions - Chat interface               ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ embeddings + inference
                              │
┌─────────────────────────────────────────────────────────────┐
│                archon-knowledge-base namespace               │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Query     │    │   Monitor   │    │   Qdrant    │     │
│  │  Service    │    │  (CronJob)  │    │  (Vector)   │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                                                             │
│  (Deployed from ArchonKnowledgeBaseInfrastructure repo)     │
└─────────────────────────────────────────────────────────────┘
```

## Deployment

### Prerequisites

- Kubernetes cluster with GPU support
- NVIDIA RuntimeClass deployed (`nvidia`)
- ArgoCD installed
- Tekton Pipelines installed

### Deploy Model Server

```bash
# Deploy model server (GPU infrastructure)
kubectl create -f - <<EOF
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  generateName: deploy-model-server-
  namespace: pipeline-system
spec:
  pipelineRef:
    name: deploy-model-server
EOF

# Wait for vLLM to be ready (15-30 min on first run)
kubectl get pods -n archon-system -w
```

### Verify Deployment

```bash
# Check model server
kubectl get pods -n archon-system
curl http://vllm.archon-system.svc.cluster.local:8000/health
```

## GPU Troubleshooting

### RuntimeClass not found
```bash
# Verify RuntimeClass exists
kubectl get runtimeclass nvidia

# If missing, deploy from platform infrastructure
kubectl apply -f AphexPlatformInfrastructure/platform/gpu/runtime-class.yaml
```

### GPU not available
```bash
# Check NVIDIA device plugin
kubectl get pods -n kube-system | grep nvidia

# Check node GPU capacity
kubectl describe nodes | grep -A5 "Capacity:"
```

### Out of Memory (OOM)
Edit `manifests/model-server/configmap.yaml`:
- Reduce `gpu_memory_utilization` (e.g., 0.85)
- Reduce `max_model_len` (e.g., 4096)
- Switch to smaller model (7B instead of 14B)

### Model download slow/failing
- First startup downloads ~10GB of models
- Check network connectivity from pod
- Verify PVC has sufficient space (50Gi)

## Configuration

| File | Purpose |
|------|---------|
| `manifests/model-server/configmap.yaml` | vLLM model and GPU settings |

## Related Repositories

- [ArchonKnowledgeBaseInfrastructure](https://github.com/bdchatham/ArchonKnowledgeBaseInfrastructure) - Knowledge base deployment

## Development

See `CLAUDE.md` for code standards and contribution guidelines.
