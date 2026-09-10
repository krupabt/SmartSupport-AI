from datetime import datetime, timezone
from app.extensions import db


class DocumentStatus:
    ACTIVE = "ACTIVE"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"

    ALL = [ACTIVE, PROCESSING, FAILED, ARCHIVED]


class KnowledgeDocument(db.Model):
    """Knowledge Base Document entity."""
    __tablename__ = "knowledge_documents"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    document_type = db.Column(db.String(20), nullable=False)  # txt, pdf, md, docx
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(80), default="General", nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    content_hash = db.Column(db.String(64), nullable=True, index=True)
    status = db.Column(db.String(20), default=DocumentStatus.ACTIVE, nullable=False, index=True)
    chunk_count = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    chunks = db.relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan", order_by="KnowledgeChunk.chunk_index.asc()")

    def to_dict(self, include_chunks=False):
        data = {
            "id": self.id,
            "filename": self.filename,
            "title": self.title,
            "document_type": self.document_type,
            "description": self.description,
            "category": self.category,
            "content_hash": self.content_hash,
            "status": self.status,
            "chunk_count": self.chunk_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_chunks:
            data["chunks"] = [chunk.to_dict() for chunk in self.chunks]
        return data

    def __repr__(self):
        return f"<KnowledgeDocument {self.id}: {self.title} ({self.status})>"


class KnowledgeChunk(db.Model):
    """Chunked segment of a knowledge document stored for retrieval."""
    __tablename__ = "knowledge_chunks"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    chunk_index = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    page_number = db.Column(db.Integer, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship back to document
    document = db.relationship("KnowledgeDocument", back_populates="chunks")

    def to_dict(self):
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "page_number": self.page_number,
            "document_title": self.document.title if self.document else None,
            "document_filename": self.document.filename if self.document else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<KnowledgeChunk {self.id} on Doc {self.document_id} [#{self.chunk_index}]>"
