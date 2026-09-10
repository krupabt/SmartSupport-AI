from datetime import datetime, timezone
from app.extensions import db


class InternalNote(db.Model):
    """Support & Admin internal notes for a ticket (never shown to customers)."""
    __tablename__ = "internal_notes"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    author_name = db.Column(db.String(120), nullable=False)
    note = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    ticket = db.relationship("Ticket", back_populates="internal_notes")
    author = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<InternalNote {self.id} on Ticket {self.ticket_id} by {self.author_name}>"
