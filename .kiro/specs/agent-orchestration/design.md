# Design Document: Agent Orchestration

## Overview

The Agent Orchestration layer implements an autonomous development workflow that processes GitHub issues through to pull requests. It integrates with the Aphex platform's KnowledgeBase CRD to leverage the two-layer knowledge system (vector store + code graph) for intelligent context retrieval.

This design covers Phase 3 of the Archon Agent Pipeline, organized into four sub-phases:
- **Phase 3A**: Core pipeline infrastructure (webhook, state machine, persistence)
- **Phase 3B**: Issue processing and LLM-based classification
- **Phase 3C**: Knowledge integration (two-layer provider interface, CRD evolution)
- **Phase 3D**: Workspace provisioning and Kiro CLI handoff

### Design Principles

1. **Two-Layer Knowledge**: Semantic search (vector) + structural traversal (graph) work together via ARNs
2. **State Machine Reliability**: All pipeline state is persisted and recoverable
3. **Kubernetes-Native**: Leverages CRDs, events, and standard patterns
4. **Observability-First**: Metrics, events, and structured logging throughout

### Webhook Ingress Architecture

GitHub webhooks are received through the existing Tekton EventListener infrastructure:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GitHub App                                      │
│                    (Org-level webhook configuration)                         │
│                                  │                                           │
│                                  ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Cloudflare Tunnel                                 │   │
│  │                    (archon.webhooks.home.local)                      │   │
│  └──────────────────────────────┬──────────────────────────────────────┘   │
└─────────────────────────────────┼───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                                   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Tekton EventListener                              │   │
│  │                    (Created during org setup)                        │   │
│  │                                                                      │   │
│  │  Triggers:                                                           │   │
│  │  ┌─────────────────────────────────────────────────────────────┐    │   │
│  │  │  CI/CD Pipeline Triggers (existing)                          │    │   │
│  │  │  - push events → build/test pipelines                        │    │   │
│  │  └─────────────────────────────────────────────────────────────┘    │   │
│  │  ┌─────────────────────────────────────────────────────────────┐    │   │
│  │  │  Agent Orchestration Trigger (NEW)                           │    │   │
│  │  │  Filter: issues events + "archon-automate" label             │    │   │
│  │  │  → Forward to agent-pipeline-service                         │    │   │
│  │  └─────────────────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────┬──────────────────────────────────────┘   │
│                                 │                                            │
│                                 ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Service: agent-pipeline (ClusterIP:8080)                            │   │
│  │  → Deployment: agent-pipeline (FastAPI)                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Trigger Logic:**

The EventListener filters issue events and forwards them directly to the agent-pipeline service using CloudEvents sink:

```yaml
# EventListener configuration
apiVersion: triggers.tekton.dev/v1beta1
kind: EventListener
metadata:
  name: archon-webhooks
  namespace: archon-system
spec:
  serviceAccountName: tekton-triggers-sa
  triggers:
    # Existing CI/CD triggers...
    
    # Agent orchestration trigger
    - name: agent-orchestration
      interceptors:
        - ref:
            name: github
          params:
            - name: secretRef
              value:
                secretName: github-webhook-secret
                secretKey: secret
            - name: eventTypes
              value: ["issues"]
        - ref:
            name: cel
          params:
            - name: filter
              # Filter: issue event with archon-automate label
              value: >
                body.action in ['opened', 'edited', 'labeled'] &&
                body.issue.labels.exists(l, l.name == 'archon-automate')
      # Direct HTTP forward to agent-pipeline service
      # No TriggerBinding/TriggerTemplate needed - just forward the payload
      bindings: []
      template:
        ref: agent-orchestration-forward

---
# TriggerTemplate that forwards via HTTP task
apiVersion: triggers.tekton.dev/v1beta1
kind: TriggerTemplate
metadata:
  name: agent-orchestration-forward
  namespace: archon-system
spec:
  resourcetemplates:
    - apiVersion: tekton.dev/v1beta1
      kind: TaskRun
      metadata:
        generateName: agent-forward-
      spec:
        taskSpec:
          steps:
            - name: forward
              image: curlimages/curl:latest
              script: |
                curl -X POST \
                  -H "Content-Type: application/json" \
                  -H "X-GitHub-Event: issues" \
                  -d '$(tt.params.body)' \
                  http://agent-pipeline.archon-system.svc.cluster.local:8080/webhooks/github
        params:
          - name: body
            value: $(body)
```

