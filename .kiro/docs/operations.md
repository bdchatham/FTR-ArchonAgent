# Operations

## Prerequisites

Before deploying the model server:

1. **NVIDIA RuntimeClass** must exist in the cluster
2. **NVIDIA Device Plugin** must be deployed
3. **GPU availability** verified on target node
4. **ArgoCD** installed in the cluster
5. **nginx Ingress Controller** deployed (for external access)

The Agent and Knowledge Base can be deployed independently - there is no required deployment order between them.

## Deployment

### Via Tekton Pipeline

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

### Via kubectl (direct)

```bash
kubectl apply -k manifests/model-server/
```

### Verify Deployment

```bash
# Check pod status
kubectl get pods -n archon-system -l app=vllm

# Watch startup progress
kubectl logs -n archon-system -l app=vllm -f

# Check service
kubectl get svc -n archon-system vllm

# Test health endpoint
kubectl port-forward svc/vllm 8000:8000 -n archon-system &
curl http://localhost:8000/health
```

## Monitoring

### Key Metrics

- **Pod status**: Running, Pending, CrashLoopBackOff
- **GPU utilization**: Via `nvidia-smi` on host
- **Memory usage**: Pod memory vs limits
- **Request latency**: Time to first token, total generation time

### Health Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/health` | Liveness/readiness check |
| `/v1/models` | List loaded models |

### Logs

```bash
# Current logs
kubectl logs -n archon-system -l app=vllm

# Previous container logs (after crash)
kubectl logs -n archon-system -l app=vllm --previous
```

## Alerting

Monitor for:

- Pod not ready for >5 minutes after startup
- CrashLoopBackOff status
- GPU memory exhaustion (OOM)
- High request latency (>30s for typical queries)

## Runbooks

### Pod Stuck in Pending

**Symptoms**: Pod remains in Pending state

**Diagnosis**:
```bash
kubectl describe pod -n archon-system -l app=vllm
```

**Common causes**:
- "Insufficient nvidia.com/gpu": GPU not available or already allocated
- "RuntimeClass not found": Deploy RuntimeClass first
- "Insufficient memory": Node lacks required memory

**Resolution**:
1. Check GPU availability: `kubectl describe nodes | grep nvidia.com/gpu`
2. Verify RuntimeClass exists: `kubectl get runtimeclass nvidia`
3. Check if another pod is using the GPU

### Pod in CrashLoopBackOff

**Symptoms**: Pod repeatedly crashes

**Diagnosis**:
```bash
kubectl logs -n archon-system -l app=vllm --previous
```

**Common causes**:
- CUDA OOM: Model too large for VRAM
- Model download failed: Network issues
- Invalid model name: Typo in configmap

**Resolution**:
1. For OOM: Reduce `gpu_memory_utilization` or `max_model_len` in configmap
2. For download failures: Check network, verify model name on HuggingFace
3. For invalid model: Correct the `llm_model` value in configmap

### Slow Model Loading

**Symptoms**: Pod takes >30 minutes to become ready

**Diagnosis**:
```bash
kubectl logs -n archon-system -l app=vllm -f
```

**Common causes**:
- First-time model download (expected: 15-30 min)
- Slow network connection
- PVC not properly mounted

**Resolution**:
1. First startup is slow - wait for download to complete
2. Verify PVC is bound: `kubectl get pvc -n archon-system`
3. Check download progress in logs

### High Inference Latency

**Symptoms**: Requests take >30 seconds

**Diagnosis**:
```bash
# Check GPU utilization on host
nvidia-smi

# Check pod resource usage
kubectl top pod -n archon-system
```

**Common causes**:
- Long input context
- High `max_tokens` in request
- GPU thermal throttling

**Resolution**:
1. Reduce `max_tokens` in requests
2. Check GPU temperature on host
3. Consider reducing `max_model_len` for faster inference

## Maintenance

### Model Updates

To change the LLM model:

1. Edit `manifests/model-server/configmap.yaml`
2. Update `llm_model` value
3. Commit and push changes
4. ArgoCD will sync and restart the pod
5. New model will be downloaded (15-30 min)

### Scaling

The model server runs as a single replica due to GPU constraints. For higher throughput:

1. Deploy additional GPU nodes
2. Create separate deployments per GPU
3. Use a load balancer across instances

### Backup

The model cache PVC contains downloaded models only - no backup required. Models are re-downloaded from HuggingFace if PVC is lost.

**Source**
- `manifests/model-server/deployment.yaml`
- `manifests/model-server/configmap.yaml`
- `pipeline/deploy-model-server.yaml`
