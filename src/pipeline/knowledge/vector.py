"""Vector store client for semantic search against Qdrant.

This module provides an async client for querying the Qdrant vector store
to perform semantic search. Results include ARN metadata that links to
the code graph for structural traversal.

The vector store contains embeddings of .archon.md documentation files,
generated from SCIP output. Each chunk includes:
- Content: The text content of the documentation chunk
- Source: The source file path
- ARN: Archon Resource Name linking to the code graph
- Related ARNs: ARNs of related symbols mentioned in the content
- Symbol metadata: Name, kind, and package information

Requirements:
- 12.2: Semantic search against vector store
- 12.6: Return results with ARN metadata

Source:
- src/pipeline/knowledge/provider.py (SemanticSearchResult model)
- ArchonKnowledgeBaseInfrastructure/src/common/vector_store.py (Qdrant patterns)
"""

import logging
from typing import Any, Optional

import httpx

from src.pipeline.knowledge.provider import SemanticSearchResult


logger = logging.getLogger(__name__)


class VectorStoreError(Exception):
    """Raised when vector store operations fail.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code from the response if applicable.
        response_body: Response body from Qdrant API if applicable.
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


class VectorStoreClient:
    """Async client for semantic search against Qdrant vector store.

    This client queries the Qdrant vector store to find documentation
    chunks relevant to a natural language query. Results include ARN
    metadata for subsequent code graph traversal.

    The client uses Qdrant's REST API via httpx for async HTTP requests,
    consistent with the pipeline's approach in github/client.py.

    Attributes:
        base_url: Base URL of the Qdrant server (e.g., http://qdrant:6333).
        collection_name: Name of the Qdrant collection to search.
        embedding_url: URL of the embedding service for query vectorization.
        timeout: Request timeout in seconds.

    Example:
        >>> client = VectorStoreClient(
        ...     base_url="http://qdrant:6333",
        ...     collection_name="archon-docs",
        ...     embedding_url="http://embedding-svc:8000",
        ... )
        >>> async with client:
        ...     results = await client.semantic_search("authentication flow")
        ...     for result in results:
        ...         print(f"{result.score:.2f}: {result.arn}")

    Or without context manager:
        >>> client = VectorStoreClient(...)
        >>> results = await client.semantic_search("authentication flow")
        >>> await client.close()
    """

    def __init__(
        self,
        base_url: str,
        collection_name: str,
        embedding_url: str,
        timeout: float = 30.0,
    ):
        """Initialize the vector store client.

        Args:
            base_url: Base URL of the Qdrant server.
            collection_name: Name of the Qdrant collection to search.
            embedding_url: URL of the embedding service for query vectorization.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.collection_name = collection_name
        self.embedding_url = embedding_url.rstrip("/")
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

    async def __aenter__(self) -> "VectorStoreClient":
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

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding vector for a text query.

        Calls the embedding service to generate a vector representation
        of the query text for similarity search.

        Args:
            text: The text to embed.

        Returns:
            List of floats representing the embedding vector.

        Raises:
            VectorStoreError: If embedding generation fails.
        """
        try:
            response = await self.client.post(
                f"{self.embedding_url}/embed",
                json={"text": text},
            )

            if response.status_code != 200:
                logger.error(
                    "Embedding service error",
                    extra={
                        "status_code": response.status_code,
                        "response": response.text[:500],
                    },
                )
                raise VectorStoreError(
                    message=f"Embedding service error: {response.status_code}",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            data = response.json()
            return data["embedding"]

        except httpx.RequestError as e:
            logger.error(
                "Embedding service request failed",
                extra={"error": str(e)},
            )
            raise VectorStoreError(
                message=f"Embedding service request failed: {e}",
            ) from e

    async def semantic_search(
        self,
        query: str,
        limit: int = 10,
        package_filter: Optional[str] = None,
        score_threshold: Optional[float] = None,
    ) -> list[SemanticSearchResult]:
        """Search vector store for relevant content.

        Performs semantic search against the Qdrant vector store by:
        1. Generating an embedding for the query text
        2. Querying Qdrant for similar vectors
        3. Parsing results into SemanticSearchResult models

        Args:
            query: Natural language search query.
            limit: Maximum number of results to return (default: 10).
            package_filter: Optional package name to filter results.
            score_threshold: Minimum similarity score (optional).

        Returns:
            list[SemanticSearchResult]: Ranked list of matching content
                chunks with ARN metadata, ordered by relevance score.

        Raises:
            VectorStoreError: If the search fails.
            ValueError: If query is empty.

        Example:
            results = await client.semantic_search(
                "How does user authentication work?",
                limit=5,
                package_filter="auth-service"
            )
            for result in results:
                print(f"{result.score:.2f}: {result.content[:100]}...")
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        query_embedding = await self._get_embedding(query)

        search_request = self._build_search_request(
            query_embedding=query_embedding,
            limit=limit,
            package_filter=package_filter,
            score_threshold=score_threshold,
        )

        try:
            response = await self.client.post(
                f"{self.base_url}/collections/{self.collection_name}/points/query",
                json=search_request,
            )

            if response.status_code != 200:
                logger.error(
                    "Qdrant search error",
                    extra={
                        "status_code": response.status_code,
                        "response": response.text[:500],
                        "collection": self.collection_name,
                    },
                )
                raise VectorStoreError(
                    message=f"Qdrant search error: {response.status_code}",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            data = response.json()
            return self._parse_search_results(data)

        except httpx.RequestError as e:
            logger.error(
                "Qdrant request failed",
                extra={
                    "error": str(e),
                    "collection": self.collection_name,
                },
            )
            raise VectorStoreError(
                message=f"Qdrant request failed: {e}",
            ) from e

    def _build_search_request(
        self,
        query_embedding: list[float],
        limit: int,
        package_filter: Optional[str],
        score_threshold: Optional[float],
    ) -> dict[str, Any]:
        """Build the Qdrant search request payload.

        Args:
            query_embedding: The query embedding vector.
            limit: Maximum number of results.
            package_filter: Optional package name filter.
            score_threshold: Optional minimum score threshold.

        Returns:
            Dictionary containing the Qdrant search request.
        """
        request: dict[str, Any] = {
            "query": query_embedding,
            "limit": limit,
            "with_payload": True,
        }

        if score_threshold is not None:
            request["score_threshold"] = score_threshold

        if package_filter is not None:
            request["filter"] = {
                "must": [
                    {
                        "key": "package",
                        "match": {"value": package_filter},
                    }
                ]
            }

        return request

    def _parse_search_results(
        self,
        response_data: dict[str, Any],
    ) -> list[SemanticSearchResult]:
        """Parse Qdrant search response into SemanticSearchResult models.

        Extracts content and ARN metadata from each search hit and
        constructs SemanticSearchResult instances.

        Args:
            response_data: The JSON response from Qdrant.

        Returns:
            List of SemanticSearchResult models.
        """
        results: list[SemanticSearchResult] = []
        points = response_data.get("result", [])

        for point in points:
            payload = point.get("payload", {})
            score = point.get("score", 0.0)

            content = payload.get("content", "")
            source = payload.get("source", "")
            arn = payload.get("arn", "")
            package = payload.get("package", "")

            if not content or not source or not arn or not package:
                logger.warning(
                    "Skipping search result with missing required fields",
                    extra={
                        "has_content": bool(content),
                        "has_source": bool(source),
                        "has_arn": bool(arn),
                        "has_package": bool(package),
                    },
                )
                continue

            result = SemanticSearchResult(
                content=content,
                source=source,
                score=self._normalize_score(score),
                arn=arn,
                related_arns=payload.get("related_arns", []),
                symbol_name=payload.get("symbol_name"),
                symbol_kind=payload.get("symbol_kind"),
                package=package,
            )
            results.append(result)

        logger.debug(
            "Parsed search results",
            extra={
                "total_points": len(points),
                "valid_results": len(results),
            },
        )

        return results

    def _normalize_score(self, score: float) -> float:
        """Normalize similarity score to 0.0-1.0 range.

        Qdrant returns cosine similarity scores which are already in
        the -1.0 to 1.0 range. We normalize to 0.0-1.0 for consistency
        with the SemanticSearchResult model.

        Args:
            score: Raw similarity score from Qdrant.

        Returns:
            Normalized score in 0.0-1.0 range.
        """
        normalized = (score + 1.0) / 2.0
        return max(0.0, min(1.0, normalized))

    async def health_check(self) -> bool:
        """Check if Qdrant is healthy and the collection exists.

        Verifies connectivity to the Qdrant server and confirms the
        configured collection exists.

        Returns:
            True if Qdrant is reachable and collection exists,
            False otherwise.

        Example:
            if await client.health_check():
                results = await client.semantic_search(query)
            else:
                logger.warning("Vector store unavailable")
        """
        try:
            response = await self.client.get(
                f"{self.base_url}/collections/{self.collection_name}",
            )
            return response.status_code == 200

        except Exception as e:
            logger.warning(
                "Vector store health check failed",
                extra={
                    "error": str(e),
                    "collection": self.collection_name,
                },
            )
            return False
