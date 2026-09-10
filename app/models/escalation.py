from datetime import datetime, timezone
from app.extensions import db


class EscalationStatus:
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"

    ALL = [ACTIVE, RESOLVED]


class EscalationType:
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"

    ALL = [AUTOMATIC, MANUAL]


class EscalationReason:
    CRITICAL_PRIORITY = "CRITICAL_PRIORITY"
    SECURITY_RISK = "SECURITY_RISK"
    LOW_AI_CONFIDENCE = "LOW_AI_CONFIDENCE"
    LOW_RAG_CONFIDENCE = "LOW_RAG_CONFIDENCE"
    NO_RELEVANT_CONTEXT = "NO_RELEVANT_CONTEXT"
    AI_REQUESTED_ESCALATION = "AI_REQUESTED_ESCALATION"
    CUSTOMER_REQUESTED_SUPPORT = "CUSTOMER_REQUESTED_SUPPORT"
    HIGH_SEVERITY_SENTIMENT = "HIGH_SEVERITY_SENTIMENT"
    MANUAL_SUPPORT_ESCALATION = "MANUAL_SUPPORT_ESCALATION"

    ALL = [
        CRITICAL_PRIORITY, SECURITY_RISK, LOW_AI_CONFIDENCE,
        LOW_RAG_CONFIDENCE, NO_RELEVANT_CONTEXT, AI_REQUESTED_ESCALATION,
        CUSTOMER_REQUESTED_SUPPORT, HIGH_SEVERITY_SENTIMENT, MANUAL_SUPPORT_ESCALATION,
    ]


class Escalation(db.Model):
    """Escalation record for a ticket with automatic vs manual attribution."""
    __tablename__ = "escalations"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    reason = db.Column(db.Text, nullable=False)
    escalated_by = db.Column(db.String(120), nullable=False)
    escalation_type = db.Column(db.String(20), default=EscalationType.AUTOMATIC, nullable=False)
    target_team = db.Column(db.String(60), nullable=True)
    status = db.Column(db.String(20), default=EscalationStatus.ACTIVE, nullable=False, index=True)
    escalated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    resolved_at = db.Column(db.DateTime, nullable=True)

    # Relationship
    ticket = db.relationship("Ticket", back_populates="escalations")

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "reason": self.reason,
            "escalated_by": self.escalated_by,
            "escalation_type": self.escalation_type,
            "target_team": self.target_team,
            "status": self.status,
            "escalated_at": self.escalated_at.isoformat() if self.escalated_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }

    def __repr__(self):
        return f"<Escalation {self.id} on Ticket {self.ticket_id} ({self.escalation_type}): {self.status}>"
