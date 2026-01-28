# Archon Agent Deployment Pipeline

Tekton pipeline for deploying the Archon Agent using GitOps.

## Overview

The deployment pipeline uses ArgoCD to manage the Agent CRD. The pipeline creates an ArgoCD Application that syncs `manifests/agent.yaml` from Git. The platform controller watches the Agent CRD and provisions the model server and orchestrator.

## Prerequisites

1. **Platform controllers** deployed (agents.aphex.io CRD)
2. **NVIDIA GPU** available on cluster
3. **ArgoCD** installed
4. **KnowledgeBase** deployed (archon-knowledge-base namespace)
5. **Target namespace** created (org-archon)

## Usage

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

## What Gets Deployed

The Agent CRD (`manifests/agent.yaml`) triggers the platform controller to provision:
- **Model server**: vLLM with GPU support
- **Orchestrator**: Unified RAG endpoint
- **Integration**: Connects to KnowledgeBase for RAG

## Monitoring

Check Agent status:
```bash
kubectl get agent archon-assistant -n org-archon
kubectl describe agent archon-assistant -n org-archon
```

Check ArgoCD Application:
```bash
kubectl get application archon-agent -n argocd
```
