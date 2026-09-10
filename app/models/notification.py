from datetime import datetime, timezone
from app.extensions import db


class NotificationType:
    CRITICAL_TICKET = "CRITICAL_TICKET"
    TICKET_ESCALATED = "TICKET_ESCALATED"
    SUPPORT_REPLY = "SUPPORT_REPLY"
    CUSTOMER_REPLY = "CUSTOMER_REPLY"
    TICKET_RESOLVED = "TICKET_RESOLVED"
    TICKET_REOPENED = "TICKET_REOPENED"
    SYSTEM_ALERT = "SYSTEM_ALERT"

    ALL = [
        CRITICAL_TICKET, TICKET_ESCALATED, SUPPORT_REPLY,
        CUSTOMER_REPLY, TICKET_RESOLVED, TICKET_REOPENED, SYSTEM_ALERT
    ]


class Notification(db.Model):
    """In-app notification entity for customers and support staff."""
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=True, index=True)
    
    type = db.Column(db.String(50), default=NotificationType.SYSTEM_ALERT, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Relationships
    user = db.relationship("User", backref=db.backref("notifications", lazy="dynamic", cascade="all, delete-orphan"))
    ticket = db.relationship("Ticket")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "ticket_id": self.ticket_id,
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "link": self.link,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Notification {self.id} for User {self.user_id} (read={self.is_read})>"
