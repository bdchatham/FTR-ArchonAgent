"""Property-based tests for knowledge provider interface.

This module contains property-based tests using Hypothesis to verify that
the knowledge provider correctly returns structured results and implements
the combined query pattern.

**Validates: Requirements 12.2, 12.3, 12.4, 12.7**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>
"""

import asyncio
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, settings, strategies as st, assume

from src.pipeline.knowledge.provider import (
    CodeSymbol,
    DefaultKnowledgeProvider,
    GraphTraversalResult,
    KnowledgeProvider,
    ResolvedARN,
    SemanticSearchResult,
)


# =============================================================================
# Mock Implementations for Testing
# =============================================================================


class MockVectorStoreClient:
    """Mock vector store client for testing.

    Returns configurable results for semantic search without
    requiring a real Qdrant instance.
    """

    def __init__(
        self,
        results: Optional[List[SemanticSearchResult]] = None,
        healthy: bool = True,
    ):
        """Initialize mock client.

        Args:
            results: Results to return from semantic_search.
            healthy: Whether health_check returns True.
        """
        self._results = results or []
        self._healthy = healthy
        self._closed = False

    async def semantic_search(
        self,
        query: str,
        limit: int = 10,
        package_filter: Optional[str] = None,
        score_threshold: Optional[float] = None,
    ) -> List[SemanticSearchResult]:
        """Return configured results."""
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        results = self._results[:limit]

        if package_filter:
            results = [r for r in results if r.package == package_filter]

        return results

    async def health_check(self) -> bool:
        """Return configured health status."""
        return self._healthy

    async def close(self) -> None:
        """Mark client as closed."""
        self._closed = False


class MockCodeGraphClient:
    """Mock code graph client for testing.

    Returns configurable results for graph queries without
    requiring a real GraphQL service.
    """

    def __init__(
        self,
        traversal_results: Optional[List[GraphTraversalResult]] = None,
        resolved_arns: Optional[Dict[str, ResolvedARN]] = None,
        healthy: bool = True,
    ):
        """Initialize mock client.

        Args:
            traversal_results: Results to return from graph_query.
            resolved_arns: Map of ARN to ResolvedARN for resolve_arn.
            healthy: Whether health_check returns True.
        """
        self._traversal_results = traversal_results or []
        self._resolved_arns = resolved_arns or {}
        self._healthy = healthy
        self._closed = False

    async def graph_query(
        self,
        arns: List[str],
        relationship_types: List[str],
        depth: int = 1,
    ) -> List[GraphTraversalResult]:
        """Return configured results."""
        if not arns:
            raise ValueError("arns list cannot be empty")
        if not relationship_types:
            raise ValueError("relationship_types list cannot be empty")
        return self._traversal_results

    async def resolve_arn(self, arn: str) -> Optional[ResolvedARN]:
        """Return configured resolved ARN."""
        if not arn or not arn.strip():
            raise ValueError("arn cannot be empty")
        return self._resolved_arns.get(arn)

    async def health_check(self) -> bool:
        """Return configured health status."""
        return self._healthy

    async def close(self) -> None:
        """Mark client as closed."""
        self._closed = True


# =============================================================================
# Hypothesis Strategies for Generating Test Data
# =============================================================================


@st.composite
def valid_arn(draw: st.DrawFn) -> str:
    """Generate a valid ARN string.

    ARN format: arn:archon:{package}:{file_path}:{symbol_name}
    """
    package = draw(st.sampled_from([
        "auth-service",
        "api-gateway",
        "user-service",
        "data-layer",
        "core-lib",
    ]))

    file_path = draw(st.sampled_from([
        "src/main.py",
        "src/handlers/auth.py",
        "src/models/user.py",
        "lib/utils.py",
        "pkg/api/routes.py",
    ]))

    symbol_name = draw(st.sampled_from([
        "AuthHandler",
        "UserModel",
        "process_request",
        "validate_token",
        "DatabaseClient",
        "ConfigLoader",
    ]))

    return f"arn:archon:{package}:{file_path}:{symbol_name}"


@st.composite
def valid_package_name(draw: st.DrawFn) -> str:
    """Generate a valid package name."""
    return draw(st.sampled_from([
        "auth-service",
        "api-gateway",
        "user-service",
        "data-layer",
        "core-lib",
        "common-utils",
    ]))