**How It Works:**

1. GitHub sends webhook to EventListener (via Cloudflare tunnel)
2. EventListener's GitHub interceptor validates the signature
3. CEL interceptor filters for `issues` events with `archon-automate` label
4. TriggerTemplate creates a TaskRun that curls the agent-pipeline service
5. Agent-pipeline receives the webhook payload and processes it

**Alternative: Direct Service Call (No TaskRun)**

For lower latency, the EventListener could use a custom webhook interceptor that directly calls the agent-pipeline service without creating a TaskRun. This requires a custom interceptor image but avoids TaskRun overhead.

**Label-Based Activation:**

Users opt-in to agent orchestration by adding the `archon-automate` label to an issue:
- Adding the label triggers the pipeline
- Removing the label stops further processing
- This gives users explicit control over which issues are automated

**Alternative: Repository-Based Activation:**

Instead of labels, the trigger could filter by repository (repos configured in the KnowledgeBase):

```yaml
# CEL filter for configured repositories
- name: filter
  value: >
    body.action in ['opened', 'edited', 'labeled'] &&
    body.repository.full_name in ['org/repo1', 'org/repo2']
```

The repository list could be dynamically populated from the KnowledgeBase resource.

## Architecture

### System Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              GitHub                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │   Issues    │    │    PRs      │    │  Webhooks   │                      │
│  └──────┬──────┘    └──────▲──────┘    └──────┬──────┘                      │
└─────────┼──────────────────┼──────────────────┼─────────────────────────────┘
          │                  │                  │
          │                  │                  ▼
┌─────────┼──────────────────┼─────────────────────────────────────────────────┐
│         │                  │         Agent Orchestration Service             │
│         │                  │                                                  │
│  ┌──────▼──────┐    ┌──────┴──────┐    ┌─────────────┐                      │
│  │  Webhook    │    │   GitHub    │    │   Issue     │                      │
│  │  Receiver   │───▶│   Client    │◀───│  Classifier │                      │
│  └──────┬──────┘    └─────────────┘    └──────┬──────┘                      │
│         │                                      │                             │
│         ▼                                      ▼                             │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │              Pipeline State Machine                  │                    │
│  │  pending → intake → clarification → provisioning    │                    │
│  │         → implementation → pr_creation → completed  │                    │
│  └──────────────────────┬──────────────────────────────┘                    │
│                         │                                                    │
│         ┌───────────────┼───────────────┐                                   │
│         ▼               ▼               ▼                                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                           │
│  │ Provisioner │ │ Kiro Runner │ │ PR Creator  │                           │
│  └──────┬──────┘ └──────┬──────┘ └─────────────┘                           │
│         │               │                                                    │
└─────────┼───────────────┼────────────────────────────────────────────────────┘
          │               │
          ▼               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Knowledge Provider                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    KnowledgeBase Resource                            │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │   │
│  │  │ Vector Store│  │ Code Graph  │  │ MCP Server  │                  │   │
│  │  │ (Qdrant)    │  │ (PostgreSQL)│  │             │                  │   │
│  │  └──────┬──────┘  └──────┬──────┘  └─────────────┘                  │   │
│  │         │                │                                           │   │
│  │         └────────┬───────┘                                           │   │
│  │                  ▼                                                   │   │
│  │         ┌─────────────┐                                              │   │
│  │         │ ARN-based   │                                              │   │
│  │         │ Context     │                                              │   │
│  │         └─────────────┘                                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Workspace & Kiro                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                      │
│  │  Workspace  │───▶│  Kiro CLI   │───▶│   Git       │                      │
│  │  (filesystem)│    │             │    │  Changes    │                      │
│  └─────────────┘    └─────────────┘    └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Package Structure

