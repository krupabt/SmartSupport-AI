from datetime import datetime, timezone
from app.extensions import db


class AIAnalysisStatus:
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"

    ALL = [PENDING, COMPLETED, FAILED, UNAVAILABLE]


class AIAnalysis(db.Model):
    """AI analysis metadata and classification results for a ticket."""
    __tablename__ = "ai_analysis"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), unique=True, nullable=False, index=True)
    
    category = db.Column(db.String(50), nullable=True)
    sentiment = db.Column(db.String(20), nullable=True)
    priority = db.Column(db.String(20), nullable=True)
    confidence = db.Column(db.Float, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    
    model_name = db.Column(db.String(80), nullable=True)
    provider = db.Column(db.String(40), nullable=True)
    status = db.Column(db.String(20), default=AIAnalysisStatus.PENDING, nullable=False)
    raw_response = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship back to Ticket
    ticket = db.relationship("Ticket", back_populates="ai_analysis")

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "category": self.category,
            "sentiment": self.sentiment,
            "priority": self.priority,
            "confidence": round(self.confidence, 2) if self.confidence is not None else None,
            "confidence_percent": int(round(self.confidence * 100)) if self.confidence is not None else None,
            "reason": self.reason,
            "model_name": self.model_name,
            "provider": self.provider,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<AIAnalysis Ticket {self.ticket_id}: {self.category} ({self.status})>"
