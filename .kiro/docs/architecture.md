# Architecture

## System Design

ArchonAgent deploys a single vLLM model server running Qwen2.5-Coder-14B-Instruct-GPTQ-Int4 on an NVIDIA RTX 5070 GPU (16GB VRAM). The server provides OpenAI-compatible endpoints for LLM inference.

```
┌─────────────────────────────────────────────────────────────┐
│                      archon-system namespace                │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                   vLLM Deployment                    │   │
│  │                                                      │   │
│  │  ┌────────────────────────────────────────────────┐ │   │
│  │  │              vllm/vllm-openai:v0.4.0           │ │   │
│  │  │                                                │ │   │
│  │  │  Model: Qwen2.5-Coder-14B-Instruct-GPTQ-Int4  │ │   │
│  │  │  GPU: nvidia.com/gpu: 1                       │ │   │
│  │  │  Port: 8000                                   │ │   │
│  │  └────────────────────────────────────────────────┘ │   │
│  │                         │                            │   │
│  │                         ▼                            │   │
│  │              ┌──────────────────┐                   │   │
│  │              │   model-cache    │                   │   │
│  │              │   PVC (50Gi)     │                   │   │
│  │              └──────────────────┘                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                         │                                   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              vllm Service (ClusterIP)               │   │
│  │              Port: 8000                              │   │
│  └─────────────────────────────────────────────────────┘   │
│                         │                                   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              vllm Ingress                            │   │
│  │              Host: archon.home.local                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Components

### vLLM Model Server

The core inference engine using vLLM's OpenAI-compatible server:

- **Image**: `vllm/vllm-openai:v0.4.0`
- **RuntimeClass**: `nvidia` for GPU access
- **Resources**: 16-24Gi memory, 4-8 CPU cores, 1 GPU
- **Health probes**: Startup (30min timeout), liveness, readiness via `/health`

### ConfigMap (vllm-config)

Externalized configuration for model selection and VRAM optimization:

- `llm_model`: Model identifier from HuggingFace
- `gpu_memory_utilization`: VRAM usage fraction (0.90 default)
- `max_model_len`: Maximum context length (8192 default)
- `quantization`: Quantization method (gptq)

### PersistentVolumeClaim (model-cache)

50Gi storage for HuggingFace model cache:

- Mounted at `/root/.cache/huggingface`
- Persists models across pod restarts
- First startup downloads models (~15-30 min)
- Subsequent restarts use cache (~2 min)

### Service (vllm)

ClusterIP service exposing the model server:

- Internal DNS: `vllm.archon-system.svc.cluster.local`
- Port: 8000

### Ingress (vllm)

External access via nginx ingress:

- Host: `archon.home.local`
- Extended timeouts for long inference requests

## Technology Stack

- **vLLM**: High-throughput LLM serving engine
- **Qwen2.5-Coder-14B**: Code-optimized LLM with Apache 2.0 license
- **GPTQ**: Post-training quantization for reduced VRAM usage
- **Kubernetes**: Container orchestration
- **ArgoCD**: GitOps deployment
- **Tekton**: CI/CD pipelines

## Dependencies

### Upstream Dependencies

- **NVIDIA RuntimeClass**: Must exist before deployment (from AphexPlatformInfrastructure)
- **NVIDIA Device Plugin**: Provides GPU scheduling
- **nginx Ingress Controller**: For external access
- **ArgoCD**: For GitOps deployment
- **HuggingFace Hub**: Model downloads

### Downstream Dependencies

- **ArchonKnowledgeBaseInfrastructure**: Uses vLLM for LLM inference (optional - KB can be deployed independently)

**Source**
- `manifests/model-server/deployment.yaml`
- `manifests/model-server/configmap.yaml`
- `manifests/model-server/service.yaml`
- `manifests/model-server/ingress.yaml`
- `manifests/model-server/pvc.yaml`
