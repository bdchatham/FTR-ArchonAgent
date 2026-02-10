"""PostgreSQL repository for pipeline state persistence.

This module implements the StateRepository protocol using asyncpg for
async PostgreSQL access. It provides:
- Connection pooling for production use
- Atomic transactions for state updates
- Optimistic locking via version field
- State history reconstruction from transitions table

Requirements:
- 8.1: Persist state to PostgreSQL
- 8.3: Use database transactions for state updates
- 8.5: Implement optimistic locking to prevent concurrent updates

Source:
- migrations/001_pipeline_state.sql (schema definition)
- src/pipeline/state/machine.py (StateRepository protocol)
"""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import asyncpg

from src.pipeline.state.models import (
    PipelineStage,
    PipelineState,
    StateTransition,
)


logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Raised when a database operation fails.

    This exception wraps underlying database errors to provide
    a consistent interface for error handling.

    Attributes:
        message: Human-readable error description.
        original_error: The underlying exception, if any.
    """

    def __init__(
        self,
        message: str,
        original_error: Optional[Exception] = None,
    ):
        self.message = message
        self.original_error = original_error
        super().__init__(message)


class PostgresStateRepository:
    """PostgreSQL implementation of the StateRepository protocol.

    This class provides persistent storage for pipeline states using
    PostgreSQL with asyncpg for async database access. It implements:

    - Connection pooling for efficient resource usage
    - Atomic transactions for state updates
    - Optimistic locking via version field
    - State history reconstruction from transitions table

    The repository expects the database schema from migrations/001_pipeline_state.sql
    to be applied before use.

    Attributes:
        connection_string: PostgreSQL connection URL.
        pool: Connection pool (initialized via connect()).
        min_pool_size: Minimum connections in pool.
        max_pool_size: Maximum connections in pool.

    Example:
        >>> repo = PostgresStateRepository("postgresql://user:pass@host/db")
        >>> await repo.connect()
        >>> try:
        ...     state = await repo.get("owner/repo#123")
        ... finally:
        ...     await repo.disconnect()

    Or using the async context manager:
        >>> async with PostgresStateRepository("postgresql://...") as repo:
        ...     state = await repo.get("owner/repo#123")
    """

    def __init__(
        self,
        connection_string: str,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
    ):
        """Initialize the repository with connection parameters.

        Args:
            connection_string: PostgreSQL connection URL in format
                postgresql://user:password@host:port/database
            min_pool_size: Minimum number of connections in the pool.
            max_pool_size: Maximum number of connections in the pool.
        """
        self.connection_string = connection_string
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def pool(self) -> asyncpg.Pool:
        """Get the connection pool, raising if not connected.

        Returns:
            The asyncpg connection pool.

        Raises:
            DatabaseError: If the pool is not initialized.
        """
        if self._pool is None:
            raise DatabaseError(
                "Database pool not initialized. Call connect() first."
            )
        return self._pool

    async def connect(self) -> None:
        """Initialize the connection pool.

        This method must be called before any database operations.
        It creates a connection pool with the configured size limits.

        Raises:
            DatabaseError: If connection fails.
        """
        if self._pool is not None:
            logger.warning("Connection pool already initialized")
            return

        try:
            logger.info(
                "Connecting to PostgreSQL",
                extra={
                    "min_pool_size": self.min_pool_size,
                    "max_pool_size": self.max_pool_size,
                },
            )
            self._pool = await asyncpg.create_pool(
                self.connection_string,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
            )
            logger.info("PostgreSQL connection pool established")
        except Exception as e:
            logger.error(
                "Failed to connect to PostgreSQL",
                extra={"error": str(e)},
            )
            raise DatabaseError(
                f"Failed to connect to PostgreSQL: {e}",
                original_error=e,
            ) from e

    async def disconnect(self) -> None:
        """Close the connection pool.

        This method should be called when shutting down to release
        database connections gracefully.
        """
        if self._pool is not None:
            logger.info("Closing PostgreSQL connection pool")
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL connection pool closed")

    async def __aenter__(self) -> "PostgresStateRepository":
        """Async context manager entry - connect to database."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - disconnect from database."""
        await self.disconnect()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[asyncpg.Connection]:
        """Create a transaction context for atomic operations.

        Yields:
            A connection with an active transaction.

        Raises:
            DatabaseError: If transaction fails.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def save(self, state: PipelineState) -> None:
        """Save a new pipeline state to the database.

        This method inserts a new pipeline state record. It should be
        used for creating new states, not updating existing ones.
        For updates, use update_with_version().

        Args:
            state: The pipeline state to save.

        Raises:
            DatabaseError: If the save operation fails.
        """
        try:
            async with self._transaction() as conn:
                # Insert the pipeline state
                await conn.execute(
                    """
                    INSERT INTO pipeline_states (
                        issue_id,
                        repository,
                        current_stage,
                        classification,
                        workspace_path,
                        pr_number,
                        error,
                        created_at,
                        updated_at,
                        version
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    state.issue_id,
                    state.repository,
                    state.current_stage.value,
                    json.dumps(state.classification) if state.classification else None,
                    state.workspace_path,
                    state.pr_number,
                    state.error,
                    state.created_at,
                    state.updated_at,
                    state.version,
                )

                # Insert any initial state transitions
                for transition in state.state_history:
                    await conn.execute(
                        """
                        INSERT INTO state_transitions (
                            issue_id,
                            from_stage,
                            to_stage,
                            timestamp,
                            details
                        ) VALUES ($1, $2, $3, $4, $5)
                        """,
                        state.issue_id,
                        transition.from_stage.value,
                        transition.to_stage.value,
                        transition.timestamp,
                        json.dumps(transition.details) if transition.details else None,
                    )

                logger.info(
                    "Saved pipeline state",
                    extra={
                        "issue_id": state.issue_id,
                        "stage": state.current_stage.value,
                        "version": state.version,
                    },
                )

        except asyncpg.UniqueViolationError as e:
            logger.error(
                "Pipeline state already exists",
                extra={"issue_id": state.issue_id, "error": str(e)},
            )
            raise DatabaseError(
                f"Pipeline state already exists for issue: {state.issue_id}",
                original_error=e,
            ) from e
        except Exception as e:
            logger.error(
                "Failed to save pipeline state",
                extra={"issue_id": state.issue_id, "error": str(e)},
            )
            raise DatabaseError(
                f"Failed to save pipeline state: {e}",
                original_error=e,
            ) from e

    async def get(self, issue_id: str) -> Optional[PipelineState]:
        """Get pipeline state by issue ID.

        This method retrieves the pipeline state and reconstructs
        the state_history from the state_transitions table.

        Args:
            issue_id: The canonical issue identifier.

        Returns:
            The pipeline state if found, None otherwise.

        Raises:
            DatabaseError: If the query fails.
        """
        try:
            async with self.pool.acquire() as conn:
                # Fetch the pipeline state
                row = await conn.fetchrow(
                    """
                    SELECT
                        issue_id,
                        repository,
                        current_stage,
                        classification,
                        workspace_path,
                        pr_number,
                        error,
                        created_at,
                        updated_at,
                        version
                    FROM pipeline_states
                    WHERE issue_id = $1
                    """,
                    issue_id,
                )

                if row is None:
                    return None

                # Fetch the state transitions (ordered by timestamp)
                transition_rows = await conn.fetch(
                    """
                    SELECT
                        from_stage,
                        to_stage,
                        timestamp,
                        details
                    FROM state_transitions
                    WHERE issue_id = $1
                    ORDER BY timestamp ASC, id ASC
                    """,
                    issue_id,
                )

                # Reconstruct state history
                state_history = [
                    StateTransition(
                        from_stage=PipelineStage(tr["from_stage"]),
                        to_stage=PipelineStage(tr["to_stage"]),
                        timestamp=tr["timestamp"].replace(tzinfo=timezone.utc)
                        if tr["timestamp"].tzinfo is None
                        else tr["timestamp"],
                        details=json.loads(tr["details"]) if tr["details"] else {},
                    )
                    for tr in transition_rows
                ]

                # Parse classification JSON
                classification = None
                if row["classification"]:
                    classification = (
                        json.loads(row["classification"])
                        if isinstance(row["classification"], str)
                        else row["classification"]
                    )

                # Ensure timestamps have timezone info
                created_at = row["created_at"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                updated_at = row["updated_at"]
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)

                return PipelineState(
                    issue_id=row["issue_id"],
                    repository=row["repository"],
                    current_stage=PipelineStage(row["current_stage"]),
                    state_history=state_history,
                    classification=classification,
                    workspace_path=row["workspace_path"],
                    pr_number=row["pr_number"],
                    error=row["error"],
                    created_at=created_at,
                    updated_at=updated_at,
                    version=row["version"],
                )

        except Exception as e:
            logger.error(
                "Failed to get pipeline state",
                extra={"issue_id": issue_id, "error": str(e)},
            )
            raise DatabaseError(
                f"Failed to get pipeline state: {e}",
                original_error=e,
            ) from e

    async def list_by_stage(self, stage: PipelineStage) -> List[PipelineState]:
        """List all pipeline states in a given stage.

        This method retrieves all states with the specified current_stage,
        including their full state history.

        Args:
            stage: The pipeline stage to filter by.

        Returns:
            List of pipeline states in the specified stage.

        Raises:
            DatabaseError: If the query fails.
        """
        try:
            async with self.pool.acquire() as conn:
                # Fetch all states in the given stage
                rows = await conn.fetch(
                    """
                    SELECT issue_id
                    FROM pipeline_states
                    WHERE current_stage = $1
                    ORDER BY created_at ASC
                    """,
                    stage.value,
                )

                # Fetch full state for each issue
                states = []
                for row in rows:
                    state = await self.get(row["issue_id"])
                    if state is not None:
                        states.append(state)

                logger.debug(
                    "Listed pipeline states by stage",
                    extra={
                        "stage": stage.value,
                        "count": len(states),
                    },
                )

                return states

        except DatabaseError:
            raise
        except Exception as e:
            logger.error(
                "Failed to list pipeline states by stage",
                extra={"stage": stage.value, "error": str(e)},
            )
            raise DatabaseError(
                f"Failed to list pipeline states by stage: {e}",
                original_error=e,
            ) from e

    async def update_with_version(self, state: PipelineState) -> bool:
        """Update state with optimistic locking.

        This method updates the pipeline state only if the version matches
        the expected value (state.version - 1). This prevents concurrent
        update conflicts by ensuring only one update succeeds when multiple
        processes try to update the same state.

        The method also inserts any new transitions that were added to
        the state_history since the last update.

        Args:
            state: The pipeline state to update. The version field should
                   be incremented by the caller before calling this method.

        Returns:
            True if update succeeded, False if version conflict.

        Raises:
            DatabaseError: If the update operation fails for reasons
                           other than version conflict.
        """
        expected_version = state.version - 1

        try:
            async with self._transaction() as conn:
                # Update the pipeline state with version check
                result = await conn.execute(
                    """
                    UPDATE pipeline_states
                    SET
                        current_stage = $2,
                        classification = $3,
                        workspace_path = $4,
                        pr_number = $5,
                        error = $6,
                        updated_at = $7,
                        version = $8
                    WHERE issue_id = $1 AND version = $9
                    """,
                    state.issue_id,
                    state.current_stage.value,
                    json.dumps(state.classification) if state.classification else None,
                    state.workspace_path,
                    state.pr_number,
                    state.error,
                    state.updated_at,
                    state.version,
                    expected_version,
                )

                # Check if update affected any rows
                rows_affected = int(result.split()[-1])
                if rows_affected == 0:
                    logger.warning(
                        "Version conflict during state update",
                        extra={
                            "issue_id": state.issue_id,
                            "expected_version": expected_version,
                            "new_version": state.version,
                        },
                    )
                    return False

                # Insert new transitions
                # Get the count of existing transitions to determine which are new
                existing_count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM state_transitions
                    WHERE issue_id = $1
                    """,
                    state.issue_id,
                )

                # Insert only new transitions (those beyond existing_count)
                new_transitions = state.state_history[existing_count:]
                for transition in new_transitions:
                    await conn.execute(
                        """
                        INSERT INTO state_transitions (
                            issue_id,
                            from_stage,
                            to_stage,
                            timestamp,
                            details
                        ) VALUES ($1, $2, $3, $4, $5)
                        """,
                        state.issue_id,
                        transition.from_stage.value,
                        transition.to_stage.value,
                        transition.timestamp,
                        json.dumps(transition.details) if transition.details else None,
                    )

                logger.info(
                    "Updated pipeline state",
                    extra={
                        "issue_id": state.issue_id,
                        "stage": state.current_stage.value,
                        "version": state.version,
                        "new_transitions": len(new_transitions),
                    },
                )

                return True

        except Exception as e:
            logger.error(
                "Failed to update pipeline state",
                extra={"issue_id": state.issue_id, "error": str(e)},
            )
            raise DatabaseError(
                f"Failed to update pipeline state: {e}",
                original_error=e,
            ) from e

    async def delete(self, issue_id: str) -> bool:
        """Delete a pipeline state and its transitions.

        This method removes a pipeline state and all associated
        transitions from the database. The cascade delete on the
        foreign key handles transition cleanup.

        Args:
            issue_id: The canonical issue identifier.

        Returns:
            True if a state was deleted, False if not found.

        Raises:
            DatabaseError: If the delete operation fails.
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM pipeline_states
                    WHERE issue_id = $1
                    """,
                    issue_id,
                )

                rows_affected = int(result.split()[-1])
                if rows_affected > 0:
                    logger.info(
                        "Deleted pipeline state",
                        extra={"issue_id": issue_id},
                    )
                    return True
                return False

        except Exception as e:
            logger.error(
                "Failed to delete pipeline state",
                extra={"issue_id": issue_id, "error": str(e)},
            )
            raise DatabaseError(
                f"Failed to delete pipeline state: {e}",
                original_error=e,
            ) from e

    async def health_check(self) -> bool:
        """Check if the database connection is healthy.

        This method performs a simple query to verify the database
        is accessible and responding.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
                return True
        except Exception as e:
            logger.warning(
                "Database health check failed",
                extra={"error": str(e)},
            )
            return False
