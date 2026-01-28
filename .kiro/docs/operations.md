# Operations

## Prerequisites

Before deploying:

1. **Platform controllers** deployed (agents.aphex.io CRD available)
2. **NVIDIA GPU** available on cluster nodes
3. **ArgoCD** installed in the cluster
4. **KnowledgeBase** deployed (optional, for RAG - degrades gracefully if unavailable)
5. **Target namespace** created (e.g., `org-archon`)

Verify prerequisites:
```bash
# Check Agent CRD exists
kubectl get crd agents.aphex.io

# Check GPU availability
kubectl describe nodes | grep nvidia.com/gpu

# Check ArgoCD
kubectl get pods -n argocd
```

## Deployment

### Deploy Agent via Pipeline

The recommended approach uses the Tekton pipeline with ArgoCD:

```bash
kubectl create -f - <<EOF
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  generateName: archon-agent-
  namespace: org-archon
spec:
  pipelineRef:
    name: deploy-agent
  params:
    - name: git-url
      value: https://github.com/bdchatham/ArchonAgent
    - name: git-revision
      value: mainline
EOF
```

This creates an ArgoCD Application that syncs `manifests/agent.yaml` from Git. The platform controller watches the Agent CRD and provisions infrastructure.

### Deploy Agent via Aphex CLI

Alternatively, use the Aphex CLI:

```bash
aphex agent create archon-assistant \
  --namespace org-archon \
  --model Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4 \
  --provider vllm \
  --gpu-count 1 \
  --quantization gptq_marlin \
  --kb-name platform-docs \
  --kb-namespace archon-knowledge-base \
  --orchestration \
  --kubeconfig ~/.kube/config
```

### Verify Deployment

```bash
# Check Agent CRD status
kubectl get agent archon-assistant -n org-archon
kubectl describe agent archon-assistant -n org-archon

# Check provisioned resources
kubectl get all -n org-archon

# Check ArgoCD Application (if deployed via pipeline)
kubectl get application archon-agent -n argocd

# Test orchestrator health
kubectl port-forward svc/archon-assistant-orchestrator 8080:8080 -n org-archon &
curl http://localhost:8080/health
curl http://localhost:8080/ready

# Test chat completion
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 50
  }'
```

## Configuration Changes

To modify agent configuration:

1. **Edit `manifests/agent.yaml`** in Git
2. **Commit and push** changes
3. **ArgoCD syncs** automatically (if auto-sync enabled)
4. **Platform controller reconciles** Agent CRD
5. **Infrastructure updates** to match desired state

Example: Change GPU count:
```yaml
spec:
  model:
    gpuCount: 2  # Changed from 1
```

## Monitoring

### Agent Status

Check Agent CRD status:
```bash
kubectl get agent archon-assistant -n org-archon -o yaml
```

Key status fields:
- `status.phase` - Current state (Pending, Ready, Failed)
- `status.modelServer.deployed` - Model server deployment status
- `status.modelServer.serviceURL` - Internal service URL
- `status.orchestrator.deployed` - Orchestrator deployment status
- `status.message` - Human-readable status information

### Resource Health

```bash
# Check pods
kubectl get pods -n org-archon

# Check services
kubectl get svc -n org-archon

# Check logs
kubectl logs -n org-archon -l app=archon-assistant-model-server
kubectl logs -n org-archon -l app=archon-assistant-orchestrator
```

### Key Metrics

**Model Server**:
- GPU utilization
- Memory usage
- Inference latency
- Request throughput

**Orchestrator**:
- Request latency (total, RAG, vLLM)
- Context chunks retrieved per request
- Degraded mode occurrences

### Health Endpoints

| Service | Endpoint | Purpose |
|---------|----------|---------|
| Orchestrator | `/health` | Liveness check |
| Orchestrator | `/ready` | Readiness check |
| Model Server | `/health` | vLLM health check |

## Troubleshooting

### Agent Stuck in Pending

Check platform controller logs:
```bash
kubectl logs -n platform-system -l app=platform-controller
```

Common causes:
- GPU resources unavailable
- Image pull failures
- Insufficient cluster resources

### Model Server Not Starting

