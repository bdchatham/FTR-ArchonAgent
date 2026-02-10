"""Code graph client for structural traversal via GraphQL.

This module provides an async client for querying the code graph to traverse
SCIP-derived relationships between code symbols. The code graph stores
relationships extracted from SCIP indexes:

- contains: Parent symbol contains child symbol (e.g., class contains method)
- references: Symbol references another symbol (e.g., function calls another)
- implements: Symbol implements an interface/protocol
- extends: Symbol extends/inherits from another
- imports: Module imports another module

The graph client enables expanding context from semantic search results by
following structural relationships to discover related code symbols.

Requirements:
- 12.3: Graph traversal for code relationships
- 12.6: Return results with ARN metadata

Source:
- src/pipeline/knowledge/provider.py (GraphTraversalResult, CodeSymbol, ResolvedARN)
- ArchonKnowledgeBaseInfrastructure/src/graph/adapter.py (GraphQL patterns)
"""

import logging
from typing import Any, Optional

import httpx

from src.pipeline.knowledge.provider import (
    CodeSymbol,
    GraphTraversalResult,
    ResolvedARN,
)


logger = logging.getLogger(__name__)


# Valid relationship types for graph traversal
VALID_RELATIONSHIP_TYPES = frozenset({
    "contains",
    "references",
    "implements",
    "extends",
    "imports",
})