```
ArchonAgent/
├── src/
│   ├── orchestrator/           # Existing RAG orchestrator (Phase 1-2)
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── rag_chain.py
│   │   └── retriever.py
│   │
│   └── pipeline/               # New agent pipeline (Phase 3)
│       ├── __init__.py
│       ├── main.py             # FastAPI application entry point
│       ├── config.py           # Pipeline configuration
│       │
│       ├── webhook/            # Phase 3A: GitHub webhook handling
│       │   ├── __init__.py
│       │   ├── handler.py      # Webhook endpoint and signature validation
│       │   └── models.py       # GitHub event models
│       │
│       ├── state/              # Phase 3A: State machine and persistence
│       │   ├── __init__.py
│       │   ├── machine.py      # State machine implementation
│       │   ├── models.py       # Pipeline state models
│       │   └── repository.py   # PostgreSQL persistence
│       │
│       ├── github/             # Phase 3A: GitHub API client
│       │   ├── __init__.py
│       │   ├── client.py       # GitHub API wrapper
│       │   └── models.py       # GitHub API models
│       │
│       ├── classifier/         # Phase 3B: Issue classification
│       │   ├── __init__.py
│       │   ├── agent.py        # LLM-based classifier
│       │   └── models.py       # Classification models
│       │
│       ├── knowledge/          # Phase 3C: Knowledge provider
│       │   ├── __init__.py
│       │   ├── provider.py     # Knowledge provider interface
│       │   ├── vector.py       # Vector store client
│       │   └── graph.py        # Code graph client
│       │
│       ├── provisioner/        # Phase 3D: Workspace provisioning
│       │   ├── __init__.py
│       │   ├── workspace.py    # Workspace creation and management
│       │   └── context.py      # Context file generation
│       │
│       ├── runner/             # Phase 3D: Kiro CLI runner
│       │   ├── __init__.py
│       │   └── kiro.py         # Kiro CLI subprocess management
│       │
│       └── events/             # Phase 3A: Event emission
│           ├── __init__.py
│           ├── emitter.py      # Event emission interface
│           └── metrics.py      # Prometheus metrics
│
├── manifests/
│   ├── agent.yaml              # Existing RAG orchestrator deployment
│   └── pipeline.yaml           # New pipeline deployment
│
├── migrations/                 # PostgreSQL migrations
│   └── 001_pipeline_state.sql
│
└── tests/
    └── pipeline/
        ├── test_webhook.py
        ├── test_state_machine.py
        ├── test_classifier.py
        └── test_knowledge_provider.py
```

## Components and Interfaces

### Webhook Handler

Receives and validates GitHub webhook events.

```python
from dataclasses import dataclass
from enum import Enum

class IssueAction(Enum):
    OPENED = "opened"
    EDITED = "edited"
    LABELED = "labeled"

@dataclass
class GitHubIssueEvent:
    action: IssueAction
    issue_number: int
    title: str
    body: str
    labels: list[str]
    repository: str
    owner: str
    author: str
    
@dataclass
class WebhookValidationResult:
    valid: bool
    error: str | None = None

class WebhookHandler:
    def __init__(self, secret: str):
        self.secret = secret
    
    def validate_signature(self, payload: bytes, signature: str) -> WebhookValidationResult:
        """Validate GitHub webhook signature using HMAC-SHA256."""
        pass
    
    def parse_issue_event(self, payload: dict) -> GitHubIssueEvent | None:
        """Parse issue event from webhook payload."""
        pass
```

### Pipeline State Machine

Manages issue progression through pipeline stages.

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

class PipelineStage(Enum):
    PENDING = "pending"
    INTAKE = "intake"
    CLARIFICATION = "clarification"
    PROVISIONING = "provisioning"
    IMPLEMENTATION = "implementation"
    PR_CREATION = "pr_creation"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class StateTransition:
    from_stage: PipelineStage
    to_stage: PipelineStage
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)

@dataclass
class PipelineState:
    issue_id: str                    # Format: "{owner}/{repo}#{number}"
    repository: str
    current_stage: PipelineStage
    state_history: list[StateTransition]
    classification: dict | None = None
    workspace_path: str | None = None
    pr_number: int | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    version: int = 1                 # Optimistic locking

