# API

## Overview

ArchonAgent exposes an OpenAI-compatible REST API for chat completions. The RAG orchestrator transparently augments requests with context from the Knowledge Base - clients use the standard OpenAI format and receive context-aware responses.

## Base URLs

- **RAG-enabled (recommended)**: `http://archon.home.local`
- **Direct vLLM (bypass RAG)**: `http://vllm.home.local`
- **Internal orchestrator**: `http://archon-rag.archon-system.svc.cluster.local:8080`
- **Internal vLLM**: `http://vllm.archon-system.svc.cluster.local:8000`

## Endpoints

### Chat Completions

```
POST /v1/chat/completions
```

Generate chat completions with automatic RAG augmentation.

**Request Body**:
```json
{
  "model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
  "messages": [
    {"role": "system", "content": "You are a helpful coding assistant."},
    {"role": "user", "content": "How does the deployment pipeline work?"}
  ],
  "max_tokens": 1024,
  "temperature": 0.7,
  "stream": false
}
```

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| model | string | Yes | - | Model identifier |
| messages | array | Yes | - | Conversation messages |
| max_tokens | integer | No | 16 | Maximum tokens to generate |
| temperature | float | No | 1.0 | Sampling temperature (0-2) |
| top_p | float | No | 1.0 | Nucleus sampling parameter |
| stream | boolean | No | false | Enable streaming response |
| stop | string/array | No | null | Stop sequences |

**What happens behind the scenes**:
1. Orchestrator extracts "How does the deployment pipeline work?" as the query
2. Calls Knowledge Base to retrieve relevant documentation chunks
3. Augments the system message with retrieved context
4. Forwards to vLLM for inference
5. Returns the response unchanged

**Response** (non-streaming):
```json
{
  "id": "cmpl-abc123",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Based on the documentation, the deployment pipeline uses ArgoCD..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 200,
    "total_tokens": 350
  }
}
```

**Streaming Response** (when `stream: true`):

Server-Sent Events format:
```
data: {"id":"cmpl-abc123","object":"chat.completion.chunk","choices":[{"delta":{"content":"Based"},"index":0}]}

data: {"id":"cmpl-abc123","object":"chat.completion.chunk","choices":[{"delta":{"content":" on"},"index":0}]}

data: [DONE]
```

### List Models

```
GET /v1/models
```

Lists available models (proxied to vLLM).

**Response**:
```json
{
  "object": "list",
  "data": [
    {
      "id": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
      "object": "model",
      "created": 1234567890,
      "owned_by": "vllm"
    }
  ]
}
```

### Health Check

```
GET /health
```

Liveness check - returns 200 when orchestrator is running.

**Response**:
```json
{"status": "healthy"}
```

### Readiness Check

```
GET /ready
```

Readiness check - verifies connectivity to KB and vLLM.

**Response** (healthy):
```json
{
  "status": "ready",
  "knowledge_base": "healthy",
  "vllm": "healthy",
  "rag_enabled": true
}
```

**Response** (degraded - KB unavailable):
```json
{
  "status": "degraded",
  "knowledge_base": "unavailable",
  "vllm": "healthy",
  "rag_enabled": false
}
```

**Response** (unhealthy - vLLM unavailable):
```
HTTP 503 Service Unavailable
{"detail": "vLLM unavailable: unavailable"}
```

## RAG Configuration

The orchestrator behavior is controlled by environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_ENABLED` | true | Enable/disable RAG augmentation |
| `RAG_CONTEXT_CHUNKS` | 5 | Number of chunks to retrieve |
| `RAG_SIMILARITY_THRESHOLD` | 0.5 | Minimum similarity score (0-1) |
| `RAG_RETRIEVAL_TIMEOUT` | 5.0 | Timeout for KB retrieval (seconds) |

## Integration Examples

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://archon.home.local/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
    messages=[
        {"role": "user", "content": "How does the deployment pipeline work?"}
    ],
    max_tokens=512
)

print(response.choices[0].message.content)
```

### curl

```bash
curl -X POST http://archon.home.local/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
    "messages": [{"role": "user", "content": "Explain the architecture"}],
    "max_tokens": 512
  }'
```

### Streaming with curl

```bash
curl -X POST http://archon.home.local/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
    "messages": [{"role": "user", "content": "Write a deployment script"}],
    "max_tokens": 512,
    "stream": true
  }'
```

### Bypass RAG (direct vLLM)

```bash
curl -X POST http://vllm.home.local/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'
```

## Error Handling

| HTTP Status | Condition | Response |
|-------------|-----------|----------|
| 400 | Invalid request | `{"detail": "..."}` |
| 503 | vLLM unavailable | `{"detail": "vLLM service unavailable"}` |
| 503 | Readiness check failed | `{"detail": "vLLM unavailable: ..."}` |

Note: KB unavailability does NOT cause errors - the orchestrator degrades gracefully and forwards requests without augmentation.

**Source**
- `src/orchestrator/main.py` - API implementation
- `src/orchestrator/models.py` - Request/response models
- `manifests/orchestrator/configmap.yaml` - Configuration