class CodeGraphError(Exception):
    """Raised when code graph operations fail.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code from the response if applicable.
        response_body: Response body from GraphQL API if applicable.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class CodeGraphClient:
    """Async client for code graph traversal via GraphQL.

    This client queries the code graph to find symbols related to given ARNs
    through specified relationship types. The code graph is populated from
    SCIP indexes and stores structural relationships between code symbols.

    The client uses GraphQL queries via httpx for async HTTP requests,
    consistent with the pipeline's approach in github/client.py and
    vector.py.

    Attributes:
        graphql_url: URL of the GraphQL endpoint.
        timeout: Request timeout in seconds.

    Example:
        >>> client = CodeGraphClient(
        ...     graphql_url="http://code-graph:8080/graphql",
        ... )
        >>> async with client:
        ...     results = await client.graph_query(
        ...         arns=["arn:archon:pkg:src/auth.py:AuthHandler"],
        ...         relationship_types=["references", "contains"],
        ...         depth=2,
        ...     )
        ...     for result in results:
        ...         print(f"{result.relationship} -> {result.symbol.name}")

    Or without context manager:
        >>> client = CodeGraphClient(...)
        >>> results = await client.graph_query(arns, relationship_types)
        >>> await client.close()
    """

    # GraphQL query for traversing relationships from ARNs
    TRAVERSE_QUERY = """
    query TraverseRelationships($arns: [String!]!, $relationshipTypes: [String!]!, $depth: Int!) {
        traverseFromArns(arns: $arns, relationshipTypes: $relationshipTypes, depth: $depth) {
            symbol {
                arn
                name
                kind
                signature
                filePath
                lineNumber
                documentation
            }
            relationship
            depth
        }
    }
    """

    # GraphQL query for resolving a single ARN
    RESOLVE_ARN_QUERY = """
    query ResolveArn($arn: String!) {
        resolveArn(arn: $arn) {
            arn
            filePath
            lineNumber
            symbolName
            symbolKind
        }
    }
    """

    # GraphQL query for health check
    HEALTH_QUERY = """
    query HealthCheck {
        __typename
    }
    """

    def __init__(
        self,
        graphql_url: str,
        timeout: float = 30.0,
    ):
        """Initialize the code graph client.

        Args:
            graphql_url: URL of the GraphQL endpoint.
            timeout: Request timeout in seconds.
        """
        self.graphql_url = graphql_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client, creating it if necessary.

        Returns:
            The httpx AsyncClient instance.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "CodeGraphClient":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        """Async context manager exit - close the client."""
        await self.close()

    async def _execute_query(
        self,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a GraphQL query.

        Args:
            query: The GraphQL query string.
            variables: Query variables.

        Returns:
            The data portion of the GraphQL response.

        Raises:
            CodeGraphError: If the query fails or returns errors.
        """
        try:
            response = await self.client.post(
                self.graphql_url,
                json={
                    "query": query,
                    "variables": variables,
                },
            )

            if response.status_code != 200:
                logger.error(
                    "GraphQL request failed",
                    extra={
                        "status_code": response.status_code,
                        "response": response.text[:500],
                    },
                )
                raise CodeGraphError(
                    message=f"GraphQL request failed: {response.status_code}",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            data = response.json()

            # Check for GraphQL errors
            if "errors" in data and data["errors"]:
                error_messages = [e.get("message", "Unknown error") for e in data["errors"]]
                logger.error(
                    "GraphQL query returned errors",
                    extra={"errors": error_messages},
                )
                raise CodeGraphError(
                    message=f"GraphQL errors: {'; '.join(error_messages)}",
                )

            return data.get("data", {})

        except httpx.RequestError as e:
            logger.error(
                "GraphQL request failed",
                extra={"error": str(e)},
            )
            raise CodeGraphError(
                message=f"GraphQL request failed: {e}",
            ) from e

    async def graph_query(
        self,
        arns: list[str],
        relationship_types: list[str],
        depth: int = 1,
    ) -> list[GraphTraversalResult]:
        """Traverse code graph from given ARNs.

        Queries the code graph to find symbols related to the given ARNs
        through specified relationship types. This enables expanding
        context from semantic search results to include structurally
        related code.

        Args:
            arns: List of ARNs to start traversal from.
            relationship_types: Types of relationships to follow.
            depth: Maximum traversal depth (default: 1, direct relationships).

        Returns:
            list[GraphTraversalResult]: Symbols discovered through traversal,
                each with relationship type and depth from starting ARN.

        Raises:
            CodeGraphError: If the query fails.
            ValueError: If arns list is empty or relationship_types invalid.

        Example:
            related = await client.graph_query(
                arns=["arn:archon:auth-service:src/auth.py:AuthHandler"],
                relationship_types=["references", "contains"],
                depth=2
            )
            for result in related:
                print(f"{result.relationship} -> {result.symbol.name}")
        """
        if not arns:
            raise ValueError("arns list cannot be empty")

        if not relationship_types:
            raise ValueError("relationship_types list cannot be empty")

        # Validate relationship types
        invalid_types = set(relationship_types) - VALID_RELATIONSHIP_TYPES
        if invalid_types:
            raise ValueError(
                f"Invalid relationship types: {invalid_types}. "
                f"Valid types are: {VALID_RELATIONSHIP_TYPES}"
            )

        if depth < 1:
            raise ValueError("depth must be at least 1")

        data = await self._execute_query(
            self.TRAVERSE_QUERY,
            {
                "arns": arns,
                "relationshipTypes": relationship_types,
                "depth": depth,
            },
        )

        return self._parse_traversal_results(data)

    def _parse_traversal_results(
        self,
        data: dict[str, Any],
    ) -> list[GraphTraversalResult]:
        """Parse GraphQL traversal response into GraphTraversalResult models.

        Args:
            data: The data portion of the GraphQL response.

        Returns:
            List of GraphTraversalResult models.
        """
        results: list[GraphTraversalResult] = []
        traversal_results = data.get("traverseFromArns", [])

        for item in traversal_results:
            symbol_data = item.get("symbol", {})

            # Skip results with missing required fields
            if not self._validate_symbol_data(symbol_data):
                logger.warning(
                    "Skipping traversal result with missing required fields",
                    extra={"symbol_data": symbol_data},
                )
                continue

            symbol = CodeSymbol(
                arn=symbol_data["arn"],
                name=symbol_data["name"],
                kind=symbol_data["kind"],
                signature=symbol_data.get("signature"),
                file_path=symbol_data["filePath"],
                line_number=symbol_data["lineNumber"],
                documentation=symbol_data.get("documentation"),
            )

            result = GraphTraversalResult(
                symbol=symbol,
                relationship=item.get("relationship", "unknown"),
                depth=item.get("depth", 1),
            )
            results.append(result)

        logger.debug(
            "Parsed traversal results",
            extra={
                "total_items": len(traversal_results),
                "valid_results": len(results),
            },
        )

        return results

    def _validate_symbol_data(self, symbol_data: dict[str, Any]) -> bool:
        """Validate that symbol data has all required fields.

        Args:
            symbol_data: The symbol data from GraphQL response.

        Returns:
            True if all required fields are present and valid.
        """
        required_fields = ["arn", "name", "kind", "filePath", "lineNumber"]
        for field in required_fields:
            if field not in symbol_data or not symbol_data[field]:
                return False

        # Validate lineNumber is positive
        if not isinstance(symbol_data["lineNumber"], int) or symbol_data["lineNumber"] < 1:
            return False

        return True

    async def resolve_arn(self, arn: str) -> Optional[ResolvedARN]:
        """Resolve ARN to file location.

        Looks up an ARN in the code graph to find its concrete file
        system location and symbol information.

        Args:
            arn: The Archon Resource Name to resolve.

        Returns:
            Optional[ResolvedARN]: File location and symbol info if found,
                None if the ARN cannot be resolved.

        Raises:
            CodeGraphError: If the query fails.
            ValueError: If arn is empty.

        Example:
            location = await client.resolve_arn(
                "arn:archon:auth-service:src/auth.py:AuthHandler"
            )
            if location:
                print(f"Found at {location.file_path}:{location.line_number}")
        """
        if not arn or not arn.strip():
            raise ValueError("arn cannot be empty")

        data = await self._execute_query(
            self.RESOLVE_ARN_QUERY,
            {"arn": arn},
        )

        resolved_data = data.get("resolveArn")
        if not resolved_data:
            logger.debug(
                "ARN not found in code graph",
                extra={"arn": arn},
            )
            return None

        # Validate required fields
        if not resolved_data.get("filePath") or not resolved_data.get("lineNumber"):
            logger.warning(
                "Resolved ARN missing required fields",
                extra={"arn": arn, "data": resolved_data},
            )
            return None

        return ResolvedARN(
            arn=resolved_data.get("arn", arn),
            file_path=resolved_data["filePath"],
            line_number=resolved_data["lineNumber"],
            symbol_name=resolved_data.get("symbolName"),
            symbol_kind=resolved_data.get("symbolKind"),
        )

    async def health_check(self) -> bool:
        """Check if the code graph service is healthy.

        Verifies connectivity to the GraphQL endpoint by executing
        a simple introspection query.

        Returns:
            True if the service is reachable and responding,
            False otherwise.

        Example:
            if await client.health_check():
                results = await client.graph_query(arns, types)
            else:
                logger.warning("Code graph unavailable")
        """
        try:
            await self._execute_query(self.HEALTH_QUERY, {})
            return True

        except Exception as e:
            logger.warning(
                "Code graph health check failed",
                extra={"error": str(e)},
            )
            return False
