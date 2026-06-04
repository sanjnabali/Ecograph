"""
src/ecograph/graphrag/vector_store.py

Qdrant Cloud vector store client for GraphRAG dense retrieval.

Manages:
- Collection creation with Product Quantization (PQ) compression
  (Qdrant Cloud free tier: 1 GB storage, ~1M 384-dim vectors)
- Upsert of community summaries and subgraph chunks as dense vectors
- Approximate-nearest-neighbour search with optional metadata filter
- Cosine similarity (sentence-transformers/all-MiniLM-L6-v2, 384-dim)

SOLID:
- IVectorStore ABC defines the interface (DIP)
- QdrantVectorStore is the production implementation
- MockVectorStore is the test double
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

_COLLECTION      = "ecograph_graphrag"
_VECTOR_DIM      = 384
_DISTANCE        = "Cosine"

# --------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------

class IVectorStore(ABC):
    @abstractmethod
    def upsert(self, doc_id: str, text: str, metadata: dict) -> None: ...
    @abstractmethod
    def search(self, query: str, top_k: int, filter_: Optional[dict] = None) -> list[dict]: ...
    @abstractmethod
    def delete(self, doc_id: str) -> None: ...

# --------------------------------------------------------------------------
# Embedding helper
# --------------------------------------------------------------------------

def _embed(texts: list[str]) -> list[list[float]]:
    """
    Compute sentence embeddings using sentence-transformers.
    Falls back to zero vectors if the library is not installed
    (so the rest of the pipeline degrades gracefully in tests).
    """
    try:
        from sentence_transformers import SentenceTransformer # type: ignore[import]
        _embed_model = getattr(_embed, "_model", None) or SentenceTransformer("all-MiniLM-L6-v2")
        return _embed_model.encode(texts, convert_to_numpy=True).tolist()
    except ImportError:
        logger.warning("sentence-transformers not installed - using zero vectors.")
        return [[0.0] * _VECTOR_DIM for _ in texts]

# --------------------------------------------------------------------------
# Qdrant implementation
# --------------------------------------------------------------------------

class QdrantVectorStore(IVectorStore):
    """
    Qdrant Cloud vector store with Product Quantization compression.

    Parameters
    ----------
    url:
        Qdrant Cloud cluster URL (e.g. https://xxx.cloud.qdrant.io:6333).
    api_key:
        Qdrant Cloud API key.
    collection:
        Collection name. Default: ecograph_graphrag.
    """
    def __init__(
        self,
        url: str,
        api_key: str,
        collection: str = _COLLECTION,
    ):
        self._url = url
        self._api_key = api_key
        self._collection = collection
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import QdrantClient # type: ignore[import]
            from qdrant_client.models import ( # type: ignore[import]
                Distance, VectorParams, ProductQuantization,
                ProductQuantizationConfig, CompressionRatio,
                OptimizersConfigDiff,
            )
        except ImportError as exc:
            raise ImportError(
                "qdrant-client is required. Install with: pip install qdrant-client"
            ) from exc

        self._client = QdrantClient(url=self._url, api_key=self._api_key, timeout=20)

        # Create collection if absent
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=_VECTOR_DIM, distance=Distance.COSINE),
                optimizers_config=OptimizersConfigDiff(indexing_threshold=10_000),
            )
            logger.info("Created Qdrant collection '%s'.", self._collection)
        return self._client

    def upsert(self, doc_id: str, text: str, metadata: dict) -> None:
        """Embed 'text' and upsert a single point into the collection."""
        from qdrant_client.models import PointStruct # type: ignore[import]
        vector = _embed([text])[0]
        point = PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id)),
            vector=vector,
            payload={"doc_id": doc_id, "text": text, **metadata},
        )
        self._get_client().upsert(collection_name=self._collection, points=[point])

    def upsert_batch(self, docs: list[dict]) -> None:
        """
        Batch upsert. Each dict must have: doc_id, text, and optional metadata keys.
        """
        from qdrant_client.models import PointStruct # type: ignore[import]
        texts = [d["text"] for d in docs]
        vectors = _embed(texts)
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, d["doc_id"])),
                vector=vectors[i],
                payload={"doc_id": d["doc_id"], "text": d["text"],
                         **{k: v for k, v in d.items() if k not in ("doc_id", "text")}},
            )
            for i, d in enumerate(docs)
        ]
        self._get_client().upsert(collection_name=self._collection, points=points)
        logger.debug("Upserted %d vectors into '%s'.", len(points), self._collection)

    def search(self,
        query: str,
        top_k: int = 5,
        filter_: Optional[dict] = None,
    ) -> list[dict]:
        """
        ANN search. Returns list of dicts with keys: doc_id, text, score, metadata.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue # type: ignore[import]
        vector = _embed([query])[0]
        qdrant_filter = None
        if filter_:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filter_.items()
            ]
            qdrant_filter = Filter(must=conditions)

        results = self._get_client().search(
            collection_name=self._collection,
            query_vector=vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        return [
            {
                "doc_id": r.payload.get("doc_id", ""),
                "text": r.payload.get("text", ""),
                "score": r.score,
                "metadata": {k: v for k, v in r.payload.items() if k not in ("doc_id", "text")},
            }
            for r in results
        ]

    def delete(self, doc_id: str) -> None:
        from qdrant_client.models import PointIdsList # type: ignore[import]
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))
        self._get_client().delete(
            collection_name=self._collection,
            points_selector=PointIdsList(points=[point_id]),
        )


# --------------------------------------------------------------------------
# Mock (test double)
# --------------------------------------------------------------------------

class MockVectorStore(IVectorStore):
    """In-memory vector store for unit tests."""
    def __init__(self) -> None:
        self._store: list[dict] = []

    def upsert(self, doc_id: str, text: str, metadata: dict) -> None:
        self._store.append({"doc_id": doc_id, "text": text, **metadata})

    def search(self, query: str, top_k: int, filter_: Optional[dict] = None) -> list[dict]:
        results = self._store[:]
        if filter_:
            results = [r for r in results if all(r.get(k) == v for k, v in filter_.items())]
        return [{"doc_id": r["doc_id"], "text": r["text"], "score": 1.0, "metadata": r}
                for r in results[:top_k]]

    def delete(self, doc_id: str) -> None:
        self._store = [r for r in self._store if r["doc_id"] != doc_id]


# --------------------------------------------------------------------------
# Singleton factory
# --------------------------------------------------------------------------

_instance: Optional[IVectorStore] = None

def get_vector_store() -> IVectorStore:
    """
    Return the process-level vector store instance.
    Reads QDRANT_URL and QDRANT_API_KEY from settings.
    Falls back to MockVectorStore if credentials are absent (dev mode).
    """
    global _instance
    if _instance is not None:
        return _instance

    try:
        from ecograph.config.settings import settings
        url = getattr(settings, "QDRANT_URL", None)
        api_key = getattr(settings, "QDRANT_API_KEY", None)
        if url and api_key:
            _instance = QdrantVectorStore(url=url, api_key=api_key)
            logger.info("QdrantVectorStore initialised (url=%s).", url)
        else:
            logger.warning("QDRANT credentials absent - using MockVectorStore.")
            _instance = MockVectorStore()
    except Exception as exc:
        logger.error("Could not initialise vector store (%s) - using mock.", exc)
        _instance = MockVectorStore()
    return _instance