# Valid state transitions
VALID_TRANSITIONS = {
    PipelineStage.PENDING: [PipelineStage.INTAKE, PipelineStage.FAILED],
    PipelineStage.INTAKE: [PipelineStage.CLARIFICATION, PipelineStage.PROVISIONING, PipelineStage.FAILED],
    PipelineStage.CLARIFICATION: [PipelineStage.INTAKE, PipelineStage.PROVISIONING, PipelineStage.FAILED],
    PipelineStage.PROVISIONING: [PipelineStage.IMPLEMENTATION, PipelineStage.FAILED],
    PipelineStage.IMPLEMENTATION: [PipelineStage.PR_CREATION, PipelineStage.FAILED],
    PipelineStage.PR_CREATION: [PipelineStage.COMPLETED, PipelineStage.FAILED],
    PipelineStage.COMPLETED: [],
    PipelineStage.FAILED: [PipelineStage.PENDING],  # Manual recovery
}

class PipelineStateMachine:
    def __init__(self, repository: "StateRepository"):
        self.repository = repository
    
    async def create(self, issue_id: str, repository: str) -> PipelineState:
        """Create new pipeline state for an issue."""
        pass
    
    async def transition(
        self, 
        issue_id: str, 
        to_stage: PipelineStage,
        details: dict[str, Any] | None = None
    ) -> PipelineState:
        """Transition issue to new stage with validation."""
        pass
    
    async def get(self, issue_id: str) -> PipelineState | None:
        """Get current state for an issue."""
        pass
    
    async def list_by_stage(self, stage: PipelineStage) -> list[PipelineState]:
        """List all issues in a given stage."""
        pass
```

### State Repository

Persists pipeline state to PostgreSQL.

```python
from abc import ABC, abstractmethod

class StateRepository(ABC):
    @abstractmethod
    async def save(self, state: PipelineState) -> None:
        """Save or update pipeline state."""
        pass
    
    @abstractmethod
    async def get(self, issue_id: str) -> PipelineState | None:
        """Get pipeline state by issue ID."""
        pass
    
    @abstractmethod
    async def list_by_stage(self, stage: PipelineStage) -> list[PipelineState]:
        """List states by current stage."""
        pass
    
    @abstractmethod
    async def update_with_version(self, state: PipelineState) -> bool:
        """Update state with optimistic locking. Returns False if version conflict."""
        pass

class PostgresStateRepository(StateRepository):
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
    
    # Implementation uses asyncpg for async PostgreSQL access
```

### Issue Classifier

LLM-based issue classification and requirement extraction.

```python
from dataclasses import dataclass
from enum import Enum

class IssueType(Enum):
    FEATURE = "feature"
    BUG = "bug"
    DOCUMENTATION = "documentation"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"

@dataclass
class IssueClassification:
    issue_type: IssueType
    requirements: list[str]
    affected_packages: list[str]
    completeness_score: int  # 1-5
    clarification_questions: list[str]  # Empty if completeness >= 3

class IssueClassifier:
    def __init__(self, llm_url: str, model_name: str):
        self.llm_url = llm_url
        self.model_name = model_name
    
    async def classify(self, title: str, body: str, labels: list[str]) -> IssueClassification:
        """Classify issue using LLM."""
        pass
