"""Knowledge provider interface for two-layer retrieval.

This module defines the abstract interface for the knowledge provider that
combines vector store semantic search with code graph traversal. The two-layer
approach enables rich context retrieval:

1. Vector Store (Semantic Search): Query embeddings of .archon.md files to find
   relevant content based on natural language queries. Results include ARN
   metadata linking to the code graph.

2. Code Graph (Structural Traversal): Use ARNs from semantic search to traverse
   SCIP-derived relationships (contains, references, implements, extends, imports)
   and discover related code symbols.

The combined query pattern:
    semantic search → extract ARNs → graph traversal → combined context

Requirements:
- 12.1: Knowledge provider interface for two-layer retrieval
- 12.2: Semantic search against vector store
- 12.3: Graph traversal for code relationships
- 12.4: ARN resolution to file locations

The models use Pydantic for validation, consistent with the pipeline's
approach in webhook/models.py, state/models.py, classifier/models.py,
and github/models.py.
"""

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field


class SemanticSearchResult(BaseModel):
    """Result from vector store semantic search.

    Each result represents a chunk of documentation content that matched
    the search query, along with metadata linking it to the code graph.

    The ARN (Archon Resource Name) is the key bridge between the vector
    store and code graph layers, enabling structural traversal from
    semantic search results.

    Attributes:
        content: The text content of the matched chunk.
        source: Source file path where the content originated.
        score: Relevance score from the vector search (0.0-1.0, higher is better).
        arn: Archon Resource Name linking to the code graph.
        related_arns: List of ARNs for related symbols mentioned in the content.
        symbol_name: Name of the code symbol if this chunk describes one.
        symbol_kind: Kind of symbol (function, class, method, etc.) if applicable.
        package: Package name containing this content.
    """

    content: str = Field(
        ...,
        min_length=1,
        description="The text content of the matched chunk",
    )

    source: str = Field(
        ...,
        min_length=1,
        description="Source file path where the content originated",
    )

    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Relevance score from vector search (0.0-1.0)",
    )

    arn: str = Field(
        ...,
        min_length=1,
        description="Archon Resource Name linking to the code graph",
    )

    related_arns: list[str] = Field(
        default_factory=list,
        description="List of ARNs for related symbols mentioned in the content",
    )

    symbol_name: Optional[str] = Field(
        default=None,
        description="Name of the code symbol if this chunk describes one",
    )

    symbol_kind: Optional[str] = Field(
        default=None,
        description="Kind of symbol (function, class, method, etc.)",
    )

    package: str = Field(
        ...,
        min_length=1,
        description="Package name containing this content",
    )


class CodeSymbol(BaseModel):
    """A code symbol from the SCIP-derived code graph.

    Represents a symbol (function, class, method, variable, etc.) extracted
    from source code via SCIP indexing. Symbols are the nodes in the code
    graph, connected by relationships like contains, references, implements.

    Attributes:
        arn: Archon Resource Name uniquely identifying this symbol.
        name: The symbol's name as it appears in code.
        kind: The kind of symbol (function, class, method, variable, etc.).
        signature: The symbol's type signature if available.
        file_path: Path to the file containing this symbol.
        line_number: Line number where the symbol is defined.
        documentation: Documentation string if available.
    """

    arn: str = Field(
        ...,
        min_length=1,
        description="Archon Resource Name uniquely identifying this symbol",
    )

    name: str = Field(
        ...,
        min_length=1,
        description="The symbol's name as it appears in code",
    )

    kind: str = Field(
        ...,
        min_length=1,
        description="The kind of symbol (function, class, method, etc.)",
    )

    signature: Optional[str] = Field(
        default=None,
        description="The symbol's type signature if available",
    )

    file_path: str = Field(
        ...,
        min_length=1,
        description="Path to the file containing this symbol",
    )

    line_number: int = Field(
        ...,
        ge=1,
        description="Line number where the symbol is defined",
    )

    documentation: Optional[str] = Field(
        default=None,
        description="Documentation string if available",
    )


