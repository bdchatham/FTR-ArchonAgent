# API

## Overview

The vLLM model server exposes OpenAI-compatible REST endpoints for LLM inference. Clients can use standard OpenAI client libraries or direct HTTP requests.

## Base URLs

- **Internal**: `http://vllm.archon-system.svc.cluster.local:8000`
- **External**: `http://archon.home.local` (via Ingress)

## Endpoints

### Health Check

```
GET /health
```

Returns 200 when the server is healthy and ready to serve requests.

**Response**:
```json
{}
```

### List Models

```
GET /v1/models
```

Lists available models loaded in the server.

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

### Chat Completions

```
POST /v1/chat/completions
```

Generate chat completions using the loaded LLM.

**Request Body**:
```json
{
  "model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
  "messages": [
    {"role": "system", "content": "You are a helpful coding assistant."},
    {"role": "user", "content": "Write a Python function to calculate fibonacci numbers."}
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
        "content": "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 42,
    "total_tokens": 67
  }
}
```

**Streaming Response** (when `stream: true`):

Server-Sent Events format:
```
data: {"id":"cmpl-abc123","object":"chat.completion.chunk","choices":[{"delta":{"content":"def"},"index":0}]}

data: {"id":"cmpl-abc123","object":"chat.completion.chunk","choices":[{"delta":{"content":" fibonacci"},"index":0}]}

data: [DONE]
```

## Authentication

No authentication is required for internal cluster access. For external access via Ingress, configure authentication at the Ingress level if needed.

## Error Handling

### Error Response Format

```json
{
  "error": {
    "message": "Error description",
    "type": "error_type",
    "code": "error_code"
  }
}
```

### Common Error Codes

| HTTP Status | Error Type | Description |
|-------------|------------|-------------|
| 400 | invalid_request_error | Malformed request body |
| 404 | model_not_found | Requested model not loaded |
| 503 | service_unavailable | Model server not ready |
| 500 | internal_error | Server error |

## Integration Examples

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://vllm.archon-system.svc.cluster.local:8000/v1",
    api_key="not-needed"  # vLLM doesn't require auth
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
    messages=[
        {"role": "user", "content": "Explain async/await in Python"}
    ],
    max_tokens=512
)

print(response.choices[0].message.content)
```

### curl

```bash
curl -X POST http://vllm.archon-system.svc.cluster.local:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 100
  }'
```

### Streaming with curl

```bash
curl -X POST http://vllm.archon-system.svc.cluster.local:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
    "messages": [{"role": "user", "content": "Write a haiku about coding"}],
    "max_tokens": 100,
    "stream": true
  }'
```

**Source**
- `manifests/model-server/service.yaml`
- `manifests/model-server/ingress.yaml`
- vLLM OpenAI-compatible API documentation
