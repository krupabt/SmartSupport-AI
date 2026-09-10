from datetime import datetime, timezone
from app.extensions import db


class AuditAction:
    STATUS_CHANGED = "STATUS_CHANGED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    CATEGORY_CHANGED = "CATEGORY_CHANGED"
    TEAM_CHANGED = "TEAM_CHANGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    CUSTOMER_REPLIED = "CUSTOMER_REPLIED"
    SUPPORT_REPLIED = "SUPPORT_REPLIED"
    INTERNAL_NOTE_ADDED = "INTERNAL_NOTE_ADDED"
    AI_REANALYZED = "AI_REANALYZED"
    RAG_REGENERATED = "RAG_REGENERATED"
    CONTACT_SUPPORT_REQUESTED = "CONTACT_SUPPORT_REQUESTED"

    ALL = [
        STATUS_CHANGED, PRIORITY_CHANGED, CATEGORY_CHANGED, TEAM_CHANGED,
        ESCALATED, RESOLVED, CLOSED, REOPENED, CUSTOMER_REPLIED,
        SUPPORT_REPLIED, INTERNAL_NOTE_ADDED, AI_REANALYZED,
        RAG_REGENERATED, CONTACT_SUPPORT_REQUESTED,
    ]


class TicketAuditLog(db.Model):
    """Immutable audit trail of all lifecycle events and modifications on a ticket."""
    __tablename__ = "ticket_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    actor_name = db.Column(db.String(120), nullable=False, default="System")
    
    action = db.Column(db.String(50), nullable=False, index=True)
    old_value = db.Column(db.String(255), nullable=True)
    new_value = db.Column(db.String(255), nullable=True)
    details = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships
    ticket = db.relationship("Ticket", back_populates="audit_logs")
    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "actor_name": self.actor_name,
            "action": self.action,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<TicketAuditLog {self.id} on Ticket {self.ticket_id}: {self.action}>"