class GraphTraversalResult(BaseModel):
    """Result from code graph traversal.

    Represents a symbol discovered through graph traversal from a starting
    ARN, along with the relationship type and traversal depth.

    The relationship types correspond to SCIP-derived relationships:
    - contains: Parent symbol contains child symbol
    - references: Symbol references another symbol
    - implements: Symbol implements an interface/protocol
    - extends: Symbol extends/inherits from another
    - imports: Module imports another module

    Attributes:
        symbol: The code symbol discovered through traversal.
        relationship: The type of relationship (contains, references, etc.).
        depth: How many hops from the starting ARN (1 = direct relationship).
    """

    symbol: CodeSymbol = Field(
        ...,
        description="The code symbol discovered through traversal",
    )

    relationship: str = Field(
        ...,
        min_length=1,
        description="The type of relationship (contains, references, etc.)",
    )

    depth: int = Field(
        ...,
        ge=1,
        description="How many hops from the starting ARN",
    )


class ResolvedARN(BaseModel):
    """Result of resolving an ARN to a file location.

    Provides the concrete file system location and symbol information
    for a given ARN, enabling navigation from abstract identifiers to
    actual source code.

    Attributes:
        arn: The ARN that was resolved.
        file_path: Path to the file containing the symbol.
        line_number: Line number where the symbol is defined.
        symbol_name: Name of the symbol if applicable.
        symbol_kind: Kind of symbol if applicable.
    """

    arn: str = Field(
        ...,
        min_length=1,
        description="The ARN that was resolved",
    )

    file_path: str = Field(
        ...,
        min_length=1,
        description="Path to the file containing the symbol",
    )

    line_number: int = Field(
        ...,
        ge=1,
        description="Line number where the symbol is defined",
    )

    symbol_name: Optional[str] = Field(
        default=None,
        description="Name of the symbol if applicable",
    )

    symbol_kind: Optional[str] = Field(
        default=None,
        description="Kind of symbol if applicable",
    )


