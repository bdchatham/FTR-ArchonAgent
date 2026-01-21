# Archon Agent Deployment Pipeline

Tekton pipeline for deploying the vLLM model server using GitOps.

## Overview

The deployment pipeline uses ArgoCD to manage the vLLM model server deployment. The pipeline creates an ArgoCD Application that watches this repository and automatically syncs changes to the cluster.

## Prerequisites

Before running the pipeline:

1. **NVIDIA RuntimeClass** must exist (from AphexPlatformInfrastructure)
2. **NVIDIA Device Plugin** deployed to cluster
3. **ArgoCD** installed and configured
4. **argocd-deployment task** available (from AphexPipelineResources)

Verify GPU availability:
```bash
kubectl describe nodes | grep nvidia.com/gpu
kubectl get runtimeclass nvidia
```

## Files

- `deploy-model-server.yaml`: Tekton Pipeline for model server deployment
- `role-binding.yaml`: Grants pipeline permission to create ArgoCD Applications

## Usage

### Deploy Model Server

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

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| git-url | https://github.com/bdchatham/ArchonAgent | Git repository URL |
| git-revision | main | Git branch, tag, or commit |
| manifest-path | manifests/model-server | Path to manifests |
| app-name | archon-model-server | ArgoCD Application name |
| target-namespace | archon-system | Target namespace |

## Monitoring

Check ArgoCD Application status:
```bash
kubectl get application archon-model-server -n argocd
kubectl get application archon-model-server -n argocd -o jsonpath='{.status.sync.status}'
```

Check pod status:
```bash
kubectl get pods -n archon-system -l app=vllm
```

Verify health:
```bash
kubectl port-forward svc/vllm 8000:8000 -n archon-system &
curl http://localhost:8000/health
```

## Independent Deployment

The Agent and Knowledge Base can be deployed independently. There is no required deployment order between them.

- **Agent**: Provides LLM inference via vLLM
- **Knowledge Base**: Provides document storage, embedding generation, and retrieval (has its own Embedding Service)

Deploy Knowledge Base from [ArchonKnowledgeBaseInfrastructure](https://github.com/bdchatham/ArchonKnowledgeBaseInfrastructure).
