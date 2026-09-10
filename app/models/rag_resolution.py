from datetime import datetime, timezone
from app.extensions import db


class RAGStatus:
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NO_RELEVANT_CONTEXT = "NO_RELEVANT_CONTEXT"
    UNAVAILABLE = "UNAVAILABLE"

    ALL = [COMPLETED, FAILED, NO_RELEVANT_CONTEXT, UNAVAILABLE]


class RAGResolution(db.Model):
    """Grounded AI resolution generated from retrieved knowledge base documents."""
    __tablename__ = "rag_resolutions"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), unique=True, nullable=False, index=True)
    
    answer = db.Column(db.Text, nullable=True)
    confidence = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(30), default=RAGStatus.COMPLETED, nullable=False, index=True)
    
    model_name = db.Column(db.String(80), nullable=True)
    provider = db.Column(db.String(40), nullable=True)
    retrieval_count = db.Column(db.Integer, default=0, nullable=False)
    needs_escalation = db.Column(db.Boolean, default=False, nullable=False)
    reason = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    ticket = db.relationship("Ticket", back_populates="rag_resolution")
    sources = db.relationship("RAGSource", back_populates="resolution", cascade="all, delete-orphan", order_by="RAGSource.similarity_score.desc()")

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "answer": self.answer,
            "confidence": round(self.confidence, 2) if self.confidence is not None else None,
            "confidence_percent": int(round(self.confidence * 100)) if self.confidence is not None else None,
            "status": self.status,
            "model_name": self.model_name,
            "provider": self.provider,
            "retrieval_count": self.retrieval_count,
            "needs_escalation": self.needs_escalation,
            "reason": self.reason,
            "sources": [src.to_dict() for src in self.sources],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<RAGResolution Ticket {self.ticket_id}: {self.status}>"


class RAGSource(db.Model):
    """Citation record pointing to the exact document chunk used for RAG grounding."""
    __tablename__ = "rag_sources"

    id = db.Column(db.Integer, primary_key=True)
    resolution_id = db.Column(db.Integer, db.ForeignKey("rag_resolutions.id"), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey("knowledge_documents.id"), nullable=True)
    chunk_id = db.Column(db.Integer, db.ForeignKey("knowledge_chunks.id"), nullable=True)
    
    source_title = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    page_number = db.Column(db.Integer, nullable=True)
    similarity_score = db.Column(db.Float, nullable=False)
    excerpt = db.Column(db.Text, nullable=False)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    resolution = db.relationship("RAGResolution", back_populates="sources")
    document = db.relationship("KnowledgeDocument")
    chunk = db.relationship("KnowledgeChunk")

    def to_dict(self):
        return {
            "id": self.id,
            "resolution_id": self.resolution_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "source_title": self.source_title,
            "filename": self.filename,
            "page_number": self.page_number,
            "similarity_score": round(self.similarity_score, 2),
            "similarity_percent": int(round(self.similarity_score * 100)),
            "excerpt": self.excerpt,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<RAGSource {self.id}: {self.source_title} (sim={self.similarity_score:.2f})>"
