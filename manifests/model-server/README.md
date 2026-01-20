# Model Server Infrastructure

GPU-accelerated vLLM model server for the Archon knowledge base system.

## Overview

This directory contains Kubernetes manifests for deploying vLLM as the inference backend for Archon. The model server provides OpenAI-compatible endpoints for:
- Embedding generation (`/v1/embeddings`)
- LLM inference (`/v1/chat/completions`)

## Deployment Sequence

**Critical**: Deploy in this order to ensure dependencies are available.

1. **RuntimeClass** (platform infrastructure)
   - The `nvidia` RuntimeClass must exist before deploying the model server
   - Located in `AphexPlatformInfrastructure/platform/gpu/runtime-class.yaml`

2. **Model Server** (this directory)
   ```bash
   # Trigger the deploy-model-server pipeline
   kubectl create -f pipeline/deploy-model-server.yaml -n archon-agent
   ```

3. **Wait for vLLM to be ready**
   - First startup downloads models (~15-30 minutes)
   - Subsequent restarts use cached models (~2 minutes)
   ```bash
   kubectl get pods -n archon-system -w
   ```

4. **Knowledge Base** (after model server is ready)
   ```bash
   kubectl create -f pipeline/deploy-pipeline.yaml -n archon-agent
   ```

## Model Selection

Configured for NVIDIA RTX 5070 (16GB VRAM):

| Model | Purpose | Size | License |
|-------|---------|------|---------|
| Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4 | LLM inference | ~10-12GB | Apache 2.0 |
| BAAI/bge-base-en-v1.5 | Embeddings | ~1GB | MIT |

### Why These Models?
- **Qwen2.5-Coder-14B**: Optimized for code understanding, significantly better than 7B models for architecture questions
- **GPTQ-Int4 quantization**: Fits 14B model in 16GB VRAM
- **bge-base-en**: Code-optimized embeddings, better retrieval for technical content

### Alternative Models

If you experience OOM errors, try:
- Reduce `max_model_len` to 4096 in `configmap.yaml`
- Switch to `Qwen/Qwen2.5-Coder-7B-Instruct-GPTQ-Int4`

## GPU Requirements

- NVIDIA GPU with 16GB+ VRAM
- NVIDIA drivers installed on host
- NVIDIA Container Toolkit installed
- NVIDIA Device Plugin deployed to Kubernetes

### Verify GPU Setup
```bash
# Check NVIDIA device plugin
kubectl get pods -n kube-system | grep nvidia

# Check GPU availability
kubectl describe nodes | grep nvidia.com/gpu
```

## Troubleshooting

### Pod stuck in Pending
```bash
kubectl describe pod -n archon-system -l app=vllm
```
- "Insufficient nvidia.com/gpu": GPU not available or already allocated
- "RuntimeClass not found": Deploy RuntimeClass first

### Pod in CrashLoopBackOff
```bash
kubectl logs -n archon-system -l app=vllm --previous
```
- CUDA OOM: Reduce `gpu_memory_utilization` or `max_model_len`
- Model download failed: Check network connectivity

### Health check failing
```bash
kubectl exec -n archon-system -it deploy/vllm -- curl localhost:8000/health
kubectl exec -n archon-system -it deploy/vllm -- curl localhost:8000/v1/models
```

## Configuration

Edit `configmap.yaml` to change:
- `llm_model`: LLM model name
- `embedding_model`: Embedding model name
- `gpu_memory_utilization`: VRAM usage (0.0-1.0)
- `max_model_len`: Maximum context length
- `quantization`: Quantization method (gptq, awq, etc.)