```

### Knowledge Provider

Two-layer knowledge retrieval interface.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SemanticSearchResult:
    content: str
    source: str
    score: float
    arn: str
    related_arns: list[str]
    symbol_name: str | None
    symbol_kind: str | None
    package: str

@dataclass
class CodeSymbol:
    arn: str
    name: str
    kind: str
    signature: str | None
    file_path: str
    line_number: int
    documentation: str | None

@dataclass
class GraphTraversalResult:
    symbol: CodeSymbol
    relationship: str  # contains, references, implements, etc.
    depth: int

@dataclass
class ResolvedARN:
    arn: str
    file_path: str
    line_number: int
    symbol_name: str | None
    symbol_kind: str | None

class KnowledgeProvider(ABC):
    @abstractmethod
    async def semantic_search(
        self, 
        query: str, 
        limit: int = 10,
        package_filter: str | None = None
    ) -> list[SemanticSearchResult]:
        """Search vector store for relevant content."""
        pass
    
    @abstractmethod
    async def graph_query(
        self,
        arns: list[str],
        relationship_types: list[str],
        depth: int = 1
    ) -> list[GraphTraversalResult]:
        """Traverse code graph from given ARNs."""
        pass
    
    @abstractmethod
    async def resolve_arn(self, arn: str) -> ResolvedARN | None:
        """Resolve ARN to file location."""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if knowledge services are available."""
        pass

class DefaultKnowledgeProvider(KnowledgeProvider):
    def __init__(
        self,
        vector_store_url: str,
        graphql_url: str
    ):
        self.vector_store_url = vector_store_url
        self.graphql_url = graphql_url
    
    async def combined_context(self, query: str) -> str:
        """
        Execute the combined query pattern:
        1. Semantic search → get ARNs
        2. Graph traversal → get related symbols
        3. Combine into rich context
        """
        # Semantic search
        results = await self.semantic_search(query)
        
        # Extract ARNs
        arns = [r.arn for r in results]
        
        # Graph traversal for related symbols
        related = await self.graph_query(
            arns, 
            ["references", "contains", "implements"],
            depth=2
        )
        
        # Combine into context string
        return self._format_context(results, related)
```

### Workspace Provisioner

Creates and manages workspaces for Kiro execution.

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class WorkspaceConfig:
    base_path: Path
    retention_days: int = 7

@dataclass
class ProvisionedWorkspace:
    path: Path
    packages: list[str]
    context_file: Path
    task_file: Path

class WorkspaceProvisioner:
    def __init__(
        self, 
        config: WorkspaceConfig,
        knowledge_provider: KnowledgeProvider
    ):
        self.config = config
        self.knowledge_provider = knowledge_provider
    
    async def provision(
        self,
        issue_id: str,
        classification: IssueClassification,
        issue_details: dict
    ) -> ProvisionedWorkspace:
        """
        Provision workspace:
        1. Create directory
        2. Clone required packages
        3. Generate context.md with knowledge retrieval
        4. Generate task.md with implementation summary
        """
        pass
    
    async def cleanup_old_workspaces(self) -> int:
        """Remove workspaces older than retention period. Returns count removed."""
        pass
```

### Kiro Runner

Manages Kiro CLI subprocess execution.

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class KiroResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

class KiroRunner:
    def __init__(self, kiro_path: str, timeout_seconds: int = 3600):
        self.kiro_path = kiro_path
        self.timeout_seconds = timeout_seconds
    
    async def run(
        self,
        workspace_path: Path,
        task_file: Path,
        log_callback: callable | None = None
    ) -> KiroResult:
        """
        Execute Kiro CLI:
        1. Start subprocess with workspace
        2. Stream output to log_callback
        3. Enforce timeout
        4. Return result
        """
        pass
```

### GitHub Client

Wrapper for GitHub API interactions.

```python
from dataclasses import dataclass

@dataclass
class PRCreateRequest:
    title: str
    body: str
    head_branch: str
    base_branch: str
    labels: list[str]
    reviewers: list[str]

@dataclass
class PRCreateResult:
    number: int
    url: str

class GitHubClient:
    def __init__(self, token: str, base_url: str = "https://api.github.com"):
        self.token = token
        self.base_url = base_url
    
    async def create_comment(
        self, 
        owner: str, 
        repo: str, 
        issue_number: int, 
        body: str
    ) -> None:
        """Create comment on issue."""
        pass
    
    async def add_label(
        self, 
        owner: str, 
        repo: str, 
        issue_number: int, 
        label: str
    ) -> None:
        """Add label to issue."""
        pass
    
    async def remove_label(
        self, 
        owner: str, 
        repo: str, 
        issue_number: int, 
        label: str
    ) -> None:
        """Remove label from issue."""
        pass
    
    async def create_pr(
        self, 
        owner: str, 
        repo: str, 
        request: PRCreateRequest
    ) -> PRCreateResult:
        """Create pull request."""
        pass
    
    async def request_reviewers(
        self, 
        owner: str, 
        repo: str, 
        pr_number: int, 
        reviewers: list[str]
    ) -> None:
        """Request reviewers for PR."""
        pass
```