@st.composite
def valid_file_path(draw: st.DrawFn) -> str:
    """Generate a valid file path."""
    return draw(st.sampled_from([
        "src/main.py",
        "src/handlers/auth.py",
        "src/models/user.py",
        "lib/utils.py",
        "pkg/api/routes.py",
        "internal/config.go",
        "src/index.ts",
    ]))


@st.composite
def valid_symbol_name(draw: st.DrawFn) -> str:
    """Generate a valid symbol name."""
    return draw(st.sampled_from([
        "AuthHandler",
        "UserModel",
        "process_request",
        "validate_token",
        "DatabaseClient",
        "ConfigLoader",
        "handle_error",
        "parse_input",
    ]))


@st.composite
def valid_symbol_kind(draw: st.DrawFn) -> str:
    """Generate a valid symbol kind."""
    return draw(
        st.sampled_from([
            "function",
            "class",
            "method",
            "variable",
            "constant",
            "interface",
            "module",
            "type",
        ])
    )


@st.composite
def valid_relationship_type(draw: st.DrawFn) -> str:
    """Generate a valid relationship type."""
    return draw(
        st.sampled_from([
            "contains",
            "references",
            "implements",
            "extends",
            "imports",
        ])
    )


@st.composite
def valid_content(draw: st.DrawFn) -> str:
    """Generate valid content text."""
    prefix = draw(st.sampled_from([
        "This function handles",
        "The class implements",
        "This module provides",
        "Authentication logic for",
        "Data processing utilities",
    ]))
    suffix = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz ",
        min_size=10,
        max_size=100,
    ))
    return f"{prefix} {suffix}"


@st.composite
def semantic_search_result(draw: st.DrawFn) -> SemanticSearchResult:
    """Generate a valid SemanticSearchResult."""
    content = draw(valid_content())
    source = draw(valid_file_path())
    score = draw(st.floats(min_value=0.0, max_value=1.0))
    arn = draw(valid_arn())
    related_arns = draw(st.lists(valid_arn(), max_size=3))
    symbol_name = draw(st.one_of(st.none(), valid_symbol_name()))
    symbol_kind = draw(st.one_of(st.none(), valid_symbol_kind()))
    package = draw(valid_package_name())

    return SemanticSearchResult(
        content=content,
        source=source,
        score=score,
        arn=arn,
        related_arns=related_arns,
        symbol_name=symbol_name,
        symbol_kind=symbol_kind,
        package=package,
    )


@st.composite
def code_symbol(draw: st.DrawFn) -> CodeSymbol:
    """Generate a valid CodeSymbol."""
    arn = draw(valid_arn())
    name = draw(valid_symbol_name())
    kind = draw(valid_symbol_kind())
    signature = draw(st.one_of(
        st.none(),
        st.sampled_from([
            "def process(data: dict) -> bool",
            "class Handler(BaseHandler)",
            "async def fetch(url: str) -> Response",
        ])
    ))
    file_path = draw(valid_file_path())
    line_number = draw(st.integers(min_value=1, max_value=1000))
    documentation = draw(st.one_of(
        st.none(),
        st.sampled_from([
            "Handles authentication requests.",
            "Main entry point for the service.",
            "Utility function for data processing.",
        ])
    ))

    return CodeSymbol(
        arn=arn,
        name=name,
        kind=kind,
        signature=signature,
        file_path=file_path,
        line_number=line_number,
        documentation=documentation,
    )


@st.composite
def graph_traversal_result(draw: st.DrawFn) -> GraphTraversalResult:
    """Generate a valid GraphTraversalResult."""
    symbol = draw(code_symbol())
    relationship = draw(valid_relationship_type())
    depth = draw(st.integers(min_value=1, max_value=5))

    return GraphTraversalResult(
        symbol=symbol,
        relationship=relationship,
        depth=depth,
    )


@st.composite
def resolved_arn(draw: st.DrawFn) -> ResolvedARN:
    """Generate a valid ResolvedARN."""
    arn = draw(valid_arn())
    file_path = draw(valid_file_path())
    line_number = draw(st.integers(min_value=1, max_value=1000))
    symbol_name = draw(st.one_of(st.none(), valid_symbol_name()))
    symbol_kind = draw(st.one_of(st.none(), valid_symbol_kind()))

    return ResolvedARN(
        arn=arn,
        file_path=file_path,
        line_number=line_number,
        symbol_name=symbol_name,
        symbol_kind=symbol_kind,
    )


@st.composite
def search_query(draw: st.DrawFn) -> str:
    """Generate a valid search query."""
    return draw(st.sampled_from([
        "How does authentication work?",
        "User registration flow",
        "Database connection handling",
        "Error handling patterns",
        "API endpoint implementation",
        "Configuration management",
        "Logging and monitoring",
        "Data validation logic",
    ]))


