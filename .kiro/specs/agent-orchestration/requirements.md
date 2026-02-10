# Requirements Document

## Introduction

This specification defines the Agent Orchestration layer for the Archon Agent Pipeline - Phase 3 of the overall pipeline architecture. This child spec implements the autonomous development workflow that processes GitHub issues through to pull requests without manual intervention.

**Parent Spec Reference:** `.kiro/specs/archon-agent-pipeline/` (Requirements 15-17)

The agent orchestration layer enables:
- Automated GitHub issue intake and classification
- Workspace provisioning with required context
- Kiro CLI handoff for autonomous implementation
- Pull request creation with approach summaries
- Reliable state machine-based pipeline orchestration

### Knowledge Architecture

The agent orchestration relies on a two-layer knowledge system:

**Layer 1: Vector Store (Semantic Search)**
- Contains embeddings of `.archon.md` files (natural language summaries generated from SCIP output)
- Each chunk includes ARN metadata linking to the code graph
- Enables plain English queries to find relevant code context

**Layer 2: Code Graph (SCIP Relationships)**
- PostgreSQL database with GraphQL API
- Stores SCIP-derived relationships: contains, references, implements, extends, imports
- Enables traversal from ARNs to related code symbols

**RAG Query Flow:**
1. Agent receives plain English question
2. Vector search returns relevant chunks with ARN metadata
3. ARNs are used to query GraphQL for code relationships
4. Combined context (semantic + structural) informs the response

### Deployment Model

The Archon product team deploys agent orchestration on the Aphex platform as follows:

**Step 1: Platform Foundation (Provided by Aphex)**
- The Aphex platform provides the `KnowledgeBase` CRD and `AphexKnowledgeBaseController`
- The CRD evolves to support SCIP-driven knowledge (not just `.kiro/docs` ingestion)

**Step 2: Create KnowledgeBase Resource (SCIP-Driven)**
```yaml
apiVersion: aphex.io/v1alpha1
kind: KnowledgeBase
metadata:
  name: archon-workspace
  namespace: archon-system
spec:
  displayName: "Archon Workspace Knowledge"
  repositories:
    - url: https://github.com/org/ArchonAgent
      branch: main
    - url: https://github.com/org/ArchonDocumentationMCPTools
      branch: main
  # SCIP-driven knowledge configuration
  scipIndexing:
    enabled: true
    languages: [go, typescript, python]
  vectorStore:
    source: archon-docs  # Sync from .archon.md files
    embeddingModel: BAAI/bge-base-en-v1.5
  codeGraph:
    enabled: true
    graphqlEndpoint: http://code-graph.archon-system:8080/graphql
  mcp:
    image: archon-mcp-server:latest
    port: 8080
```

**Step 3: Documentation Generation Pipeline**
- On code submission, SCIP indexing runs via ArchonDocumentationMCPTools
- SCIP output generates `.archon.md` files (natural language summaries with ARN references)
- Knowledge Base syncs `.archon.md` content to vector store with ARN metadata
- SCIP relationships sync to code graph

**Step 4: Deploy Agent Orchestration**
The agent orchestration is deployed as a separate workload that:
- References the `KnowledgeBase` resource by name
- Queries vector store for semantic search (returns ARNs)
- Queries code graph for relationship traversal (using ARNs)
- Combines both layers for rich context

### Architecture Context

This component is designed to integrate with the existing platform architecture:

**Platform Integration:**
- **KnowledgeBase CRD**: Evolves to support SCIP-driven knowledge with two-layer storage (vector + graph)
- **Knowledge_Provider Interface**: Abstracts the two-layer query pattern (vector search → ARN → graph traversal)
- **AphexKnowledgeBaseController**: Manages KnowledgeBase resources, SCIP indexing triggers, and sync pipelines

**External Integrations:**
- **Kiro CLI**: Executes implementation tasks in provisioned workspaces
- **GitHub API**: Receives webhooks and creates PRs/comments
- **ArchonDocumentationMCPTools**: Generates SCIP indexes and `.archon.md` documentation

### Design Principles

1. **Two-Layer Knowledge**: Semantic search (vector) + structural traversal (graph) work together
2. **ARN-Centric**: ARNs are the bridge between vector results and code graph queries
3. **SCIP-Driven**: Documentation is generated from SCIP output, not manually maintained
4. **Resource-Oriented**: Agent pipelines reference KnowledgeBase resources by name
5. **Kubernetes-Native**: State persistence and event emission use Kubernetes primitives

## Glossary

