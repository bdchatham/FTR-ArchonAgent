# Architecture

## System Design

ArchonAgent provides a transparent RAG proxy in front of vLLM. Clients send standard OpenAI chat completion requests; the orchestrator retrieves context from the Knowledge Base, augments the prompt, and forwards to vLLM.

```
┌──────────┐                        ┌─────────────────────────────────────────────┐
│  Client  │   /v1/chat/completions │              archon-system namespace        │
│          │ ──────────────────────▶│                                             │
└──────────┘   archon.home.local    │  ┌───────────────────────────────────────┐  │
                                    │  │         RAG Orchestrator              │  │
                                    │  │         (archon-rag:8080)             │  │
                                    │  │                                       │  │
                                    │  │  1. Extract query from messages       │  │
                                    │  │  2. Retrieve context from KB ─────────┼──┼──┐
                                    │  │  3. Augment prompt with context       │  │  │
                                    │  │  4. Forward to vLLM ──────────────────┼──┼──┼──┐
                                    │  │  5. Return response                   │  │  │  │
                                    │  └───────────────────────────────────────┘  │  │  │
                                    │                                             │  │  │
                                    │  ┌───────────────────────────────────────┐  │  │  │
                                    │  │              vLLM                     │◀─┼──┼──┘
                                    │  │         (vllm:8000)                   │  │  │
                                    │  │                                       │  │  │
                                    │  │  Model: Qwen2.5-Coder-14B-GPTQ-Int4  │  │  │
                                    │  │  GPU: nvidia.com/gpu: 1              │  │  │
                                    │  └───────────────────────────────────────┘  │  │
                                    └─────────────────────────────────────────────┘  │
                                                                                     │
                                    ┌─────────────────────────────────────────────┐  │
                                    │       archon-knowledge-base namespace       │  │
                                    │                                             │  │
                                    │  ┌───────────────────────────────────────┐  │  │
                                    │  │           Query Service               │◀─┼──┘
                                    │  │         (query:8080)                  │  │
                                    │  │         POST /v1/retrieve             │  │
                                    │  └───────────────────────────────────────┘  │
                                    └─────────────────────────────────────────────┘
```

## Components

### RAG Orchestrator

Lightweight FastAPI service that coordinates retrieval and inference:

- **Image**: `ghcr.io/bdchatham/archon-rag-orchestrator:latest`
- **Port**: 8080
- **Resources**: 256-512Mi memory, 100-500m CPU
- **Framework**: FastAPI + LangChain

Key responsibilities:
1. Parse incoming OpenAI chat completion requests
2. Extract user query from conversation
3. Call Knowledge Base to retrieve relevant context
4. Augment system prompt with retrieved context
5. Forward augmented request to vLLM
6. Return response in OpenAI format

### vLLM Model Server

GPU-accelerated inference engine:

- **Image**: `vllm/vllm-openai:v0.4.0`
- **RuntimeClass**: `nvidia` for GPU access
- **Resources**: 16-24Gi memory, 4-8 CPU cores, 1 GPU
- **Model**: Qwen2.5-Coder-14B-Instruct-GPTQ-Int4

### Configuration

**Orchestrator ConfigMap** (`archon-rag-config`):
- `KNOWLEDGE_BASE_URL`: KB query service URL
- `VLLM_URL`: vLLM service URL
- `RAG_ENABLED`: Enable/disable RAG augmentation
- `RAG_CONTEXT_CHUNKS`: Number of chunks to retrieve
- `RAG_SIMILARITY_THRESHOLD`: Minimum similarity score

**vLLM ConfigMap** (`vllm-config`):
- `llm_model`: HuggingFace model identifier
- `gpu_memory_utilization`: VRAM usage fraction
- `max_model_len`: Maximum context length

## Request Flow

1. **Client Request**: Standard OpenAI chat completion request arrives
2. **Query Extraction**: Orchestrator extracts the last user message
3. **Context Retrieval**: Orchestrator calls KB `/v1/retrieve` with the query
4. **Filtering**: Chunks below similarity threshold are discarded
5. **Prompt Augmentation**: Context is injected into system message
6. **LLM Inference**: Augmented request forwarded to vLLM
7. **Response**: vLLM response returned to client unchanged

## Graceful Degradation

The orchestrator degrades gracefully when dependencies are unavailable:

| Scenario | Behavior |
|----------|----------|
| KB unreachable | Forward to vLLM without augmentation |
| KB timeout (>5s) | Forward to vLLM without augmentation |
| KB returns empty | Forward to vLLM without augmentation |
| vLLM unreachable | Return 503 Service Unavailable |

## Technology Stack

- **FastAPI**: Async web framework for orchestrator
- **LangChain**: RAG chain construction and prompt management
- **vLLM**: High-throughput LLM serving engine
- **Qwen2.5-Coder-14B**: Code-optimized LLM
- **Kubernetes**: Container orchestration
- **ArgoCD**: GitOps deployment

## Dependencies

### Upstream Dependencies

- **ArchonKnowledgeBaseInfrastructure**: Provides `/v1/retrieve` for context retrieval
- **NVIDIA RuntimeClass**: Required for vLLM GPU access
- **nginx Ingress Controller**: For external access

### Downstream Dependencies

None - this is the top of the inference stack.

**Source**
- `src/orchestrator/main.py` - Orchestrator FastAPI app
- `src/orchestrator/rag_chain.py` - LangChain RAG logic
- `manifests/orchestrator/` - Orchestrator Kubernetes manifests
- `manifests/model-server/` - vLLM Kubernetes manifests
