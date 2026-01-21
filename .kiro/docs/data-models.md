# Data Models

## Overview

ArchonAgent uses Kubernetes ConfigMaps for configuration. The orchestrator is stateless - it retrieves context from the Knowledge Base on each request.

## Orchestrator ConfigMap

Configuration for the RAG orchestrator.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: archon-rag-config
  namespace: archon-system
data:
  KNOWLEDGE_BASE_URL: "http://query.archon-knowledge-base.svc.cluster.local:8080"
  VLLM_URL: "http://vllm.archon-system.svc.cluster.local:8000"
  RAG_ENABLED: "true"
  RAG_CONTEXT_CHUNKS: "5"
  RAG_SIMILARITY_THRESHOLD: "0.5"
  RAG_RETRIEVAL_TIMEOUT: "5.0"
```

### Fields

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| KNOWLEDGE_BASE_URL | string | (see above) | KB query service URL |
| VLLM_URL | string | (see above) | vLLM service URL |
| RAG_ENABLED | bool | true | Enable RAG augmentation |
| RAG_CONTEXT_CHUNKS | int | 5 | Number of chunks to retrieve |
| RAG_SIMILARITY_THRESHOLD | float | 0.5 | Minimum similarity score (0-1) |
| RAG_RETRIEVAL_TIMEOUT | float | 5.0 | KB retrieval timeout in seconds |

### Tuning RAG_CONTEXT_CHUNKS

- **5** (default): Good balance of context and prompt length
- **3**: Less context, faster inference, lower token usage
- **10**: More context, may exceed model context window

### Tuning RAG_SIMILARITY_THRESHOLD

- **0.5** (default): Include moderately relevant chunks
- **0.7**: Only highly relevant chunks
- **0.3**: Include loosely related chunks

## vLLM ConfigMap

Configuration for the vLLM model server.

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
| llm_model | string | (see above) | HuggingFace model identifier |
| gpu_memory_utilization | float | 0.90 | Fraction of GPU VRAM to use |
| max_model_len | int | 8192 | Maximum context length in tokens |
| tensor_parallel_size | int | 1 | GPUs for tensor parallelism |
| quantization | string | gptq | Quantization method |

## Request/Response Models

### ChatCompletionRequest

```python
class ChatCompletionRequest:
    model: str                    # Model identifier
    messages: list[ChatMessage]   # Conversation history
    max_tokens: int | None        # Max tokens to generate
    temperature: float = 1.0      # Sampling temperature
    top_p: float = 1.0           # Nucleus sampling
    stream: bool = False         # Enable streaming
    stop: str | list[str] | None # Stop sequences
```

### ChatMessage

```python
class ChatMessage:
    role: str      # "system", "user", or "assistant"
    content: str   # Message content
```

### RetrievalChunk

Retrieved from Knowledge Base:

```python
class RetrievalChunk:
    content: str       # Chunk text
    source: str        # Source file path
    chunk_index: int   # Position in source
    score: float       # Similarity score (0-1)
```

## Context Injection Format

When context is retrieved, it's injected into the system message:

```
[Original system message]

## Relevant Context

The following information was retrieved from the knowledge base:

**Source:** operations.md
The deployment pipeline uses ArgoCD to sync manifests from Git...
---

**Source:** architecture.md
The system consists of three main components...
---

Use this context to inform your response. If the context doesn't contain relevant information, rely on your general knowledge.
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        Request Flow                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Client Request                                                  │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────┐                                            │
│  │ Extract Query   │  "How does deployment work?"               │
│  └────────┬────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐     ┌─────────────────┐                   │
│  │ Retrieve Context│────▶│ Knowledge Base  │                   │
│  └────────┬────────┘     │ /v1/retrieve    │                   │
│           │              └─────────────────┘                    │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐                                            │
│  │ Filter by Score │  score >= 0.5                              │
│  └────────┬────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐                                            │
│  │ Build Context   │  Format chunks with sources                │
│  └────────┬────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐                                            │
│  │ Augment System  │  Inject context into system message        │
│  │ Message         │                                            │
│  └────────┬────────┘                                            │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐     ┌─────────────────┐                   │
│  │ Forward to vLLM │────▶│ vLLM            │                   │
│  └────────┬────────┘     │ /v1/chat/...    │                   │
│           │              └─────────────────┘                    │
│           │                                                      │
│           ▼                                                      │
│  Response to Client                                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Source**
- `manifests/orchestrator/configmap.yaml`
- `manifests/model-server/configmap.yaml`
- `src/orchestrator/models.py`
- `src/orchestrator/rag_chain.py`
