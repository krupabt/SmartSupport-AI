import os
import logging
from typing import List, Optional

from app.services.rag.schemas import RetrievedChunk
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
DEFAULT_THRESHOLD = 0.35


class RAGRetriever:
    """Semantic similarity retriever querying the local vector store."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedding_service: Optional[EmbeddingService] = None,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.embedding_service = embedding_service or EmbeddingService()

        cfg_top_k = None
        cfg_threshold = None
        try:
            from flask import current_app, has_app_context
            if has_app_context():
                cfg_top_k = current_app.config.get("RAG_TOP_K")
                cfg_threshold = current_app.config.get("RAG_SIMILARITY_THRESHOLD")
        except Exception:
            pass

        if top_k is not None:
            self.top_k = top_k
        elif cfg_top_k is not None:
            self.top_k = int(cfg_top_k)
        else:
            self.top_k = int(os.getenv("RAG_TOP_K", DEFAULT_TOP_K))

        if threshold is not None:
            self.threshold = threshold
        elif cfg_threshold is not None:
            self.threshold = float(cfg_threshold)
        else:
            self.threshold = float(os.getenv("RAG_SIMILARITY_THRESHOLD", DEFAULT_THRESHOLD))

    def build_query(
        self,
        subject: str,
        description: str,
        category: Optional[str] = None,
        product_service: Optional[str] = None,
    ) -> str:
        """Construct a semantically rich retrieval query without leaking secrets."""
        parts = []
        if category and category.lower() != "general":
            parts.append(f"Category: {category}")
        if product_service:
            parts.append(f"Product/Service: {product_service}")
        if subject:
            parts.append(f"Subject: {subject}")
        if description:
            # First 300 characters of description provide optimal semantic density
            desc_snippet = description.strip()[:300]
            parts.append(f"Details: {desc_snippet}")

        return " | ".join(parts) if parts else subject

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None,
    ) -> List[RetrievedChunk]:
        """Perform vector similarity search and retrieve relevant document chunks."""
        if not query or not query.strip():
            return []

        k = top_k if top_k is not None else self.top_k
        thresh = threshold if threshold is not None else self.threshold

        logger.info(f"RAG retrieving for query: '{query[:60]}...' (top_k={k}, threshold={thresh})")

        query_vec = self.embedding_service.embed_query(query)
        chunks = self.vector_store.search(query_vec, top_k=k, threshold=thresh)

        logger.info(f"Retrieved {len(chunks)} relevant chunks above threshold {thresh}.")
        return chunks
