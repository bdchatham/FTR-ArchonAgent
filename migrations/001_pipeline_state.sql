-- Migration: 001_pipeline_state.sql
-- Description: Create pipeline state persistence tables for agent orchestration
-- Requirements: 8.1 (Persist state to PostgreSQL), 8.2 (State schema)
--
-- This migration creates the database schema for persisting pipeline state,
-- enabling the agent orchestration system to:
-- - Track issues through pipeline stages
-- - Survive service restarts without losing in-progress work
-- - Support querying issues by current state
-- - Maintain an audit trail of state transitions
--
-- Source: ArchonAgent/.kiro/specs/agent-orchestration/design.md

-- =============================================================================
-- Pipeline States Table
-- =============================================================================
-- Stores the current state of each issue being processed through the pipeline.
-- Each row represents a single GitHub issue and its progress through the
-- autonomous development workflow.
--
-- The issue_id serves as the primary key using the canonical format
-- "{owner}/{repo}#{number}" (e.g., "myorg/myrepo#123").
--
-- Optimistic locking is implemented via the version field to prevent
-- concurrent update conflicts when multiple workers process the same issue.

CREATE TABLE pipeline_states (
    -- Canonical issue identifier in format "{owner}/{repo}#{number}"
    -- Example: "myorg/myrepo#123"
    -- This format uniquely identifies an issue across all repositories
    issue_id TEXT PRIMARY KEY,

    -- Full repository path in format "{owner}/{repo}"
    -- Example: "myorg/myrepo"
    -- Used for filtering and grouping issues by repository
    repository TEXT NOT NULL,

    -- Current pipeline stage
    -- Valid values: pending, intake, clarification, provisioning,
    --               implementation, pr_creation, completed, failed
    -- See VALID_TRANSITIONS in state/models.py for allowed transitions
    current_stage TEXT NOT NULL,

    -- LLM classification results stored as JSON
    -- Contains: issue_type, requirements, affected_packages,
    --           completeness_score, clarification_questions
    -- NULL until classification completes in the intake stage
    classification JSONB,

    -- Filesystem path to the provisioned workspace
    -- Example: "/var/lib/archon/workspaces/myorg-myrepo-123"
    -- NULL until workspace is provisioned
    workspace_path TEXT,

    -- Pull request number if PR was created
    -- NULL until PR creation stage completes successfully
    pr_number INTEGER,

    -- Error message if pipeline failed
    -- Contains details about what went wrong
    -- NULL unless current_stage is 'failed'
    error TEXT,

    -- Timestamp when this pipeline state was first created (UTC)
    -- Set once when the issue enters the pipeline
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Timestamp when this pipeline state was last updated (UTC)
    -- Updated on every state change
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Optimistic locking version for concurrent update protection
    -- Incremented on each update; updates fail if version doesn't match
    -- Requirement 8.5: Implement optimistic locking to prevent concurrent updates
    version INTEGER NOT NULL DEFAULT 1,

    -- Constraint: Ensure current_stage is a valid pipeline stage
    -- This provides database-level validation matching PipelineStage enum
    CONSTRAINT valid_current_stage CHECK (
        current_stage IN (
            'pending',
            'intake',
            'clarification',
            'provisioning',
            'implementation',
            'pr_creation',
            'completed',
            'failed'
        )
    ),

    -- Constraint: Version must be positive
    CONSTRAINT positive_version CHECK (version >= 1),

    -- Constraint: PR number must be positive if set
    CONSTRAINT positive_pr_number CHECK (pr_number IS NULL OR pr_number > 0)
);

-- Add table comment for documentation
COMMENT ON TABLE pipeline_states IS 
    'Stores the current state of GitHub issues being processed through the agent pipeline. '
    'Each row tracks an issue from intake through PR creation, supporting restart recovery '
    'and concurrent update protection via optimistic locking.';

-- Add column comments
COMMENT ON COLUMN pipeline_states.issue_id IS 
    'Canonical issue identifier in format "{owner}/{repo}#{number}"';
COMMENT ON COLUMN pipeline_states.repository IS 
    'Full repository path in format "{owner}/{repo}"';
COMMENT ON COLUMN pipeline_states.current_stage IS 
    'Current pipeline stage (pending, intake, clarification, provisioning, implementation, pr_creation, completed, failed)';
COMMENT ON COLUMN pipeline_states.classification IS 
    'LLM classification results as JSON (issue_type, requirements, affected_packages, completeness_score)';
COMMENT ON COLUMN pipeline_states.workspace_path IS 
    'Filesystem path to the provisioned workspace for Kiro execution';
COMMENT ON COLUMN pipeline_states.pr_number IS 
    'Pull request number if PR was created successfully';
COMMENT ON COLUMN pipeline_states.error IS 
    'Error message describing failure reason when current_stage is failed';
COMMENT ON COLUMN pipeline_states.created_at IS 
    'Timestamp when this pipeline state was first created (UTC)';