class KnowledgeProvider(ABC):
    """Abstract interface for two-layer knowledge retrieval.

    The KnowledgeProvider combines vector store semantic search with code
    graph traversal to provide rich context for issue understanding and
    implementation. Implementations query:

    1. Vector store for semantic search (returns content with ARN metadata)
    2. Code graph for structural traversal (uses ARNs to find related symbols)

    The combined query pattern enables finding relevant documentation via
    natural language, then expanding context through code relationships.

    Concrete implementations include:
    - DefaultKnowledgeProvider: Queries Qdrant vector store and GraphQL API
    - MockKnowledgeProvider: For testing without external dependencies

    Requirements:
    - 12.1: Knowledge provider interface for two-layer retrieval
    - 12.2: Semantic search against vector store
    - 12.3: Graph traversal for code relationships
    - 12.4: ARN resolution to file locations

    Example usage:
        provider = DefaultKnowledgeProvider(vector_url, graphql_url)

        # Semantic search for relevant content
        results = await provider.semantic_search("authentication flow")

        # Extract ARNs and traverse graph for related symbols
        arns = [r.arn for r in results]
        related = await provider.graph_query(
            arns,
            ["references", "contains"],
            depth=2
        )

        # Resolve specific ARN to file location
        location = await provider.resolve_arn(arns[0])
    """

    @abstractmethod
    async def semantic_search(
        self,
        query: str,
        limit: int = 10,
        package_filter: Optional[str] = None,
    ) -> list[SemanticSearchResult]:
        """Search vector store for relevant content.

        Performs semantic search against the vector store containing
        embeddings of .archon.md documentation files. Results include
        ARN metadata for subsequent graph traversal.

        Args:
            query: Natural language search query.
            limit: Maximum number of results to return (default: 10).
            package_filter: Optional package name to filter results.

        Returns:
            list[SemanticSearchResult]: Ranked list of matching content
                chunks with ARN metadata, ordered by relevance score.

        Raises:
            ConnectionError: If vector store is unavailable.
            ValueError: If query is empty or invalid.

        Example:
            results = await provider.semantic_search(
                "How does user authentication work?",
                limit=5,
                package_filter="auth-service"
            )
            for result in results:
                print(f"{result.score:.2f}: {result.content[:100]}...")
        """
        pass

    @abstractmethod
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

        Supported relationship types:
        - contains: Parent symbol contains child symbol
        - references: Symbol references another symbol
        - implements: Symbol implements an interface/protocol
        - extends: Symbol extends/inherits from another
        - imports: Module imports another module

        Args:
            arns: List of ARNs to start traversal from.
            relationship_types: Types of relationships to follow.
            depth: Maximum traversal depth (default: 1, direct relationships).

        Returns:
            list[GraphTraversalResult]: Symbols discovered through traversal,
                each with relationship type and depth from starting ARN.

        Raises:
            ConnectionError: If code graph service is unavailable.
            ValueError: If arns list is empty or relationship_types invalid.

        Example:
            related = await provider.graph_query(
                arns=["arn:archon:auth-service:src/auth.py:AuthHandler"],
                relationship_types=["references", "contains"],
                depth=2
            )
            for result in related:
                print(f"{result.relationship} -> {result.symbol.name}")
        """
        pass

    @abstractmethod
    async def resolve_arn(self, arn: str) -> Optional[ResolvedARN]:
        """Resolve ARN to file location.

        Looks up an ARN in the code graph to find its concrete file
        system location and symbol information. Returns None if the
        ARN cannot be resolved.

        Args:
            arn: The Archon Resource Name to resolve.

        Returns:
            Optional[ResolvedARN]: File location and symbol info if found,
                None if the ARN cannot be resolved.

        Raises:
            ConnectionError: If code graph service is unavailable.
            ValueError: If arn is empty or malformed.

        Example:
            location = await provider.resolve_arn(
                "arn:archon:auth-service:src/auth.py:AuthHandler"
            )
            if location:
                print(f"Found at {location.file_path}:{location.line_number}")
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if knowledge services are available.

        Verifies connectivity to both the vector store and code graph
        services. Returns True only if both services are healthy.

        Returns:
            bool: True if all knowledge services are available and healthy,
                False if any service is unavailable or unhealthy.

        Example:
            if await provider.health_check():
                results = await provider.semantic_search(query)
            else:
                logger.warning("Knowledge services unavailable")
        """
        pass



class DefaultKnowledgeProvider(KnowledgeProvider):
    """Default implementation of KnowledgeProvider using Qdrant and GraphQL.

    This provider implements the two-layer knowledge retrieval pattern:
    1. Semantic search against Qdrant vector store
    2. Graph traversal via GraphQL for structural relationships

    The combined query pattern enables rich context retrieval:
    - Semantic search finds relevant documentation chunks
    - ARNs from results are used to traverse the code graph
    - Related symbols provide structural context

    Attributes:
        vector_client: Client for Qdrant vector store queries.
        graph_client: Client for GraphQL code graph queries.

    Requirements:
    - 12.6: Default implementation queries vector store and GraphQL API
    - 12.7: Combined query pattern for rich context

    Example:
        >>> from src.pipeline.knowledge.vector import VectorStoreClient
        >>> from src.pipeline.knowledge.graph import CodeGraphClient
        >>>
        >>> vector_client = VectorStoreClient(
        ...     base_url="http://qdrant:6333",
        ...     collection_name="archon-docs",
        ...     embedding_url="http://embedding-svc:8000",
        ... )
        >>> graph_client = CodeGraphClient(
        ...     graphql_url="http://code-graph:8080/graphql",
        ... )
        >>> provider = DefaultKnowledgeProvider(vector_client, graph_client)
        >>>
        >>> async with provider:
        ...     # Combined context retrieval
        ...     context = await provider.combined_context("authentication flow")
        ...     print(context)
    """

    def __init__(
        self,
        vector_client: "VectorStoreClient",
        graph_client: "CodeGraphClient",
    ):
        """Initialize the default knowledge provider.

        Args:
            vector_client: Client for Qdrant vector store queries.
            graph_client: Client for GraphQL code graph queries.
        """
        self.vector_client = vector_client
        self.graph_client = graph_client

    async def close(self) -> None:
        """Close both clients and release resources."""
        await self.vector_client.close()
        await self.graph_client.close()

    async def __aenter__(self) -> "DefaultKnowledgeProvider":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        """Async context manager exit - close both clients."""
        await self.close()

    async def semantic_search(
        self,
        query: str,
        limit: int = 10,
        package_filter: Optional[str] = None,
    ) -> list[SemanticSearchResult]:
        """Search vector store for relevant content.

        Delegates to the vector store client to perform semantic search
        against the Qdrant collection.

        Args:
            query: Natural language search query.
            limit: Maximum number of results to return (default: 10).
            package_filter: Optional package name to filter results.

        Returns:
            list[SemanticSearchResult]: Ranked list of matching content
                chunks with ARN metadata, ordered by relevance score.

        Raises:
            ConnectionError: If vector store is unavailable.
            ValueError: If query is empty or invalid.
        """
        return await self.vector_client.semantic_search(
            query=query,
            limit=limit,
            package_filter=package_filter,
        )

    async def graph_query(
        self,
        arns: list[str],
        relationship_types: list[str],
        depth: int = 1,
    ) -> list[GraphTraversalResult]:
        """Traverse code graph from given ARNs.

        Delegates to the code graph client to traverse relationships
        from the given ARNs.

        Args:
            arns: List of ARNs to start traversal from.
            relationship_types: Types of relationships to follow.
            depth: Maximum traversal depth (default: 1, direct relationships).

        Returns:
            list[GraphTraversalResult]: Symbols discovered through traversal,
                each with relationship type and depth from starting ARN.

        Raises:
            ConnectionError: If code graph service is unavailable.
            ValueError: If arns list is empty or relationship_types invalid.
        """
        return await self.graph_client.graph_query(
            arns=arns,
            relationship_types=relationship_types,
            depth=depth,
        )

    async def resolve_arn(self, arn: str) -> Optional[ResolvedARN]:
        """Resolve ARN to file location.

        Delegates to the code graph client to resolve the ARN.

        Args:
            arn: The Archon Resource Name to resolve.

        Returns:
            Optional[ResolvedARN]: File location and symbol info if found,
                None if the ARN cannot be resolved.

        Raises:
            ConnectionError: If code graph service is unavailable.
            ValueError: If arn is empty or malformed.
        """
        return await self.graph_client.resolve_arn(arn)

    async def health_check(self) -> bool:
        """Check if knowledge services are available.

        Verifies connectivity to both the vector store and code graph
        services. Returns True only if both services are healthy.

        Returns:
            bool: True if all knowledge services are available and healthy,
                False if any service is unavailable or unhealthy.
        """
        vector_healthy = await self.vector_client.health_check()
        graph_healthy = await self.graph_client.health_check()
        return vector_healthy and graph_healthy

    async def combined_context(
        self,
        query: str,
        limit: int = 10,
        package_filter: Optional[str] = None,
        relationship_types: Optional[list[str]] = None,
        depth: int = 2,
    ) -> str:
        """Execute the combined query pattern for rich context retrieval.

        This method implements the two-layer knowledge retrieval pattern:
        1. Semantic search → get relevant documentation chunks with ARNs
        2. Extract ARNs from results
        3. Graph traversal → get related code symbols
        4. Combine into formatted context string

        The combined context includes both semantic search results (natural
        language documentation) and structural relationships (code symbols
        and their connections).

        Args:
            query: Natural language search query.
            limit: Maximum number of semantic search results (default: 10).
            package_filter: Optional package name to filter results.
            relationship_types: Types of relationships to follow in graph
                traversal. Defaults to ["references", "contains", "implements"].
            depth: Maximum graph traversal depth (default: 2).

        Returns:
            str: Formatted context string combining semantic search results
                and graph traversal results.

        Raises:
            ConnectionError: If knowledge services are unavailable.
            ValueError: If query is empty.

        Example:
            context = await provider.combined_context(
                "How does user authentication work?",
                limit=5,
                relationship_types=["references", "contains"],
                depth=2,
            )
            # context contains formatted documentation and related symbols
        """
        if relationship_types is None:
            relationship_types = ["references", "contains", "implements"]

        # Step 1: Semantic search
        search_results = await self.semantic_search(
            query=query,
            limit=limit,
            package_filter=package_filter,
        )

        if not search_results:
            return self._format_empty_context(query)

        # Step 2: Extract ARNs from search results
        arns = self._extract_arns(search_results)

        # Step 3: Graph traversal for related symbols
        graph_results: list[GraphTraversalResult] = []
        if arns:
            try:
                graph_results = await self.graph_query(
                    arns=arns,
                    relationship_types=relationship_types,
                    depth=depth,
                )
            except Exception:
                # Degrade gracefully if graph query fails
                pass

        # Step 4: Combine into formatted context
        return self._format_context(query, search_results, graph_results)

    def _extract_arns(
        self,
        search_results: list[SemanticSearchResult],
    ) -> list[str]:
        """Extract unique ARNs from semantic search results.

        Collects ARNs from both the primary ARN field and related_arns
        lists, deduplicating the results.

        Args:
            search_results: Results from semantic search.

        Returns:
            List of unique ARNs.
        """
        arns: set[str] = set()
        for result in search_results:
            arns.add(result.arn)
            arns.update(result.related_arns)
        return list(arns)

    def _format_empty_context(self, query: str) -> str:
        """Format context when no results are found.

        Args:
            query: The original search query.

        Returns:
            Formatted string indicating no results.
        """
        return f"No relevant context found for query: {query}"

    def _format_context(
        self,
        query: str,
        search_results: list[SemanticSearchResult],
        graph_results: list[GraphTraversalResult],
    ) -> str:
        """Format combined context from search and graph results.

        Creates a structured context string with:
        - Query summary
        - Semantic search results (documentation chunks)
        - Related code symbols from graph traversal

        Args:
            query: The original search query.
            search_results: Results from semantic search.
            graph_results: Results from graph traversal.

        Returns:
            Formatted context string.
        """
        sections: list[str] = []

        # Header
        sections.append(f"# Context for: {query}\n")

        # Semantic search results section
        sections.append("## Relevant Documentation\n")
        for i, result in enumerate(search_results, 1):
            sections.append(self._format_search_result(i, result))

        # Graph traversal results section
        if graph_results:
            sections.append("\n## Related Code Symbols\n")
            for result in graph_results:
                sections.append(self._format_graph_result(result))

        return "\n".join(sections)

    def _format_search_result(
        self,
        index: int,
        result: SemanticSearchResult,
    ) -> str:
        """Format a single semantic search result.

        Args:
            index: Result index (1-based).
            result: The search result to format.

        Returns:
            Formatted string for the result.
        """
        lines: list[str] = []
        lines.append(f"### {index}. {result.source} (score: {result.score:.2f})")

        if result.symbol_name:
            symbol_info = f"**Symbol:** {result.symbol_name}"
            if result.symbol_kind:
                symbol_info += f" ({result.symbol_kind})"
            lines.append(symbol_info)

        lines.append(f"**Package:** {result.package}")
        lines.append(f"**ARN:** `{result.arn}`")
        lines.append("")
        lines.append(result.content)
        lines.append("")

        return "\n".join(lines)

    def _format_graph_result(self, result: GraphTraversalResult) -> str:
        """Format a single graph traversal result.

        Args:
            result: The graph traversal result to format.

        Returns:
            Formatted string for the result.
        """
        symbol = result.symbol
        lines: list[str] = []

        lines.append(f"- **{symbol.name}** ({symbol.kind})")
        lines.append(f"  - Relationship: {result.relationship} (depth: {result.depth})")
        lines.append(f"  - Location: `{symbol.file_path}:{symbol.line_number}`")

        if symbol.signature:
            lines.append(f"  - Signature: `{symbol.signature}`")

        if symbol.documentation:
            # Truncate long documentation
            doc = symbol.documentation
            if len(doc) > 200:
                doc = doc[:200] + "..."
            lines.append(f"  - Doc: {doc}")

        return "\n".join(lines)
