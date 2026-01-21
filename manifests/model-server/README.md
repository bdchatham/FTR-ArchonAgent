# Model Server Infrastructure

GPU-accelerated vLLM model server for LLM inference.

## Overview

Kubernetes manifests for deploying vLLM as the inference backend for Archon. The model server provides OpenAI-compatible endpoints for LLM chat completions.

## Prerequisites

1. **NVIDIA RuntimeClass** must exist (from AphexPlatformInfrastructure)
2. **NVIDIA Device Plugin** deployed
3. **GPU available** on target node

Verify GPU setup:
```bash
kubectl get pods -n kube-system | grep nvidia
kubectl describe nodes | grep nvidia.com/gpu
kubectl get runtimeclass nvidia
```

## Deployment

### Via Pipeline (recommended)

```bash
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
```

### Via kubectl

```bash
kubectl apply -k manifests/model-server/
```

### Verify

```bash
kubectl get pods -n archon-system -l app=vllm -w
kubectl port-forward svc/vllm 8000:8000 -n archon-system &
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
```

## Model Configuration

Configured for NVIDIA RTX 5070 (16GB VRAM):

| Setting | Value | Description |
|---------|-------|-------------|
| llm_model | Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4 | Code-optimized LLM |
| gpu_memory_utilization | 0.90 | VRAM usage fraction |
| max_model_len | 8192 | Maximum context length |
| quantization | gptq | Quantization method |

### Alternative Models

For OOM errors or different hardware:

| Model | VRAM | Use Case |
|-------|------|----------|
| Qwen2.5-Coder-14B-GPTQ-Int4 | ~12GB | Default, best quality |
| Qwen2.5-Coder-7B-GPTQ-Int4 | ~6GB | Lower VRAM, faster |

## Troubleshooting

### Pod Pending

```bash
kubectl describe pod -n archon-system -l app=vllm
```

- "Insufficient nvidia.com/gpu": GPU not available
- "RuntimeClass not found": Deploy RuntimeClass first

### Pod CrashLoopBackOff

```bash
kubectl logs -n archon-system -l app=vllm --previous
```

- CUDA OOM: Reduce `gpu_memory_utilization` or `max_model_len`
- Download failed: Check network connectivity

### Slow Startup

First startup downloads models (15-30 min). Subsequent restarts use cache (~2 min).

## Files

| File | Purpose |
|------|---------|
| kustomization.yaml | Orchestrates all resources |
| namespace.yaml | archon-system namespace |
| resource-quota.yaml | GPU quota limits |
| limit-range.yaml | Default container limits |
| configmap.yaml | Model configuration |
| pvc.yaml | Model cache storage |
| deployment.yaml | vLLM deployment |
| service.yaml | ClusterIP service |
| ingress.yaml | External access |
