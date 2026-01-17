# Archon Pipeline Installation Guide

## Product Team Workflow (ArchonAgent)

### 1. Install Pipeline via AphexCLI

```bash
# From ArchonAgent repository root
aphex pipeline create archon-pipeline --file aphex-pipeline/pipeline.yaml --namespace archon-ci
```

**What this does:**
- Creates `archon-pipeline` Pipeline in `archon-ci` namespace
- Installs RBAC and ServiceAccount for pipeline execution
- Makes pipeline available for webhook triggering

### 2. Verify Pipeline Installation

```bash
# Check pipeline exists
kubectl get pipeline archon-pipeline -n archon-ci

# View pipeline details
kubectl describe pipeline archon-pipeline -n archon-ci
```

## Platform Operator Workflow

### 3. Create RepoBinding for Webhook Provisioning

```bash
# Platform operator applies RepoBinding
kubectl apply -f - <<EOF
apiVersion: aphex/v1alpha1
kind: RepoBinding
metadata:
  name: archon-binding
  namespace: pipeline-system
spec:
  repoOrg: "bdchatham"
  repoName: "ArchonAgent"
  tenantName: "archon-ci"
  pipelineName: "archon-pipeline"
  permissionProfile: "standard"
  ingressHost: "webhooks.home.local"
EOF
```

### 4. Get Webhook Configuration

```bash
# Check RepoBinding status
kubectl get repobinding archon-binding -n pipeline-system -o yaml

# Extract webhook URL and secret
kubectl get repobinding archon-binding -n pipeline-system -o jsonpath='{.status.webhookURL}'
kubectl get repobinding archon-binding -n pipeline-system -o jsonpath='{.status.webhookSecret}'
```

### 5. Configure GitHub Webhook

1. Go to ArchonAgent repository settings
2. Navigate to Webhooks
3. Add webhook with:
   - **URL**: From RepoBinding status `webhookURL`
   - **Content Type**: `application/json`
   - **Secret**: From RepoBinding status `webhookSecret`
   - **Events**: Push events

## What Gets Provisioned Automatically

**By AphexCLI:**
- ✅ Pipeline in `archon-ci` namespace
- ✅ ServiceAccount `pipeline-runner`
- ✅ RBAC for pipeline execution

**By RepoBinding Controller:**
- ✅ TriggerBinding `github-push-binding`
- ✅ TriggerTemplate `archon-ci-trigger-template`
- ✅ EventListener `github-listener`
- ✅ Webhook Secret with secure token
- ✅ Ingress route for webhook delivery

## Testing the Pipeline

### Manual Test
```bash
# Create test PipelineRun
kubectl create -f - <<EOF
apiVersion: tekton.dev/v1beta1
kind: PipelineRun
metadata:
  generateName: archon-test-
  namespace: archon-ci
spec:
  pipelineRef:
    name: archon-pipeline
  params:
    - name: git-url
      value: "https://github.com/bdchatham/ArchonAgent"
    - name: git-revision
      value: "main"
  workspaces:
    - name: source
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 1Gi
EOF
```

### Webhook Test
```bash
# Push to ArchonAgent repository
git push origin main

# Check pipeline execution
kubectl get pipelineruns -n archon-ci
kubectl logs -f pipelinerun/<run-name> -n archon-ci
```

## Pipeline Execution Flow

1. **Git Push** → GitHub webhook → EventListener
2. **EventListener** → TriggerTemplate → PipelineRun
3. **PipelineRun** executes tasks:
   - `clone-repo` - Fetch source code
   - `run-tests` - Execute pytest with coverage
   - `build-query-image` - Build query service container
   - `build-monitor-image` - Build monitor container
   - `deploy-manifests` - Apply Kubernetes manifests

## Troubleshooting

**Pipeline not found:**
```bash
# Reinstall pipeline
aphex pipeline create archon-pipeline --file aphex-pipeline/pipeline.yaml --namespace archon-ci
```

**Webhook not triggering:**
```bash
# Check EventListener
kubectl get eventlistener -n archon-ci
kubectl logs -l app.kubernetes.io/name=eventlistener -n archon-ci

# Check RepoBinding status
kubectl describe repobinding archon-binding -n pipeline-system
```

**Build failures:**
```bash
# Check PipelineRun logs
kubectl get pipelineruns -n archon-ci
kubectl describe pipelinerun <run-name> -n archon-ci
kubectl logs pipelinerun/<run-name> -n archon-ci
```
