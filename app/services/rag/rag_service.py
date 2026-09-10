import os
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime, timezone

from app.extensions import db
from app.models.ticket import Ticket
from app.models.knowledge_doc import KnowledgeDocument, KnowledgeChunk, DocumentStatus
from app.models.rag_resolution import RAGResolution, RAGSource, RAGStatus
from app.services.rag.document_loader import DocumentLoader
from app.services.rag.document_processor import DocumentProcessor
from app.services.rag.chunker import TextChunker
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vector_store import VectorStore
from app.services.rag.retriever import RAGRetriever
from app.services.rag.resolution_generator import ResolutionGenerator
from app.services.rag.schemas import RAGResolutionResult

logger = logging.getLogger(__name__)


class RAGService:
    """Master service coordinating knowledge document ingestion, vector indexing, and grounded RAG resolution."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedding_service: Optional[EmbeddingService] = None,
        retriever: Optional[RAGRetriever] = None,
        resolution_generator: Optional[ResolutionGenerator] = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.embedding_service = embedding_service or EmbeddingService()
        self.retriever = retriever or RAGRetriever(
            vector_store=self.vector_store,
            embedding_service=self.embedding_service,
        )
        self.resolution_generator = resolution_generator or ResolutionGenerator()
        self.chunker = TextChunker()

    # -----------------------------------------------------------------------
    # Document Ingestion & Indexing
    # -----------------------------------------------------------------------

    def ingest_document(
        self,
        file_path: str,
        title: str,
        category: str = "General",
        description: str = "",
        document_id: Optional[int] = None,
    ) -> KnowledgeDocument:
        """Load, process, chunk, embed, and index a knowledge document."""
        path = Path(file_path)
        filename = path.name
        doc_type = path.suffix.lower().replace(".", "")

        logger.info(f"Ingesting document '{filename}' (title='{title}', category='{category}')")

        # 1. Load document pages
        pages = DocumentLoader.load(str(path))

        # 2. Combine and compute content hash
        full_text = "\n\n".join([p[0] for p in pages])
        content_hash = DocumentProcessor.compute_hash(full_text)

        # 3. Create or update KnowledgeDocument model in SQLite
        if document_id:
            doc = db.session.get(KnowledgeDocument, document_id)
            if not doc:
                raise ValueError(f"Document with ID {document_id} not found.")
            doc.title = title
            doc.category = category
            doc.description = description
            doc.file_path = str(path)
            doc.content_hash = content_hash
            doc.status = DocumentStatus.PROCESSING
            # Clear existing chunks from DB and vector store
            KnowledgeChunk.query.filter_by(document_id=doc.id).delete()
            self.vector_store.delete_document(doc.id)
        else:
            doc = KnowledgeDocument(
                filename=filename,
                title=title,
                document_type=doc_type,
                description=description,
                category=category,
                file_path=str(path),
                content_hash=content_hash,
                status=DocumentStatus.PROCESSING,
                chunk_count=0,
            )
            db.session.add(doc)

        db.session.flush()

        # 4. Chunk document pages
        chunks_data = self.chunker.chunk_document_pages(pages)
        if not chunks_data:
            doc.status = DocumentStatus.FAILED
            db.session.commit()
            raise ValueError("Document yielded 0 chunks after text splitting.")

        # 5. Save chunks to SQLite
        chunk_models = []
        chunk_texts = []
        for idx, (chunk_text, page_num) in enumerate(chunks_data):
            chunk_obj = KnowledgeChunk(
                document_id=doc.id,
                chunk_index=idx + 1,
                content=chunk_text,
                page_number=page_num,
            )
            db.session.add(chunk_obj)
            chunk_models.append(chunk_obj)
            chunk_texts.append(chunk_text)

        db.session.flush()

        # 6. Generate embeddings using local SentenceTransformer
        embeddings = self.embedding_service.embed_documents(chunk_texts)

        # 7. Add vectors and metadata to VectorStore
        docstore_entries = [
            {
                "chunk_id": chunk_models[i].id,
                "document_id": doc.id,
                "chunk_index": chunk_models[i].chunk_index,
                "content": chunk_models[i].content,
                "document_title": doc.title,
                "filename": doc.filename,
                "category": doc.category,
                "page_number": chunk_models[i].page_number,
            }
            for i in range(len(chunk_models))
        ]

        self.vector_store.add_chunks(docstore_entries, embeddings)

        # 8. Mark document ACTIVE
        doc.status = DocumentStatus.ACTIVE
        doc.chunk_count = len(chunk_models)
        doc.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(f"Document '{title}' successfully indexed with {doc.chunk_count} chunks.")
        return doc

    def delete_document(self, document_id: int):
        """Delete document from database and vector index."""
        doc = db.session.get(KnowledgeDocument, document_id)
        if not doc:
            return

        self.vector_store.delete_document(doc.id)
        db.session.delete(doc)
        db.session.commit()
        logger.info(f"Document ID {document_id} and all its chunks deleted.")

    def rebuild_index(self):
        """Rebuild entire vector index from active documents in SQLite."""
        logger.info("Rebuilding vector store index from database...")
        self.vector_store.clear()

        active_docs = KnowledgeDocument.query.filter_by(status=DocumentStatus.ACTIVE).all()
        all_chunks_meta = []
        all_texts = []

        for doc in active_docs:
            for chunk in doc.chunks:
                all_chunks_meta.append({
                    "chunk_id": chunk.id,
                    "document_id": doc.id,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "document_title": doc.title,
                    "filename": doc.filename,
                    "category": doc.category,
                    "page_number": chunk.page_number,
                })
                all_texts.append(chunk.content)

        if all_texts:
            embeddings = self.embedding_service.embed_documents(all_texts)
            self.vector_store.add_chunks(all_chunks_meta, embeddings)

        logger.info(f"Vector store rebuilt with {len(all_chunks_meta)} chunks across {len(active_docs)} documents.")

    # -----------------------------------------------------------------------
    # Grounded Ticket Resolution
    # -----------------------------------------------------------------------

    def resolve_ticket(self, ticket: Ticket, force_regenerate: bool = False) -> RAGResolution:
        """
        Execute RAG retrieval and grounded generation for a customer complaint.
        Saves / updates RAGResolution and RAGSource entities in SQLite.
        """
        resolution = RAGResolution.query.filter_by(ticket_id=ticket.id).first()
        if resolution and not force_regenerate:
            return resolution

        if not resolution:
            resolution = RAGResolution(ticket_id=ticket.id)
            db.session.add(resolution)
            db.session.flush()
        else:
            # Clear old source citations
            RAGSource.query.filter_by(resolution_id=resolution.id).delete()

        # 1. Build query from ticket
        query = self.retriever.build_query(
            subject=ticket.subject,
            description=ticket.description,
            category=ticket.category,
            product_service=ticket.product_service,
        )

        # 2. Retrieve relevant chunks
        chunks = self.retriever.retrieve(query)

        # 3. Generate grounded resolution via LLM
        res_result = self.resolution_generator.generate_resolution(
            subject=ticket.subject,
            description=ticket.description,
            product_service=ticket.product_service,
            reference_id=ticket.reference_id,
            chunks=chunks,
        )

        # 4. Save RAGResolution
        resolution.answer = res_result.answer
        resolution.confidence = res_result.confidence
        resolution.needs_escalation = res_result.needs_escalation
        resolution.reason = res_result.reason
        resolution.status = res_result.status
        resolution.model_name = res_result.model_name
        resolution.provider = res_result.provider
        resolution.retrieval_count = res_result.retrieval_count
        resolution.updated_at = datetime.now(timezone.utc)

        # 5. Save RAGSource citations
        for src in res_result.sources:
            rag_src = RAGSource(
                resolution_id=resolution.id,
                document_id=src.document_id,
                chunk_id=src.chunk_id,
                source_title=src.source_title,
                filename=src.filename,
                page_number=src.page_number,
                similarity_score=src.similarity_score,
                excerpt=src.excerpt,
            )
            db.session.add(rag_src)

        db.session.commit()
        logger.info(f"RAG resolution stored for Ticket {ticket.ticket_number} (status={resolution.status}).")
        return resolution