- **Issue_Intake_Agent**: Component that receives GitHub webhook events and classifies issues using LLM
- **Provisioning_Agent**: Component that creates filesystem workspaces with required packages and context
- **Agent_Pipeline**: The complete orchestration flow from issue to PR
- **Pipeline_State_Machine**: State machine tracking issue progress through stages
- **Workspace**: A filesystem folder containing cloned packages and context files for Kiro
- **Issue_Classification**: LLM-generated categorization of issue type and extracted requirements
- **Clarification_Request**: Comment posted to GitHub when issue lacks sufficient detail
- **Approach_Summary**: Description of implementation approach included in PR body
- **Pipeline_Event**: Observable event emitted for monitoring and alerting
- **Stage**: A discrete step in the pipeline (intake, provisioning, implementation, pr_creation)
- **KnowledgeBase**: A Kubernetes custom resource (CRD) that defines repositories and their SCIP-driven knowledge configuration
- **Knowledge_Provider**: An interface abstraction for the two-layer query pattern (vector + graph)
- **ARN**: Archon Resource Name - deterministic identifier linking vector results to code graph nodes

## Implementation Phases

This workstream spans multiple packages and is organized into phases:

### Phase 3A: Core Pipeline Infrastructure
**Package:** ArchonAgent
**Focus:** GitHub integration, state machine, basic pipeline flow

- Requirement 1: GitHub Webhook Receiver
- Requirement 7: Pipeline State Machine
- Requirement 8: State Persistence
- Requirement 9: Pipeline Events
- Requirement 10: Configuration Management
- Requirement 11: GitHub API Client

### Phase 3B: Issue Processing & Classification
**Package:** ArchonAgent
**Focus:** LLM-based issue classification and clarification

- Requirement 2: Issue Classification
- Requirement 3: Clarification Request

### Phase 3C: Knowledge Integration
**Package:** ArchonAgent + AphexKnowledgeBaseController
**Focus:** Two-layer knowledge provider and CRD evolution

- Requirement 12: Knowledge Provider Interface
- Requirement 13: KnowledgeBase CRD Evolution (new)

### Phase 3D: Workspace & Kiro Integration
**Package:** ArchonAgent
**Focus:** Workspace provisioning and Kiro CLI handoff

- Requirement 4: Workspace Provisioning
- Requirement 5: Kiro CLI Invocation
- Requirement 6: Pull Request Creation

## Requirements

### Phase 3A: Core Pipeline Infrastructure

### Requirement 1: GitHub Webhook Receiver

**User Story:** As a platform operator, I want a webhook endpoint that receives GitHub issue events, so that the pipeline can automatically process new issues.

#### Acceptance Criteria

1. THE Webhook_Receiver SHALL expose an HTTP POST endpoint at `/webhooks/github`
2. THE Webhook_Receiver SHALL trust that signature validation is performed by the Tekton EventListener
3. THE Webhook_Receiver SHALL parse `issues` events with actions: `opened`, `edited`, `labeled`
4. WHEN an `issues.opened` event is received THEN the Webhook_Receiver SHALL enqueue the issue for intake processing
5. THE Webhook_Receiver SHALL extract: issue number, title, body, labels, repository, author from the event payload
6. THE Webhook_Receiver SHALL acknowledge webhooks within 10 seconds to prevent GitHub retries

### Requirement 7: Pipeline State Machine

**User Story:** As a platform operator, I want issue progress tracked through a state machine, so that the pipeline is reliable and observable.

#### Acceptance Criteria

1. THE Pipeline_State_Machine SHALL track issues through stages: `pending`, `intake`, `clarification`, `provisioning`, `implementation`, `pr_creation`, `completed`, `failed`
2. THE Pipeline_State_Machine SHALL enforce valid state transitions
3. THE Pipeline_State_Machine SHALL record timestamps for each state transition
4. THE Pipeline_State_Machine SHALL store error details when transitioning to `failed` state
5. THE Pipeline_State_Machine SHALL support querying issues by current state
6. THE Pipeline_State_Machine SHALL support manual state transitions for recovery

### Requirement 8: State Persistence

**User Story:** As a platform operator, I want pipeline state persisted to survive restarts, so that in-progress work is not lost.

#### Acceptance Criteria