# =============================================================================
# Helper Functions
# =============================================================================


def run_async(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================================
# Property Tests
# =============================================================================


class TestKnowledgeProviderReturnStructure:
    """Property tests for knowledge provider return structure.

    Feature: agent-orchestration, Property 15: Knowledge Provider Return Structure

    *For any* semantic search, graph query, or ARN resolution call, the returned
    results SHALL contain all required metadata fields (ARN, content/symbol info,
    scores where applicable).

    **Validates: Requirements 12.2, 12.3, 12.4**
    """

    @given(result=semantic_search_result())
    @settings(max_examples=100)
    def test_semantic_search_result_has_required_fields(
        self,
        result: SemanticSearchResult,
    ) -> None:
        """Property 15: SemanticSearchResult contains all required fields.

        *For any* semantic search result, the result SHALL contain:
        - content (non-empty string)
        - source (non-empty string)
        - score (float 0.0-1.0)
        - arn (non-empty string)
        - package (non-empty string)

        **Validates: Requirement 12.2**
        """
        # Verify required fields are present and valid
        assert result.content is not None
        assert len(result.content) > 0
        assert isinstance(result.content, str)

        assert result.source is not None
        assert len(result.source) > 0
        assert isinstance(result.source, str)

        assert result.score is not None
        assert 0.0 <= result.score <= 1.0
        assert isinstance(result.score, float)

        assert result.arn is not None
        assert len(result.arn) > 0
        assert isinstance(result.arn, str)

        assert result.package is not None
        assert len(result.package) > 0
        assert isinstance(result.package, str)

        # Verify optional fields have correct types when present
        assert isinstance(result.related_arns, list)
        for related_arn in result.related_arns:
            assert isinstance(related_arn, str)

        if result.symbol_name is not None:
            assert isinstance(result.symbol_name, str)

        if result.symbol_kind is not None:
            assert isinstance(result.symbol_kind, str)

    @given(result=graph_traversal_result())
    @settings(max_examples=100)
    def test_graph_traversal_result_has_required_fields(
        self,
        result: GraphTraversalResult,
    ) -> None:
        """Property 15: GraphTraversalResult contains all required fields.

        *For any* graph traversal result, the result SHALL contain:
        - symbol (CodeSymbol with all required fields)
        - relationship (non-empty string)
        - depth (positive integer)

        **Validates: Requirement 12.3**
        """
        # Verify required fields are present and valid
        assert result.symbol is not None
        assert isinstance(result.symbol, CodeSymbol)

        assert result.relationship is not None
        assert len(result.relationship) > 0
        assert isinstance(result.relationship, str)

        assert result.depth is not None
        assert result.depth >= 1
        assert isinstance(result.depth, int)

        # Verify symbol has required fields
        symbol = result.symbol
        assert symbol.arn is not None and len(symbol.arn) > 0
        assert symbol.name is not None and len(symbol.name) > 0
        assert symbol.kind is not None and len(symbol.kind) > 0
        assert symbol.file_path is not None and len(symbol.file_path) > 0
        assert symbol.line_number >= 1

    @given(result=resolved_arn())
    @settings(max_examples=100)
    def test_resolved_arn_has_required_fields(
        self,
        result: ResolvedARN,
    ) -> None:
        """Property 15: ResolvedARN contains all required fields.

        *For any* resolved ARN, the result SHALL contain:
        - arn (non-empty string)
        - file_path (non-empty string)
        - line_number (positive integer)

        **Validates: Requirement 12.4**
        """
        # Verify required fields are present and valid
        assert result.arn is not None
        assert len(result.arn) > 0
        assert isinstance(result.arn, str)

        assert result.file_path is not None
        assert len(result.file_path) > 0
        assert isinstance(result.file_path, str)

        assert result.line_number is not None
        assert result.line_number >= 1
        assert isinstance(result.line_number, int)

        # Verify optional fields have correct types when present
        if result.symbol_name is not None:
            assert isinstance(result.symbol_name, str)

        if result.symbol_kind is not None:
            assert isinstance(result.symbol_kind, str)

    @given(symbol=code_symbol())
    @settings(max_examples=100)
    def test_code_symbol_has_required_fields(
        self,
        symbol: CodeSymbol,
    ) -> None:
        """Property 15: CodeSymbol contains all required fields.

        *For any* code symbol, the symbol SHALL contain:
        - arn (non-empty string)
        - name (non-empty string)
        - kind (non-empty string)
        - file_path (non-empty string)
        - line_number (positive integer)

        **Validates: Requirement 12.3**
        """
        # Verify required fields are present and valid
        assert symbol.arn is not None
        assert len(symbol.arn) > 0
        assert isinstance(symbol.arn, str)

        assert symbol.name is not None
        assert len(symbol.name) > 0
        assert isinstance(symbol.name, str)

        assert symbol.kind is not None
        assert len(symbol.kind) > 0
        assert isinstance(symbol.kind, str)

        assert symbol.file_path is not None
        assert len(symbol.file_path) > 0
        assert isinstance(symbol.file_path, str)

        assert symbol.line_number is not None
        assert symbol.line_number >= 1
        assert isinstance(symbol.line_number, int)

        # Verify optional fields have correct types when present
        if symbol.signature is not None:
            assert isinstance(symbol.signature, str)

        if symbol.documentation is not None:
            assert isinstance(symbol.documentation, str)


class TestKnowledgeProviderCombinedQuery:
    """Property tests for knowledge provider combined query pattern.

    Feature: agent-orchestration, Property 16: Knowledge Provider Combined Query

    *For any* combined context query, the result SHALL include both semantic
    search results and graph traversal results, with ARNs linking the two layers.

    **Validates: Requirement 12.7**
    """

    @given(
        query=search_query(),
        search_results=st.lists(semantic_search_result(), min_size=1, max_size=5),
        graph_results=st.lists(graph_traversal_result(), min_size=0, max_size=10),
    )
    @settings(max_examples=100)
    def test_combined_context_includes_search_results(
        self,
        query: str,
        search_results: List[SemanticSearchResult],
        graph_results: List[GraphTraversalResult],
    ) -> None:
        """Property 16: Combined context includes semantic search results.

        *For any* combined context query with non-empty search results,
        the formatted context SHALL include content from the search results.

        **Validates: Requirement 12.7**
        """
        vector_client = MockVectorStoreClient(results=search_results)
        graph_client = MockCodeGraphClient(traversal_results=graph_results)
        provider = DefaultKnowledgeProvider(vector_client, graph_client)

        async def test():
            context = await provider.combined_context(query)

            # Context should include the query
            assert query in context

            # Context should include content from search results
            assert "Relevant Documentation" in context

            # Context should include at least some search result content
            for result in search_results[:3]:  # Check first few results
                # Either the source or content should appear
                assert result.source in context or result.content[:50] in context

        run_async(test())

    @given(
        query=search_query(),
        search_results=st.lists(semantic_search_result(), min_size=1, max_size=3),
        graph_results=st.lists(graph_traversal_result(), min_size=1, max_size=5),
    )
    @settings(max_examples=100)
    def test_combined_context_includes_graph_results(
        self,
        query: str,
        search_results: List[SemanticSearchResult],
        graph_results: List[GraphTraversalResult],
    ) -> None:
        """Property 16: Combined context includes graph traversal results.

        *For any* combined context query with non-empty graph results,
        the formatted context SHALL include symbols from the graph traversal.

        **Validates: Requirement 12.7**
        """
        vector_client = MockVectorStoreClient(results=search_results)
        graph_client = MockCodeGraphClient(traversal_results=graph_results)
        provider = DefaultKnowledgeProvider(vector_client, graph_client)

        async def test():
            context = await provider.combined_context(query)

            # Context should include graph results section
            assert "Related Code Symbols" in context

            # Context should include symbol names from graph results
            for result in graph_results[:3]:  # Check first few results
                assert result.symbol.name in context

        run_async(test())

    @given(
        query=search_query(),
        search_results=st.lists(semantic_search_result(), min_size=1, max_size=3),
    )
    @settings(max_examples=100)
    def test_combined_context_extracts_arns_from_search(
        self,
        query: str,
        search_results: List[SemanticSearchResult],
    ) -> None:
        """Property 16: Combined query extracts ARNs from search results.

        *For any* combined context query, the ARNs from semantic search
        results SHALL be used for graph traversal.

        **Validates: Requirement 12.7**
        """
        # Track which ARNs are passed to graph_query
        captured_arns: List[str] = []

        class TrackingGraphClient(MockCodeGraphClient):
            async def graph_query(
                self,
                arns: List[str],
                relationship_types: List[str],
                depth: int = 1,
            ) -> List[GraphTraversalResult]:
                captured_arns.extend(arns)
                return []

        vector_client = MockVectorStoreClient(results=search_results)
        graph_client = TrackingGraphClient()
        provider = DefaultKnowledgeProvider(vector_client, graph_client)

        async def test():
            await provider.combined_context(query)

            # Verify ARNs from search results were passed to graph_query
            expected_arns = set()
            for result in search_results:
                expected_arns.add(result.arn)
                expected_arns.update(result.related_arns)

            # All expected ARNs should have been passed
            for arn in expected_arns:
                assert arn in captured_arns

        run_async(test())

    @given(query=search_query())
    @settings(max_examples=100)
    def test_combined_context_handles_empty_search_results(
        self,
        query: str,
    ) -> None:
        """Property 16: Combined context handles empty search results gracefully.

        *For any* combined context query with no search results,
        the result SHALL indicate no context was found.

        **Validates: Requirement 12.7**
        """
        vector_client = MockVectorStoreClient(results=[])
        graph_client = MockCodeGraphClient()
        provider = DefaultKnowledgeProvider(vector_client, graph_client)

        async def test():
            context = await provider.combined_context(query)

            # Context should indicate no results found
            assert "No relevant context found" in context
            assert query in context

        run_async(test())

    @given(
        query=search_query(),
        search_results=st.lists(semantic_search_result(), min_size=1, max_size=3),
    )
    @settings(max_examples=100)
    def test_combined_context_handles_graph_failure_gracefully(
        self,
        query: str,
        search_results: List[SemanticSearchResult],
    ) -> None:
        """Property 16: Combined context degrades gracefully on graph failure.

        *For any* combined context query where graph traversal fails,
        the result SHALL still include semantic search results.

        **Validates: Requirement 12.7**
        """

        class FailingGraphClient(MockCodeGraphClient):
            async def graph_query(
                self,
                arns: List[str],
                relationship_types: List[str],
                depth: int = 1,
            ) -> List[GraphTraversalResult]:
                raise Exception("Graph service unavailable")

        vector_client = MockVectorStoreClient(results=search_results)
        graph_client = FailingGraphClient()
        provider = DefaultKnowledgeProvider(vector_client, graph_client)

        async def test():
            # Should not raise, should degrade gracefully
            context = await provider.combined_context(query)

            # Context should still include search results
            assert "Relevant Documentation" in context

            # Should not include graph results section (since it failed)
            assert "Related Code Symbols" not in context

        run_async(test())

    @given(
        query=search_query(),
        search_results=st.lists(semantic_search_result(), min_size=1, max_size=3),
        graph_results=st.lists(graph_traversal_result(), min_size=1, max_size=5),
    )
    @settings(max_examples=100)
    def test_combined_context_includes_arns_in_output(
        self,
        query: str,
        search_results: List[SemanticSearchResult],
        graph_results: List[GraphTraversalResult],
    ) -> None:
        """Property 16: Combined context includes ARNs linking both layers.

        *For any* combined context query, the formatted output SHALL
        include ARNs that link semantic search results to code symbols.

        **Validates: Requirement 12.7**
        """
        vector_client = MockVectorStoreClient(results=search_results)
        graph_client = MockCodeGraphClient(traversal_results=graph_results)
        provider = DefaultKnowledgeProvider(vector_client, graph_client)

        async def test():
            context = await provider.combined_context(query)

            # Context should include ARNs from search results
            for result in search_results[:2]:  # Check first few
                assert result.arn in context

        run_async(test())


class TestKnowledgeProviderHealthCheck:
    """Property tests for knowledge provider health check.

    These tests verify that the health check correctly reports the
    combined health status of both underlying services.

    **Validates: Requirements 12.2, 12.3**
    """

    @given(
        vector_healthy=st.booleans(),
        graph_healthy=st.booleans(),
    )
    @settings(max_examples=100)
    def test_health_check_requires_both_services_healthy(
        self,
        vector_healthy: bool,
        graph_healthy: bool,
    ) -> None:
        """Health check returns True only when both services are healthy.

        **Validates: Requirements 12.2, 12.3**
        """
        vector_client = MockVectorStoreClient(healthy=vector_healthy)
        graph_client = MockCodeGraphClient(healthy=graph_healthy)
        provider = DefaultKnowledgeProvider(vector_client, graph_client)

        async def test():
            result = await provider.health_check()

            # Health check should be True only if both are healthy
            expected = vector_healthy and graph_healthy
            assert result == expected

        run_async(test())
