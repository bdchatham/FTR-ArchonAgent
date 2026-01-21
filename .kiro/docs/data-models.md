# Data Models

## Overview

ArchonAgent uses Kubernetes ConfigMaps for configuration and PersistentVolumeClaims for model storage. There are no application-level data models - the vLLM container handles all inference logic.

## ConfigMap: vllm-config

Externalized configuration for the vLLM model server.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vllm-config
  namespace: archon-system
data:
  llm_model: "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4"
  gpu_memory_utilization: "0.90"
  max_model_len: "8192"
  tensor_parallel_size: "1"
  quantization: "gptq"
```

### Fields

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| llm_model | string | Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4 | HuggingFace model identifier |
| gpu_memory_utilization | string | 0.90 | Fraction of GPU VRAM to use (0.0-1.0) |
| max_model_len | string | 8192 | Maximum context length in tokens |
| tensor_parallel_size | string | 1 | Number of GPUs for tensor parallelism |
| quantization | string | gptq | Quantization method (gptq, awq, none) |

### Model Selection Guidelines

For 16GB VRAM (RTX 5070):

| Model | Size | Use Case |
|-------|------|----------|
| Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4 | ~10-12GB | Code understanding, architecture questions |
| Qwen/Qwen2.5-Coder-7B-Instruct-GPTQ-Int4 | ~5-6GB | Lighter workloads, faster inference |

### Tuning gpu_memory_utilization

- **0.90** (default): Maximizes model capacity, may cause OOM under heavy load
- **0.85**: Safer margin for concurrent requests
- **0.80**: Conservative, good for stability testing

### Tuning max_model_len

- **8192** (default): Full context for most use cases
- **4096**: Reduced memory, faster inference
- **2048**: Minimal memory, suitable for short queries

## ResourceQuota: gpu-quota

Limits GPU allocation in the namespace.

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: gpu-quota
  namespace: archon-system
spec:
  hard:
    requests.nvidia.com/gpu: "1"
    limits.nvidia.com/gpu: "1"
```

### Fields

| Key | Value | Description |
|-----|-------|-------------|
| requests.nvidia.com/gpu | 1 | Maximum GPU requests in namespace |
| limits.nvidia.com/gpu | 1 | Maximum GPU limits in namespace |

## LimitRange: default-limits

Default resource limits for containers without explicit limits.

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: archon-system
spec:
  limits:
    - default:
        memory: "512Mi"
        cpu: "500m"
      defaultRequest:
        memory: "256Mi"
        cpu: "100m"
      type: Container
```

Note: The vLLM deployment specifies explicit resource requests/limits, so these defaults apply only to other containers in the namespace.

## PersistentVolumeClaim: model-cache

Storage for HuggingFace model cache.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: model-cache
  namespace: archon-system
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 50Gi
  storageClassName: local-path
```

### Fields

| Key | Value | Description |
|-----|-------|-------------|
| accessModes | ReadWriteOnce | Single-node read-write access |
| storage | 50Gi | Storage capacity for model files |
| storageClassName | local-path | Storage class (adjust for your cluster) |

### Storage Requirements

| Model | Approximate Size |
|-------|------------------|
| Qwen2.5-Coder-14B-GPTQ-Int4 | ~10GB |
| Qwen2.5-Coder-7B-GPTQ-Int4 | ~5GB |
| Additional cache overhead | ~5GB |

50Gi provides headroom for model updates and multiple cached versions.

## Data Flow

```
ConfigMap (vllm-config)
        │
        ▼
┌───────────────────┐
│  vLLM Container   │
│                   │
│  Reads config via │
│  environment vars │
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  HuggingFace Hub  │
│  (model download) │
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  PVC (model-cache)│
│  /root/.cache/    │
│  huggingface      │
└───────────────────┘
```

**Source**
- `manifests/model-server/configmap.yaml`
- `manifests/model-server/resource-quota.yaml`
- `manifests/model-server/limit-range.yaml`
- `manifests/model-server/pvc.yaml`