### Event Emitter

Emits pipeline events for monitoring.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class EventType(Enum):
    STATE_TRANSITION = "state_transition"
    ERROR = "error"
    COMPLETION = "completion"
    TIMEOUT = "timeout"

@dataclass
class PipelineEvent:
    event_type: EventType
    issue_id: str
    repository: str
    timestamp: datetime
    details: dict

class EventEmitter(ABC):
    @abstractmethod
    async def emit(self, event: PipelineEvent) -> None:
        """Emit pipeline event."""
        pass

class MetricsEventEmitter(EventEmitter):
    """Emits events as Prometheus metrics."""
    
    def __init__(self):
        # Initialize Prometheus counters and histograms
        pass
    
    async def emit(self, event: PipelineEvent) -> None:
        # Update metrics based on event type
        pass
```

## Data Models

### PostgreSQL Schema

```sql
-- Pipeline state table
CREATE TABLE pipeline_states (
    issue_id TEXT PRIMARY KEY,           -- Format: "{owner}/{repo}#{number}"
    repository TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    classification JSONB,
    workspace_path TEXT,
    pr_number INTEGER,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    version INTEGER DEFAULT 1            -- Optimistic locking
);

-- State history table
CREATE TABLE state_transitions (
    id SERIAL PRIMARY KEY,
    issue_id TEXT NOT NULL REFERENCES pipeline_states(issue_id) ON DELETE CASCADE,
    from_stage TEXT NOT NULL,
    to_stage TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    details JSONB
);

-- Indexes
CREATE INDEX idx_pipeline_states_stage ON pipeline_states(current_stage);
CREATE INDEX idx_pipeline_states_repository ON pipeline_states(repository);
CREATE INDEX idx_state_transitions_issue ON state_transitions(issue_id);
```

### KnowledgeBase CRD Evolution

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: knowledgebases.aphex.io
spec:
  group: aphex.io
  versions:
    - name: v1alpha1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              required:
                - displayName
                - repositories
              properties:
                displayName:
                  type: string
                description:
                  type: string
                repositories:
                  type: array
                  items:
                    type: object
                    required:
                      - url
                    properties:
                      url:
                        type: string
                      branch:
                        type: string
                        default: main
                      paths:
                        type: array
                        items:
                          type: string
                
                # SCIP-driven knowledge configuration
                scipIndexing:
                  type: object
                  properties:
                    enabled:
                      type: boolean
                      default: false
                    languages:
                      type: array
                      items:
                        type: string
                        enum: [go, typescript, python, java]
                
                vectorStore:
                  type: object
                  properties:
                    source:
                      type: string
                      enum: [kiro-docs, archon-docs]
                      default: archon-docs
                    embeddingModel:
                      type: string
                      default: BAAI/bge-base-en-v1.5
                    collectionName:
                      type: string
                
                codeGraph:
                  type: object
                  properties:
                    enabled:
                      type: boolean
                      default: false
                    graphqlEndpoint:
                      type: string
                
                mcp:
                  type: object
                  properties:
                    image:
                      type: string
                    port:
                      type: integer
                      default: 8080
                    replicas:
                      type: integer
                      default: 1
                    queryServiceURL:
                      type: string
            
            status:
              type: object
              properties:
                phase:
                  type: string
                message:
                  type: string
                lastReconcileTime:
                  type: string
                vectorStoreReady:
                  type: boolean
                codeGraphReady:
                  type: boolean
                lastSyncTime:
                  type: string
                mcp:
                  type: object
                  properties:
                    deployed:
                      type: boolean
                    serviceName:
                      type: string
                    serviceURL:
                      type: string
                    readyReplicas:
                      type: integer
```

### Configuration Model