1. THE Pipeline_State_Machine SHALL persist state to PostgreSQL
2. THE state schema SHALL include: issue_id, repository, current_state, state_history, classification, workspace_path, pr_number, created_at, updated_at
3. THE Pipeline_State_Machine SHALL use database transactions for state updates
4. WHEN the service restarts THEN the Pipeline_State_Machine SHALL resume processing from persisted state
5. THE Pipeline_State_Machine SHALL implement optimistic locking to prevent concurrent updates
6. THE state history SHALL be queryable for debugging and auditing

### Requirement 9: Pipeline Events

**User Story:** As a platform operator, I want the pipeline to emit events for monitoring, so that I can observe and alert on pipeline health.

#### Acceptance Criteria

1. THE Agent_Pipeline SHALL emit events for: state transitions, errors, completions, timeouts
2. THE events SHALL include: event_type, issue_id, repository, timestamp, details
3. THE Agent_Pipeline SHALL emit events to a configurable event sink (Kubernetes events, metrics, or message queue)
4. THE events SHALL be structured for easy parsing by monitoring tools
5. THE Agent_Pipeline SHALL emit metrics: issues_processed, issues_failed, average_processing_time, issues_by_state
6. THE metrics SHALL be exposed in Prometheus format at `/metrics` endpoint

### Requirement 10: Configuration Management

**User Story:** As a platform operator, I want the pipeline configurable via environment variables and config files, so that I can tune behavior without code changes.

#### Acceptance Criteria

1. THE Agent_Pipeline SHALL read configuration from environment variables
2. THE configuration SHALL include: GitHub webhook secret, GitHub API token, workspace base path, kiro-cli path, timeouts, retention periods
3. THE configuration SHALL include: LLM endpoint URL, model name
4. THE configuration SHALL reference a KnowledgeBase resource by namespace and name for context retrieval
5. THE configuration SHALL support per-repository overrides via config file
6. THE Agent_Pipeline SHALL validate configuration on startup and fail fast if invalid
7. THE Agent_Pipeline SHALL log configuration values (redacting secrets) on startup

### Requirement 11: GitHub API Client

**User Story:** As an agent system, I want a GitHub API client for interacting with issues and PRs, so that the pipeline can communicate results.

#### Acceptance Criteria

1. THE GitHub_Client SHALL authenticate using a GitHub App or Personal Access Token
2. THE GitHub_Client SHALL support: creating comments, adding labels, removing labels, creating PRs, requesting reviewers
3. THE GitHub_Client SHALL implement rate limiting to respect GitHub API limits
4. THE GitHub_Client SHALL retry transient failures with exponential backoff
5. WHEN GitHub API returns an error THEN the GitHub_Client SHALL log the error with request details
6. THE GitHub_Client SHALL support both github.com and GitHub Enterprise Server endpoints

### Phase 3B: Issue Processing & Classification

### Requirement 2: Issue Classification

**User Story:** As a developer, I want issues automatically classified by type and requirements extracted, so that the pipeline can determine appropriate handling.

#### Acceptance Criteria

1. THE Issue_Intake_Agent SHALL use an LLM to classify issue type from: `feature`, `bug`, `documentation`, `infrastructure`, `unknown`
2. THE Issue_Intake_Agent SHALL extract structured requirements from the issue body
3. THE Issue_Intake_Agent SHALL identify affected packages from issue content and labels
4. THE Issue_Intake_Agent SHALL assess issue completeness on a scale of 1-5
5. WHEN issue completeness is below 3 THEN the Issue_Intake_Agent SHALL generate clarification questions
6. THE Issue_Intake_Agent SHALL store classification results in the pipeline state
7. THE Issue_Intake_Agent SHALL complete classification within 30 seconds

### Requirement 3: Clarification Request

**User Story:** As a developer, I want the agent to request clarification on incomplete issues, so that implementation can proceed with sufficient detail.

#### Acceptance Criteria

1. WHEN an issue lacks sufficient detail THEN the Issue_Intake_Agent SHALL post a comment requesting clarification
2. THE clarification comment SHALL include specific questions about missing information
3. THE clarification comment SHALL be formatted as a GitHub-flavored markdown checklist
4. THE Issue_Intake_Agent SHALL add a `needs-clarification` label to the issue
5. WHEN an `issues.edited` event is received for an issue with `needs-clarification` label THEN the Issue_Intake_Agent SHALL re-evaluate completeness
6. WHEN completeness improves to 3 or above THEN the Issue_Intake_Agent SHALL remove the `needs-clarification` label and proceed

### Phase 3C: Knowledge Integration

### Requirement 12: Knowledge Provider Interface

**User Story:** As a platform architect, I want a pluggable knowledge provider interface, so that the two-layer knowledge system (vector + graph) can be queried consistently.

