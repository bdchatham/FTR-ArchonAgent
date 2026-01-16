# Archon Agent Deployment Pipeline

This directory contains the Tekton pipeline for deploying the Archon Agent knowledge base using GitOps.

## Overview

The deployment pipeline uses ArgoCD to manage the Archon Agent deployment. The pipeline creates an ArgoCD Application that watches this repository and automatically syncs changes to the cluster.

## Architecture

```
Pipeline → argocd-deployment Task → ArgoCD Application → Kubernetes Manifests
```

1. **Pipeline** (`deploy-pipeline.yaml`): Defines the deployment workflow
2. **argocd-deployment Task**: Reusable platform task that creates ArgoCD Applications
3. **ArgoCD Application**: Watches the Git repository and syncs manifests
4. **Kubernetes Manifests** (`manifests/knowledge-base/`): Actual deployment resources

## Files

- `deploy-pipeline.yaml`: Tekton Pipeline definition
- `role-binding.yaml`: Grants pipeline permission to create ArgoCD Applications

## RBAC Setup

The pipeline uses the platform's standard `pipeline-runner` ServiceAccount, which is automatically created by the RepoBinding controller when you create a pipeline via `aphex pipeline create`.

The RoleBinding grants this ServiceAccount permission to create ArgoCD Applications by binding to the shared `argocd-application-deployer` ClusterRole.

## Usage

### Manual Trigger

```bash
# Create a PipelineRun
kubectl create -f - <<EOF
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  generateName: deploy-knowledge-base-
  namespace: archon-agent
spec:
  pipelineRef:
    name: deploy-knowledge-base
  params:
    - name: git-url
      value: https://github.com/bdchatham/ArchonAgent
    - name: git-revision
      value: main
    - name: manifest-path
      value: manifests/knowledge-base
    - name: app-name
      value: archon-knowledge-base
    - name: target-namespace
      value: archon-kb
EOF
```

### Via GitHub Webhook

When configured with a RepoBinding, GitHub pushes will automatically trigger the pipeline.

## Parameters

- `git-url`: Git repository URL (default: https://github.com/bdchatham/ArchonAgent)
- `git-revision`: Git branch, tag, or commit SHA (default: main)
- `manifest-path`: Path to Kubernetes manifests in the repo (default: manifests/knowledge-base)
- `app-name`: Name of the ArgoCD Application (default: archon-knowledge-base)
- `target-namespace`: Target namespace for deployment (default: archon-kb)

## Monitoring

Check ArgoCD Application status:

```bash
kubectl get application archon-knowledge-base -n argocd
```

View sync status:

```bash
kubectl get application archon-knowledge-base -n argocd -o jsonpath='{.status.sync.status}'
```

View health status:

```bash
kubectl get application archon-knowledge-base -n argocd -o jsonpath='{.status.health.status}'
```

## Benefits of GitOps Approach

1. **Declarative**: All configuration is in Git
2. **Automated**: Changes are automatically synced
3. **Auditable**: Git history provides complete audit trail
4. **Recoverable**: Easy rollback via Git
5. **Self-healing**: ArgoCD automatically corrects drift
6. **Simplified Pipeline**: Pipeline just creates the Application, ArgoCD does the rest