```python
from pydantic_settings import BaseSettings

class PipelineSettings(BaseSettings):
    # GitHub configuration
    github_webhook_secret: str
    github_token: str
    github_base_url: str = "https://api.github.com"
    
    # Workspace configuration
    workspace_base_path: str = "/var/lib/archon/workspaces"
    workspace_retention_days: int = 7
    
    # Kiro configuration
    kiro_cli_path: str = "/usr/local/bin/kiro-cli"
    kiro_timeout_seconds: int = 3600
    
    # LLM configuration
    llm_url: str
    llm_model: str = "Qwen/Qwen2.5-Coder-14B-Instruct-GPTQ-Int4"
    
    # Knowledge Base configuration
    knowledge_base_namespace: str = "archon-system"
    knowledge_base_name: str = "archon-workspace"
    
    # Database configuration
    database_url: str
    
    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8080
    
    class Config:
        env_prefix = "PIPELINE_"
```



## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Issue Event Parsing

*For any* valid GitHub issue event payload with action `opened`, `edited`, or `labeled`, the webhook handler SHALL successfully parse the event into a structured `GitHubIssueEvent` object.

**Validates: Requirement 1.3**

### Property 2: Issue Field Extraction

*For any* parsed GitHub issue event, the extracted data SHALL include all required fields: issue number, title, body, labels, repository, and author, with values matching the original payload.

**Validates: Requirement 1.5**

### Property 3: Classification Output Validation

*For any* issue classification result, the issue type SHALL be one of the valid enum values (`feature`, `bug`, `documentation`, `infrastructure`, `unknown`) and the completeness score SHALL be an integer in the range 1-5.

**Validates: Requirements 2.1, 2.4**

### Property 4: Clarification Question Generation

*For any* issue with completeness score below 3, the classifier SHALL generate a non-empty list of clarification questions.

**Validates: Requirement 2.5**

### Property 5: Clarification Comment Structure

*For any* clarification comment posted to GitHub, the comment SHALL contain at least one question and SHALL be formatted as a GitHub-flavored markdown checklist (lines starting with `- [ ]`).

**Validates: Requirements 3.2, 3.3**

### Property 6: Label State Consistency

*For any* issue that transitions through clarification, the `needs-clarification` label SHALL be added when completeness is below 3 and removed when completeness reaches 3 or above.

**Validates: Requirements 3.4, 3.6**

### Property 7: State Transition Validation

*For any* state transition request, the state machine SHALL only allow transitions defined in the valid transitions map, rejecting invalid transitions with an error.

**Validates: Requirements 7.1, 7.2**

### Property 8: State Transition Timestamps

*For any* successful state transition, the state machine SHALL record a timestamp in the state history that is greater than or equal to the previous transition timestamp.

**Validates: Requirement 7.3**

### Property 9: Failed State Error Storage

*For any* transition to the `failed` state, the pipeline state SHALL contain a non-empty error message describing the failure.

**Validates: Requirement 7.4**

### Property 10: State Query Correctness

*For any* set of pipeline states, querying by stage SHALL return exactly the states with that current stage, with no false positives or negatives.

**Validates: Requirement 7.5**

### Property 11: State Persistence Round-Trip

*For any* pipeline state saved to the database, retrieving it by issue ID SHALL return an equivalent state with all fields preserved.

**Validates: Requirements 8.1, 8.2**

### Property 12: State Transactional Atomicity

*For any* state update operation, either all changes (state, history, timestamps) are persisted together, or none are persisted (no partial updates).

**Validates: Requirement 8.3**

### Property 13: State Restart Recovery

*For any* pipeline state persisted before a service restart, the state SHALL be recoverable after restart with all fields intact.

**Validates: Requirement 8.4**

### Property 14: State Optimistic Locking

*For any* concurrent update attempts on the same pipeline state, exactly one SHALL succeed and others SHALL fail with a version conflict error.

**Validates: Requirement 8.5**

### Property 15: Knowledge Provider Return Structure

*For any* semantic search, graph query, or ARN resolution call, the returned results SHALL contain all required metadata fields (ARN, content/symbol info, scores where applicable).

**Validates: Requirements 12.2, 12.3, 12.4**

### Property 16: Knowledge Provider Combined Query

*For any* combined context query, the result SHALL include both semantic search results and graph traversal results, with ARNs linking the two layers.