#### Acceptance Criteria

1. THE Knowledge_Provider interface SHALL define methods for: semantic_search, graph_query, resolve_arn, and health_check
2. THE semantic_search method SHALL accept a query string and return ranked results with content, score, and ARN metadata
3. THE graph_query method SHALL accept ARNs and relationship types, returning related code symbols
4. THE resolve_arn method SHALL accept an ARN and return file path, line number, and symbol information
5. THE Agent_Pipeline SHALL resolve Knowledge_Provider implementations from KnowledgeBase resource configuration
6. THE default Knowledge_Provider implementation SHALL query the vector store for semantic search and the GraphQL API for graph traversal
7. THE Knowledge_Provider SHALL support the combined query pattern: semantic search → extract ARNs → graph traversal → combined context

### Requirement 13: KnowledgeBase CRD Evolution

**User Story:** As a platform architect, I want the KnowledgeBase CRD to support SCIP-driven knowledge configuration, so that the two-layer knowledge system can be declaratively managed.

#### Acceptance Criteria

1. THE KnowledgeBase CRD spec SHALL include a `scipIndexing` field with: enabled (bool), languages (list of strings)
2. THE KnowledgeBase CRD spec SHALL include a `vectorStore` field with: source (enum: kiro-docs, archon-docs), embeddingModel (string)
3. THE KnowledgeBase CRD spec SHALL include a `codeGraph` field with: enabled (bool), graphqlEndpoint (string)
4. THE AphexKnowledgeBaseController SHALL reconcile vector store configuration when `vectorStore` field changes
5. THE AphexKnowledgeBaseController SHALL reconcile code graph configuration when `codeGraph` field changes
6. THE KnowledgeBase status SHALL include: vectorStoreReady (bool), codeGraphReady (bool), lastSyncTime (timestamp)

### Phase 3D: Workspace & Kiro Integration

### Requirement 4: Workspace Provisioning

**User Story:** As an agent system, I want to provision workspaces with required packages and context, so that Kiro has everything needed for implementation.

#### Acceptance Criteria

1. THE Provisioning_Agent SHALL create a filesystem folder at a configurable base path
2. THE Provisioning_Agent SHALL clone required packages from Git into the workspace
3. THE Provisioning_Agent SHALL create a `context.md` file containing: issue details, classification results, relevant documentation
4. THE Provisioning_Agent SHALL query the configured Knowledge_Provider for relevant context and include it in `context.md`
5. THE Provisioning_Agent SHALL resolve the Knowledge_Provider from the KnowledgeBase resource referenced in the pipeline configuration
6. THE Provisioning_Agent SHALL create a `task.md` file with the implementation task summary
7. THE Provisioning_Agent SHALL set appropriate file permissions for the workspace
8. THE Provisioning_Agent SHALL clean up workspaces older than a configurable retention period

### Requirement 5: Kiro CLI Invocation

**User Story:** As an agent system, I want to invoke Kiro CLI with the provisioned workspace, so that implementation happens autonomously.

#### Acceptance Criteria

1. THE Agent_Pipeline SHALL invoke `kiro-cli` as a subprocess with the workspace path
2. THE Agent_Pipeline SHALL pass the task summary via stdin or task file
3. THE Agent_Pipeline SHALL capture stdout and stderr from kiro-cli execution
4. THE Agent_Pipeline SHALL enforce a configurable timeout for kiro-cli execution
5. WHEN kiro-cli exits with code 0 THEN the Agent_Pipeline SHALL proceed to PR creation
6. WHEN kiro-cli exits with non-zero code THEN the Agent_Pipeline SHALL log the error and transition to failed state
7. THE Agent_Pipeline SHALL stream kiro-cli output to logs for observability

### Requirement 6: Pull Request Creation

**User Story:** As a developer, I want PRs automatically created with implementation results, so that changes can be reviewed and merged.

#### Acceptance Criteria

1. WHEN kiro-cli completes successfully THEN the Agent_Pipeline SHALL create a PR in the target repository
2. THE PR title SHALL include the original issue number and a summary
3. THE PR body SHALL include: approach summary, files changed, link to original issue
4. THE Agent_Pipeline SHALL link the PR to the original issue using GitHub keywords
5. THE Agent_Pipeline SHALL add appropriate labels to the PR based on issue classification
6. THE Agent_Pipeline SHALL request reviewers based on CODEOWNERS or configuration
7. THE Agent_Pipeline SHALL comment on the original issue with a link to the created PR