Check pod events and logs:
```bash
kubectl describe pod -n org-archon -l app=archon-assistant-model-server
kubectl logs -n org-archon -l app=archon-assistant-model-server
```

Common causes:
- GPU not available (check `nvidia.com/gpu` resource)
- Model download timeout (large model, slow network)
- Insufficient VRAM for model + quantization

### Orchestrator Degraded Mode

Check orchestrator logs for KB connectivity:
```bash
kubectl logs -n org-archon -l app=archon-assistant-orchestrator | grep -i "knowledge base"
```

The orchestrator degrades gracefully when KB is unavailable - requests still work but without RAG augmentation.

### ArgoCD Sync Issues

Check ArgoCD Application status:
```bash
kubectl get application archon-agent -n argocd
kubectl describe application archon-agent -n argocd
```

Force sync:
```bash
kubectl patch application archon-agent -n argocd \
  --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

## Rollback

To rollback to a previous version:

1. **Revert Git commit** containing `manifests/agent.yaml` changes
2. **ArgoCD syncs** automatically
3. **Platform controller reconciles** to previous state

Or manually edit the Agent CRD:
```bash
kubectl edit agent archon-assistant -n org-archon
```

## Deletion

To delete the agent:

```bash
# Via Aphex CLI
aphex agent delete archon-assistant --namespace org-archon

# Via kubectl
kubectl delete agent archon-assistant -n org-archon
```

The platform controller automatically cleans up all provisioned resources.

**Source**
- `manifests/agent.yaml` - Agent CRD manifest
- `pipeline/deploy-agent.yaml` - Deployment pipeline
- Platform controller in AphexPlatformInfrastructure
|---------|----------|---------|
| Orchestrator | `/health` | Liveness |
| Orchestrator | `/ready` | Readiness (checks KB + vLLM) |
| vLLM | `/health` | Liveness/readiness |

### Logs

```bash
# Orchestrator logs
kubectl logs -n archon-orchestrator -l app=archon-rag -f

# vLLM logs
kubectl logs -n archon-model-server -l app=vllm -f
```

## Runbooks

### Orchestrator Not Ready

**Symptoms**: `/ready` returns 503

**Diagnosis**:
```bash
curl http://localhost:8080/ready
kubectl logs -n archon-orchestrator -l app=archon-rag
```

**Common causes**:
- vLLM not ready (GPU loading)
- KB unavailable (degraded mode, not failure)

**Resolution**:
1. Check vLLM status: `kubectl get pods -n archon-model-server -l app=vllm`
2. If vLLM is loading, wait for startup (15-30 min first time)
3. If KB is unavailable, orchestrator will work in degraded mode

### No Context Being Retrieved

**Symptoms**: Responses don't include KB context

**Diagnosis**:
```bash
# Check orchestrator logs for retrieval
kubectl logs -n archon-orchestrator -l app=archon-rag | grep -i retriev

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
kubectl logs -n archon-orchestrator -l app=archon-rag | grep -i latency
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
kubectl patch configmap archon-rag-config -n archon-orchestrator \
  --type merge -p '{"data":{"RAG_ENABLED":"false"}}'
kubectl rollout restart deployment/archon-rag -n archon-orchestrator
```

### Adjust Context Chunks

```bash
kubectl patch configmap archon-rag-config -n archon-orchestrator \
  --type merge -p '{"data":{"RAG_CONTEXT_CHUNKS":"3"}}'
kubectl rollout restart deployment/archon-rag -n archon-orchestrator
```

### Change Similarity Threshold

```bash
kubectl patch configmap archon-rag-config -n archon-orchestrator \
  --type merge -p '{"data":{"RAG_SIMILARITY_THRESHOLD":"0.7"}}'
kubectl rollout restart deployment/archon-rag -n archon-orchestrator
```

## Scaling

**Orchestrator**: Can scale horizontally (stateless)
```bash
kubectl scale deployment/archon-rag -n archon-orchestrator --replicas=3
```

**vLLM**: Single replica per GPU. For more throughput, add GPU nodes.

**Source**
- `manifests/orchestrator/` - Orchestrator manifests
- `manifests/model-server/` - vLLM manifests
- `src/orchestrator/config.py` - Configuration options
