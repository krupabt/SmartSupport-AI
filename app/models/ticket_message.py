from datetime import datetime, timezone
from app.extensions import db


class SenderType:
    CUSTOMER = "CUSTOMER"
    SUPPORT = "SUPPORT"
    SYSTEM = "SYSTEM"

    ALL = [CUSTOMER, SUPPORT, SYSTEM]


class TicketMessage(db.Model):
    """Conversation messages belonging to a ticket thread."""
    __tablename__ = "ticket_messages"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    sender_name = db.Column(db.String(120), nullable=False)
    sender_type = db.Column(db.String(20), default=SenderType.CUSTOMER, nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship
    ticket = db.relationship("Ticket", back_populates="messages")
    sender = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "sender_type": self.sender_type,
            "message": self.message,
            "is_internal": self.is_internal,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<TicketMessage {self.id} on Ticket {self.ticket_id} by {self.sender_type}>"