**Validates: Requirement 12.7**

## Error Handling

### Webhook Errors

| Error Condition | Response | Recovery |
|-----------------|----------|----------|
| Invalid signature | HTTP 401, log rejection | GitHub will retry |
| Malformed payload | HTTP 400, log error | GitHub will retry |
| Unknown event type | HTTP 200, ignore | No action needed |
| Database unavailable | HTTP 503, log error | GitHub will retry |

### Classification Errors

| Error Condition | Response | Recovery |
|-----------------|----------|----------|
| LLM timeout | Transition to failed state | Manual retry |
| LLM error response | Transition to failed state | Manual retry |
| Invalid LLM output | Use default classification | Log warning |

### State Machine Errors

| Error Condition | Response | Recovery |
|-----------------|----------|----------|
| Invalid transition | Reject with error | Caller handles |
| Version conflict | Return conflict error | Caller retries |
| Database error | Propagate error | Caller handles |

### Knowledge Provider Errors

| Error Condition | Response | Recovery |
|-----------------|----------|----------|
| Vector store unavailable | Return empty results | Degrade gracefully |
| GraphQL error | Return empty results | Degrade gracefully |
| Invalid ARN | Return None | Caller handles |

### Workspace Errors

| Error Condition | Response | Recovery |
|-----------------|----------|----------|
| Git clone failure | Transition to failed state | Manual retry |
| Disk full | Transition to failed state | Cleanup old workspaces |
| Permission denied | Transition to failed state | Fix permissions |

### Kiro Errors

| Error Condition | Response | Recovery |
|-----------------|----------|----------|
| Timeout | Transition to failed state | Manual retry with longer timeout |
| Non-zero exit | Transition to failed state | Review logs, manual retry |
| Process crash | Transition to failed state | Manual retry |

### GitHub API Errors

| Error Condition | Response | Recovery |
|-----------------|----------|----------|
| Rate limited | Retry with backoff | Automatic |
| Auth failure | Log error, fail operation | Fix credentials |
| Network error | Retry with backoff | Automatic |

## Testing Strategy

### Dual Testing Approach

This specification requires both unit tests and property-based tests:

- **Unit tests**: Verify specific examples, edge cases, and error conditions
- **Property tests**: Verify universal properties across all valid inputs

### Property-Based Testing Configuration

- **Library**: Hypothesis (Python)
- **Minimum iterations**: 100 per property test
- **Tag format**: `Feature: agent-orchestration, Property N: <property_text>`

### Test Categories

#### Webhook Handler Tests

**Property Tests:**
- Property 1: Webhook signature validation
- Property 2: Issue event parsing
- Property 3: Issue field extraction

**Unit Tests:**
- Edge cases: empty payload, missing fields, unicode content
- Error cases: malformed JSON, unknown event types

#### Issue Classifier Tests

**Property Tests:**
- Property 4: Classification output validation
- Property 5: Clarification question generation

**Unit Tests:**
- Edge cases: empty body, very long content
- Error cases: LLM timeout, invalid response

#### State Machine Tests

**Property Tests:**
- Property 8: State transition validation
- Property 9: State transition timestamps
- Property 10: Failed state error storage
- Property 11: State query correctness
- Property 12: State persistence round-trip
- Property 13: State transactional atomicity
- Property 14: State restart recovery
- Property 15: State optimistic locking

**Unit Tests:**
- Edge cases: rapid transitions, concurrent updates
- Error cases: database failures, version conflicts

#### Knowledge Provider Tests

**Property Tests:**
- Property 16: Knowledge provider return structure
- Property 17: Knowledge provider combined query

**Unit Tests:**
- Edge cases: empty results, large result sets
- Error cases: service unavailable, timeout

### Test Data Generation

For property-based tests, generate:
- Random valid webhook payloads with varying content
- Random issue titles and bodies with unicode
- Random state transition sequences
- Random ARNs and query strings

### Integration Tests

Integration tests verify end-to-end flows:
- Webhook → Classification → State update
- State machine → Database persistence → Recovery
- Knowledge provider → Vector store → Graph traversal
- Workspace provisioning → Kiro execution → PR creation