COMMENT ON COLUMN pipeline_states.updated_at IS 
    'Timestamp when this pipeline state was last modified (UTC)';
COMMENT ON COLUMN pipeline_states.version IS 
    'Optimistic locking version; incremented on each update to prevent concurrent conflicts';


-- =============================================================================
-- State Transitions Table
-- =============================================================================
-- Stores the history of state transitions for each issue, providing an
-- audit trail for debugging, observability, and compliance.
--
-- Each row represents a single transition from one stage to another,
-- with a timestamp and optional details about the transition.
--
-- Requirement 8.2: state_history is stored in this separate table for
-- efficient querying and to avoid JSONB array manipulation overhead.
-- Requirement 8.6: State history SHALL be queryable for debugging and auditing.

CREATE TABLE state_transitions (
    -- Auto-incrementing primary key
    id SERIAL PRIMARY KEY,

    -- Reference to the pipeline state this transition belongs to
    -- Cascades on delete to clean up history when state is removed
    issue_id TEXT NOT NULL REFERENCES pipeline_states(issue_id) ON DELETE CASCADE,

    -- The stage before this transition
    from_stage TEXT NOT NULL,

    -- The stage after this transition
    to_stage TEXT NOT NULL,

    -- When the transition occurred (UTC)
    -- Requirement 7.3: Record timestamps for each state transition
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Optional metadata about the transition
    -- May contain: error details, classification results, PR info, etc.
    details JSONB,

    -- Constraint: Ensure from_stage is a valid pipeline stage
    CONSTRAINT valid_from_stage CHECK (
        from_stage IN (
            'pending',
            'intake',
            'clarification',
            'provisioning',
            'implementation',
            'pr_creation',
            'completed',
            'failed'
        )
    ),

    -- Constraint: Ensure to_stage is a valid pipeline stage
    CONSTRAINT valid_to_stage CHECK (
        to_stage IN (
            'pending',
            'intake',
            'clarification',
            'provisioning',
            'implementation',
            'pr_creation',
            'completed',
            'failed'
        )
    )
);

-- Add table comment for documentation
COMMENT ON TABLE state_transitions IS 
    'Audit trail of state transitions for pipeline issues. Each row records '
    'a transition from one stage to another with timestamp and optional details. '
    'Supports debugging, observability, and compliance requirements.';

-- Add column comments
COMMENT ON COLUMN state_transitions.id IS 
    'Auto-incrementing primary key for the transition record';
COMMENT ON COLUMN state_transitions.issue_id IS 
    'Reference to the pipeline_states row this transition belongs to';
COMMENT ON COLUMN state_transitions.from_stage IS 
    'The pipeline stage before this transition';
COMMENT ON COLUMN state_transitions.to_stage IS 
    'The pipeline stage after this transition';
COMMENT ON COLUMN state_transitions.timestamp IS 
    'When the transition occurred (UTC timezone)';
COMMENT ON COLUMN state_transitions.details IS 
    'Optional JSON metadata about the transition (error info, classification results, etc.)';


-- =============================================================================
-- Indexes for Efficient Queries
-- =============================================================================
-- These indexes support the common query patterns used by the pipeline:
-- - Listing issues by current stage (for processing queues)
-- - Filtering issues by repository (for repository-specific views)
-- - Looking up transition history for an issue (for debugging)

-- Index on current_stage for efficient stage-based queries
-- Requirement 7.5: Support querying issues by current state
-- Used by: list_by_stage() to find all issues in a given stage
CREATE INDEX idx_pipeline_states_stage ON pipeline_states(current_stage);

-- Index on repository for efficient repository-based filtering
-- Used by: Dashboard views, repository-specific issue lists
CREATE INDEX idx_pipeline_states_repository ON pipeline_states(repository);

-- Index on issue_id in state_transitions for efficient history lookups
-- Used by: Retrieving full transition history for an issue
-- Note: This is in addition to the foreign key constraint
CREATE INDEX idx_state_transitions_issue ON state_transitions(issue_id);

-- Index on timestamp in state_transitions for time-based queries
-- Used by: Audit queries, debugging recent transitions
CREATE INDEX idx_state_transitions_timestamp ON state_transitions(timestamp);

-- Composite index for common query pattern: issues by stage and repository
-- Used by: Repository-specific processing queues
CREATE INDEX idx_pipeline_states_stage_repository 
    ON pipeline_states(current_stage, repository);


-- =============================================================================
-- Trigger for Automatic updated_at Maintenance
-- =============================================================================
-- Automatically updates the updated_at timestamp whenever a row is modified.
-- This ensures updated_at is always accurate without requiring application code
-- to explicitly set it on every update.

CREATE OR REPLACE FUNCTION update_pipeline_states_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_pipeline_states_updated_at
    BEFORE UPDATE ON pipeline_states
    FOR EACH ROW
    EXECUTE FUNCTION update_pipeline_states_updated_at();

COMMENT ON FUNCTION update_pipeline_states_updated_at() IS 
    'Trigger function to automatically update the updated_at timestamp on row modification';
