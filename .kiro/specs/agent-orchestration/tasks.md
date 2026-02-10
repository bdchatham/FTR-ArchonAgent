# Implementation Plan: Agent Orchestration

## Overview

This implementation plan covers Phase 3 of the Archon Agent Pipeline, organized into four sub-phases. Each phase builds incrementally on the previous, with checkpoints to validate progress.

**Implementation Language:** Python (consistent with existing ArchonAgent codebase)

## Tasks

### Phase 3A: Core Pipeline Infrastructure

- [x] 1. Set up pipeline module structure
  - [x] 1.1 Create `src/pipeline/` directory structure with `__init__.py` files
    - Create directories: webhook, state, github, classifier, knowledge, provisioner, runner, events
    - _Requirements: Project structure from design_
  
  - [x] 1.2 Create `src/pipeline/config.py` with PipelineSettings
    - Define all configuration fields using pydantic-settings
    - Include validation for required fields
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
  
  - [x] 1.3 Create `src/pipeline/main.py` FastAPI application entry point
    - Set up FastAPI app with lifespan management
    - Add health and ready endpoints
    - _Requirements: 9.6_

- [x] 2. Implement webhook handler
  - [x] 2.1 Create `src/pipeline/webhook/models.py` with GitHub event models
    - Define GitHubIssueEvent, IssueAction enum
    - _Requirements: 1.4, 1.6_
  
  - [x] 2.2 Create `src/pipeline/webhook/handler.py` with event parsing
    - Parse issues events (signature already validated by EventListener)
    - Extract issue data and enqueue for processing
    - _Requirements: 1.4, 1.5, 1.6_
  
  - [x] 2.3 Write property tests for event parsing
    - **Property 1: Issue Event Parsing**
    - **Property 2: Issue Field Extraction**
    - **Validates: Requirements 1.3, 1.5**

- [x] 3. Implement pipeline state machine
  - [x] 3.1 Create `src/pipeline/state/models.py` with state models
    - Define PipelineStage enum, StateTransition, PipelineState dataclasses
    - Define VALID_TRANSITIONS map
    - _Requirements: 7.1, 7.2_
  
  - [x] 3.2 Create `src/pipeline/state/machine.py` with state machine logic
    - Implement transition validation
    - Implement timestamp recording
    - Implement error storage for failed state
    - _Requirements: 7.2, 7.3, 7.4, 7.6_
  
  - [x] 3.3 Write property tests for state transitions
    - **Property 7: State Transition Validation**
    - **Property 8: State Transition Timestamps**
    - **Property 9: Failed State Error Storage**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**

- [x] 4. Implement state persistence
  - [x] 4.1 Create `migrations/001_pipeline_state.sql` with PostgreSQL schema
    - Create pipeline_states and state_transitions tables
    - Add indexes for efficient queries
    - _Requirements: 8.1, 8.2_
  
  - [x] 4.2 Create `src/pipeline/state/repository.py` with PostgreSQL repository
    - Implement save, get, list_by_stage methods
    - Implement optimistic locking with version field
    - Use asyncpg for async database access
    - _Requirements: 8.1, 8.3, 8.5_
  
  - [x] 4.3 Write property tests for state persistence
    - **Property 10: State Query Correctness**
    - **Property 11: State Persistence Round-Trip**
    - **Property 12: State Transactional Atomicity**
    - **Property 14: State Optimistic Locking**
    - **Validates: Requirements 7.5, 8.1, 8.2, 8.3, 8.5**

- [x] 5. Implement event emission and metrics
  - [x] 5.1 Create `src/pipeline/events/models.py` with event types
    - Define EventType enum, PipelineEvent dataclass
    - _Requirements: 9.1, 9.2_
  
  - [x] 5.2 Create `src/pipeline/events/emitter.py` with event emitter
    - Implement EventEmitter interface
    - _Requirements: 9.1, 9.3_
  
  - [x] 5.3 Create `src/pipeline/events/metrics.py` with Prometheus metrics
    - Define counters: issues_processed, issues_failed
    - Define histogram: processing_time
    - Define gauge: issues_by_state
    - _Requirements: 9.5, 9.6_

- [x] 6. Implement GitHub API client
  - [x] 6.1 Create `src/pipeline/github/models.py` with API models
    - Define PRCreateRequest, PRCreateResult dataclasses
    - _Requirements: 6.2, 6.3_
  
  - [x] 6.2 Create `src/pipeline/github/client.py` with GitHub client
    - Implement create_comment, add_label, remove_label methods
    - Implement create_pr, request_reviewers methods
    - Implement rate limiting and retry logic
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

- [x] 7. Checkpoint - Phase 3A complete
  - Ensure all tests pass, ask the user if questions arise.
  - Verify webhook handler, state machine, persistence, and GitHub client work together

### Phase 3B: Issue Processing & Classification

- [x] 8. Implement issue classifier
  - [x] 8.1 Create `src/pipeline/classifier/models.py` with classification models
    - Define IssueType enum, IssueClassification dataclass
    - _Requirements: 2.1, 2.4_
  
  - [x] 8.2 Create `src/pipeline/classifier/agent.py` with LLM classifier
    - Implement classify method using LLM
    - Extract issue type, requirements, affected packages
    - Calculate completeness score
    - Generate clarification questions when score < 3
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  
  - [x] 8.3 Write property tests for classification output
    - **Property 3: Classification Output Validation**
    - **Property 4: Clarification Question Generation**
    - **Validates: Requirements 2.1, 2.4, 2.5**

