import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import numpy as np

from app.services.rag.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Vector Store managing local vector index and document chunk metadata.
    Uses FAISS IndexFlatIP (Inner Product on normalized vectors = Cosine Similarity)
    with an optimized NumPy vector search fallback.
    """

    def __init__(self, storage_dir: Optional[str] = None, storage_path: Optional[str] = None, dimension: int = 384):
        self.dimension = dimension
        target_dir = storage_dir or storage_path
        if not target_dir:
            try:
                from flask import current_app, has_app_context
                if has_app_context() and current_app.config.get("VECTOR_STORE_PATH"):
                    target_dir = current_app.config["VECTOR_STORE_PATH"]
            except Exception:
                pass

        if target_dir:
            self.storage_dir = Path(target_dir)
        else:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            self.storage_dir = base_dir / "instance" / "vector_store"

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_dir / "faiss_index.bin"
        self.docstore_file = self.storage_dir / "docstore.json"

        self._vectors: Optional[np.ndarray] = None  # (N, D) float32
        self._docstore: List[Dict] = []  # parallel list of chunk metadata
        self._faiss_index = None

        self.load()

    def count(self) -> int:
        return len(self._docstore)

    def get_total_vectors(self) -> int:
        return len(self._docstore)

    def add_chunks(self, chunks: List[Dict], embeddings: np.ndarray):
        """Add new document chunks and corresponding normalized embeddings."""
        if not chunks or len(embeddings) == 0:
            return

        if len(chunks) != len(embeddings):
            raise ValueError(f"Mismatch: {len(chunks)} chunks metadata vs {len(embeddings)} embeddings.")

        embeddings = np.array(embeddings, dtype=np.float32)

        if self._vectors is None or len(self._vectors) == 0:
            self._vectors = embeddings
            self._docstore = list(chunks)
        else:
            self._vectors = np.vstack([self._vectors, embeddings])
            self._docstore.extend(chunks)

        self._update_faiss_index()
        self.save()
        logger.info(f"Added {len(chunks)} chunks to vector store. Total chunks: {self.get_total_vectors()}")

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        threshold: float = 0.0,
    ) -> List[RetrievedChunk]:
        """
        Execute semantic similarity search against indexed vector chunks.
        Returns top_k chunks with cosine similarity >= threshold.
        """
        if self._vectors is None or len(self._vectors) == 0 or len(self._docstore) == 0:
            logger.info("Vector store is empty. 0 chunks retrieved.")
            return []

        query_vector = np.array(query_vector, dtype=np.float32).reshape(1, -1)

        # 1. FAISS Search if available
        if self._faiss_index is not None:
            try:
                import faiss
                k_search = min(top_k * 2, len(self._docstore))
                distances, indices = self._faiss_index.search(query_vector, k_search)
                
                results = []
                for score, idx in zip(distances[0], indices[0]):
                    if idx < 0 or idx >= len(self._docstore):
                        continue
                    if score < threshold:
                        continue
                    
                    meta = self._docstore[idx]
                    results.append(self._build_retrieved_chunk(meta, float(score)))
                    if len(results) >= top_k:
                        break
                return results
            except Exception as e:
                logger.warning(f"FAISS search failed ({str(e)}). Falling back to NumPy cosine search.")

        # 2. Optimized NumPy Dot Product / Cosine Search
        similarities = np.dot(self._vectors, query_vector.T).flatten()
        top_indices = np.argsort(similarities)[::-1]

        results = []
        for idx in top_indices:
            if idx < 0 or idx >= len(self._docstore):
                continue
            score = float(similarities[idx])
            if score < threshold:
                break
            meta = self._docstore[idx]
            results.append(self._build_retrieved_chunk(meta, score))
            if len(results) >= top_k:
                break

        return results

    def _build_retrieved_chunk(self, meta: Dict, score: float) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=meta.get("chunk_id", 0),
            document_id=meta.get("document_id", 0),
            chunk_index=meta.get("chunk_index", 0),
            content=meta.get("content", ""),
            document_title=meta.get("document_title", "Unknown"),
            filename=meta.get("filename", "Unknown"),
            category=meta.get("category", "General"),
            similarity_score=max(0.0, min(1.0, score)),
            page_number=meta.get("page_number"),
        )

    def delete_document(self, document_id: int):
        """Remove all chunks associated with a specific document."""
        if not self._docstore:
            return

        keep_indices = [
            i for i, doc in enumerate(self._docstore)
            if doc.get("document_id") != document_id
        ]

        if len(keep_indices) == len(self._docstore):
            return  # Nothing to delete

        if not keep_indices:
            self._vectors = None
            self._docstore = []
        else:
            self._vectors = self._vectors[keep_indices]
            self._docstore = [self._docstore[i] for i in keep_indices]

        self._update_faiss_index()
        self.save()
        logger.info(f"Deleted document {document_id} from vector store. Remaining chunks: {self.get_total_vectors()}")

    def clear(self):
        """Clear all vectors and docstore."""
        self._vectors = None
        self._docstore = []
        self._faiss_index = None
        if self.index_file.exists():
            self.index_file.unlink()
        if self.docstore_file.exists():
            self.docstore_file.unlink()

    def _update_faiss_index(self):
        """Rebuild or update in-memory FAISS index if library is available."""
        if self._vectors is None or len(self._vectors) == 0:
            self._faiss_index = None
            return

        try:
            import faiss
            index = faiss.IndexFlatIP(self.dimension)
            index.add(self._vectors)
            self._faiss_index = index
        except Exception:
            self._faiss_index = None

    def save(self):
        """Persist vector store and docstore to disk."""
        try:
            # 1. Save metadata docstore
            with open(self.docstore_file, "w", encoding="utf-8") as f:
                json.dump(self._docstore, f, indent=2)

            # 2. Save vectors (NumPy binary array)
            if self._vectors is not None and len(self._vectors) > 0:
                np.save(str(self.storage_dir / "vectors.npy"), self._vectors)

            # 3. Save FAISS binary index if available
            if self._faiss_index is not None:
                try:
                    import faiss
                    faiss.write_index(self._faiss_index, str(self.index_file))
                except Exception as fe:
                    logger.debug(f"FAISS index file write skipped: {str(fe)}")
        except Exception as e:
            logger.error(f"Failed to persist vector store: {str(e)}", exc_info=True)

    def load(self):
        """Load vector store from persistent disk storage."""
        if not self.docstore_file.exists():
            return

        try:
            with open(self.docstore_file, "r", encoding="utf-8") as f:
                self._docstore = json.load(f)

            vec_path = self.storage_dir / "vectors.npy"
            if vec_path.exists():
                self._vectors = np.load(str(vec_path))

            self._update_faiss_index()
            logger.info(f"Loaded vector store with {self.get_total_vectors()} indexed chunks.")
        except Exception as e:
            logger.error(f"Failed to load vector store from disk: {str(e)}", exc_info=True)
            self._docstore = []
            self._vectors = None
