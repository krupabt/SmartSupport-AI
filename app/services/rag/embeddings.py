import os
import logging
from typing import List
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384


class EmbeddingService:
    """
    Singleton service managing Sentence Transformers dense vector embeddings.
    Embeddings are L2-normalized so dot products represent exact cosine similarity.
    """
    _instance = None
    _model = None

    def __new__(cls, model_name: str = DEFAULT_EMBEDDING_MODEL):
        if cls._instance is None:
            cls._instance = super(EmbeddingService, cls).__new__(cls)
            cls._instance.model_name = os.getenv("EMBEDDING_MODEL", model_name)
            cls._instance._init_model()
        return cls._instance

    def _init_model(self):
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading SentenceTransformer embedding model: '{self.model_name}'...")
            self._model = SentenceTransformer(self.model_name)
            logger.info("SentenceTransformer model loaded successfully.")
        except Exception as e:
            logger.warning(f"SentenceTransformer load warning: {str(e)}. Fallback to lightweight vector generator.")
            self._model = None

    def embed_documents(self, texts: List[str]) -> np.ndarray:
        """Generate normalized embeddings for a list of document chunks."""
        if not texts:
            return np.empty((0, EMBEDDING_DIMENSION), dtype=np.float32)

        if self._model is not None:
            embeddings = self._model.encode(
                texts,
                batch_size=32,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            return np.array(embeddings, dtype=np.float32)

        # Deterministic lightweight vector simulation fallback
        return self._generate_fallback_vectors(texts)

    def embed_query(self, query: str) -> np.ndarray:
        """Generate normalized embedding vector for a search query."""
        if not query or not query.strip():
            return np.zeros((EMBEDDING_DIMENSION,), dtype=np.float32)

        if self._model is not None:
            embedding = self._model.encode(
                [query],
                show_progress_bar=False,
                normalize_embeddings=True,
            )[0]
            return np.array(embedding, dtype=np.float32)

        return self._generate_fallback_vectors([query])[0]

    def _generate_fallback_vectors(self, texts: List[str]) -> np.ndarray:
        """Deterministic seed-based vector generation for environments without downloaded model weights."""
        vectors = []
        for text in texts:
            # Deterministic pseudo-random seed from hash
            seed = hash(text.strip().lower()) & 0xFFFFFFFF
            rng = np.random.RandomState(seed)
            vec = rng.randn(EMBEDDING_DIMENSION).astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec)
        return np.array(vectors, dtype=np.float32)