- [x] 9. Implement clarification workflow
  - [x] 9.1 Add clarification comment formatting
    - Format questions as GitHub markdown checklist
    - _Requirements: 3.2, 3.3_
  
  - [x] 9.2 Implement label management for clarification
    - Add needs-clarification label when completeness < 3
    - Remove label when completeness >= 3
    - _Requirements: 3.4, 3.5, 3.6_
  
  - [x] 9.3 Write property tests for clarification workflow
    - **Property 5: Clarification Comment Structure**
    - **Property 6: Label State Consistency**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.6**

- [x] 10. Checkpoint - Phase 3B complete
  - Ensure all tests pass, ask the user if questions arise.
  - Verify issue classification and clarification workflow

### Phase 3C: Knowledge Integration

- [x] 11. Implement knowledge provider interface
  - [x] 11.1 Create `src/pipeline/knowledge/provider.py` with interface
    - Define KnowledgeProvider abstract base class
    - Define semantic_search, graph_query, resolve_arn, health_check methods
    - Define result dataclasses: SemanticSearchResult, GraphTraversalResult, ResolvedARN
    - _Requirements: 12.1, 12.2, 12.3, 12.4_
  
  - [x] 11.2 Create `src/pipeline/knowledge/vector.py` with vector store client
    - Implement semantic search against Qdrant
    - Return results with ARN metadata
    - _Requirements: 12.2, 12.6_
  
  - [x] 11.3 Create `src/pipeline/knowledge/graph.py` with code graph client
    - Implement GraphQL queries for relationship traversal
    - _Requirements: 12.3, 12.6_
  
  - [x] 11.4 Implement combined query pattern in DefaultKnowledgeProvider
    - Semantic search → extract ARNs → graph traversal → combined context
    - _Requirements: 12.7_
  
  - [x] 11.5 Write property tests for knowledge provider
    - **Property 15: Knowledge Provider Return Structure**
    - **Property 16: Knowledge Provider Combined Query**
    - **Validates: Requirements 12.2, 12.3, 12.4, 12.7**

- [x] 12. Document KnowledgeBase CRD evolution (design artifact)
  - [x] 12.1 Create child spec in AphexKnowledgeBaseController with CRD schema proposal
    - Created `AphexKnowledgeBaseController/.kiro/specs/scip-knowledge-integration/` spec
    - requirements.md documents scipIndexing, vectorStore, codeGraph fields and status additions
    - design.md contains the CRD schema update proposal with Go type definitions
    - tasks.md defines implementation tasks for CRD changes and controller reconciliation
    - Combined original 12.1 (proposal doc) and 12.2 (child spec) — the spec IS the proposal
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 13. Checkpoint - Phase 3C complete
  - Ensure all tests pass, ask the user if questions arise.
  - Verify knowledge provider integration

### Phase 3D: Workspace & Kiro Integration

- [x] 14. Implement workspace provisioner
  - [x] 14.1 Create `src/pipeline/provisioner/workspace.py` with provisioner
    - Implement workspace directory creation
    - Implement Git clone for required packages
    - Implement workspace cleanup for old workspaces
    - _Requirements: 4.1, 4.2, 4.7, 4.8_
  
  - [x] 14.2 Create `src/pipeline/provisioner/context.py` with context generation
    - Generate context.md with issue details and knowledge context
    - Generate task.md with implementation summary
    - _Requirements: 4.3, 4.4, 4.5, 4.6_

- [x] 15. Implement Kiro CLI runner
  - [x] 15.1 Create `src/pipeline/runner/kiro.py` with Kiro runner
    - Implement subprocess execution with timeout
    - Capture stdout/stderr
    - Stream output to logs
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

- [x] 16. Implement PR creation
  - [x] 16.1 Add PR creation logic to pipeline
    - Create PR with issue link and approach summary
    - Add labels based on classification
    - Request reviewers
    - Comment on original issue
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

- [x] 17. Wire pipeline stages together
  - [x] 17.1 Implement pipeline orchestrator
    - Connect webhook → classifier → provisioner → kiro → PR creation
    - Handle state transitions between stages
    - Implement error handling and recovery
    - _Requirements: All pipeline flow requirements_

- [x] 18. Create Kubernetes manifests
  - [x] 18.1 Create `manifests/pipeline.yaml` deployment
    - Deployment with resource limits
    - Service for internal access
    - ConfigMap for non-secret configuration
    - _Requirements: Deployment from design_
  
  - [x] 18.2 Create Tekton trigger resources
    - TriggerBinding for issue events
    - Trigger with CEL filter for archon-automate label
    - _Requirements: Webhook architecture from design_

- [x] 19. Final checkpoint - Phase 3D complete
  - Ensure all tests pass, ask the user if questions arise.
  - Verify end-to-end pipeline flow

## Notes

- All test tasks are required to ensure validation of what we're building
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- **Phase 3C Task 12.2** creates a child spec in `AphexKnowledgeBaseController` for the CRD evolution work
- The CRD implementation (Requirement 13) is tracked separately in `AphexKnowledgeBaseController/.kiro/specs/scip-knowledge-integration/`
