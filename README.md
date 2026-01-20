# Archon Agent

RAG-powered knowledge base system for querying documentation across repositories.

## Architecture

Archon consists of two main components:

1. **Model Server** (`manifests/model-server/`) - GPU-accelerated vLLM inference
2. **Knowledge Base** (`manifests/knowledge-base/`) - RAG query and ingestion services

```
┌─────────────────────────────────────────────────────────────┐
│                     archon-system namespace                  │
│  ┌─────────────┐                                            │
│  │    vLLM     │◄── GPU inference (embeddings + LLM)        │
│  │  :8000      │                                            │
│  └─────────────┘                                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     archon-kb namespace                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Query     │    │   Monitor   │    │   Qdrant    │     │
│  │  Service    │    │  (CronJob)  │    │  (Vector)   │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

## Deployment

### Prerequisites

- Kubernetes cluster with GPU support
- NVIDIA RuntimeClass deployed (`nvidia`)
- ArgoCD installed
- Tekton Pipelines installed

### Pipeline Execution Order

**Important**: Deploy in this exact order.

```bash
# 1. Deploy model server (GPU infrastructure)
kubectl create -f pipeline/deploy-model-server.yaml -n archon-agent

# 2. Wait for vLLM to be ready (15-30 min on first run)
kubectl get pods -n archon-system -w

# 3. Deploy knowledge base components
kubectl create -f pipeline/deploy-pipeline.yaml -n archon-agent
```

### Verify Deployment

```bash
# Check model server
kubectl get pods -n archon-system
curl http://vllm.archon-system.svc.cluster.local:8000/health

# Check knowledge base
kubectl get pods -n archon-kb
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
| `manifests/configmap.yaml` | Archon service configuration |

## Development

See `CLAUDE.md` for code standards and contribution guidelines.
