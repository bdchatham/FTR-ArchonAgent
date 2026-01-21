# Operations

## Prerequisites

Before deploying:

1. **NVIDIA RuntimeClass** must exist (for vLLM)
2. **Knowledge Base** should be deployed (for RAG - optional, degrades gracefully)
3. **ArgoCD** installed in the cluster
4. **nginx Ingress Controller** deployed

## Deployment

### Deploy vLLM Model Server

```bash
kubectl apply -k manifests/model-server/
```

Or via Tekton pipeline:
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

### Deploy RAG Orchestrator

```bash
kubectl apply -k manifests/orchestrator/
```

### Verify Deployment

```bash
# Check pods
kubectl get pods -n archon-system

# Check services
kubectl get svc -n archon-system

# Test health endpoints
kubectl port-forward svc/archon-rag 8080:8080 -n archon-system &
curl http://localhost:8080/health
curl http://localhost:8080/ready

# Test chat completion
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 50}'
```

## Monitoring

### Key Metrics

**Orchestrator**:
- Request latency (total, RAG, vLLM)
- Context chunks retrieved per request
- Degraded mode occurrences

**vLLM**:
- GPU utilization
- Memory usage
- Inference latency

### Health Endpoints

| Service | Endpoint | Purpose |
|---------|----------|---------|
| Orchestrator | `/health` | Liveness |
| Orchestrator | `/ready` | Readiness (checks KB + vLLM) |
| vLLM | `/health` | Liveness/readiness |

### Logs

```bash
# Orchestrator logs
kubectl logs -n archon-system -l app=archon-rag -f

# vLLM logs
kubectl logs -n archon-system -l app=vllm -f
```

## Runbooks

### Orchestrator Not Ready

**Symptoms**: `/ready` returns 503

**Diagnosis**:
```bash
curl http://localhost:8080/ready
kubectl logs -n archon-system -l app=archon-rag
```

**Common causes**:
- vLLM not ready (GPU loading)
- KB unavailable (degraded mode, not failure)

**Resolution**:
1. Check vLLM status: `kubectl get pods -n archon-system -l app=vllm`
2. If vLLM is loading, wait for startup (15-30 min first time)
3. If KB is unavailable, orchestrator will work in degraded mode

### No Context Being Retrieved

**Symptoms**: Responses don't include KB context

**Diagnosis**:
```bash
# Check orchestrator logs for retrieval
kubectl logs -n archon-system -l app=archon-rag | grep -i retriev

# Check KB health
kubectl get pods -n archon-knowledge-base
```

**Common causes**:
- KB service unavailable
- Similarity threshold too high
- No relevant documents in KB

**Resolution**:
1. Verify KB is running: `kubectl get pods -n archon-knowledge-base`
2. Lower `RAG_SIMILARITY_THRESHOLD` in configmap
3. Verify documents are ingested in KB

### High Latency

**Symptoms**: Requests take >10 seconds

**Diagnosis**:
```bash
# Check orchestrator logs for timing
kubectl logs -n archon-system -l app=archon-rag | grep -i latency
```

**Common causes**:
- KB retrieval slow
- vLLM inference slow (long context)
- Network issues

**Resolution**:
1. Check RAG latency vs vLLM latency in logs
2. Reduce `RAG_CONTEXT_CHUNKS` to inject less context
3. Reduce `max_tokens` in requests

### vLLM OOM

**Symptoms**: vLLM pod crashes with OOM

**Resolution**:
1. Reduce `gpu_memory_utilization` in vLLM configmap
2. Reduce `max_model_len` in vLLM configmap
3. Consider smaller model

## Configuration Changes

### Disable RAG

Set `RAG_ENABLED=false` in orchestrator configmap:
```bash
kubectl patch configmap archon-rag-config -n archon-system \
  --type merge -p '{"data":{"RAG_ENABLED":"false"}}'
kubectl rollout restart deployment/archon-rag -n archon-system
```

### Adjust Context Chunks

```bash
kubectl patch configmap archon-rag-config -n archon-system \
  --type merge -p '{"data":{"RAG_CONTEXT_CHUNKS":"3"}}'
kubectl rollout restart deployment/archon-rag -n archon-system
```

### Change Similarity Threshold

```bash
kubectl patch configmap archon-rag-config -n archon-system \
  --type merge -p '{"data":{"RAG_SIMILARITY_THRESHOLD":"0.7"}}'
kubectl rollout restart deployment/archon-rag -n archon-system
```

## Scaling

**Orchestrator**: Can scale horizontally (stateless)
```bash
kubectl scale deployment/archon-rag -n archon-system --replicas=3
```

**vLLM**: Single replica per GPU. For more throughput, add GPU nodes.

**Source**
- `manifests/orchestrator/` - Orchestrator manifests
- `manifests/model-server/` - vLLM manifests
- `src/orchestrator/config.py` - Configuration options
