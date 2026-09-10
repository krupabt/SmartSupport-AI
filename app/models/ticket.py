from datetime import datetime, timezone
from app.extensions import db


class TicketStatus:
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_FOR_CUSTOMER = "WAITING_FOR_CUSTOMER"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

    ALL = [OPEN, IN_PROGRESS, WAITING_FOR_CUSTOMER, ESCALATED, RESOLVED, CLOSED]


class TicketPriority:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    ALL = [LOW, MEDIUM, HIGH, CRITICAL]


class TicketCategory:
    BILLING = "Billing"
    PAYMENT = "Payment"
    REFUND = "Refund"
    DELIVERY = "Delivery"
    PRODUCT_ISSUE = "Product Issue"
    TECHNICAL_ISSUE = "Technical Issue"
    ACCOUNT = "Account"
    SUBSCRIPTION = "Subscription"
    SECURITY = "Security"
    GENERAL = "General"

    ALL = [
        BILLING, PAYMENT, REFUND, DELIVERY, PRODUCT_ISSUE,
        TECHNICAL_ISSUE, ACCOUNT, SUBSCRIPTION, SECURITY, GENERAL
    ]


class SupportTeam:
    BILLING_SUPPORT = "Billing Support"
    TECHNICAL_SUPPORT = "Technical Support"
    DELIVERY_SUPPORT = "Delivery Support"
    ACCOUNT_SUPPORT = "Account Support"
    SENIOR_SUPPORT = "Senior Support"
    UNASSIGNED = "Unassigned"

    ALL = [
        BILLING_SUPPORT, TECHNICAL_SUPPORT, DELIVERY_SUPPORT,
        ACCOUNT_SUPPORT, SENIOR_SUPPORT, UNASSIGNED
    ]


class Ticket(db.Model):
    """Support Ticket entity representing customer complaints and inquiries."""
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(32), unique=True, index=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    subject = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    product_service = db.Column(db.String(120), nullable=False)
    reference_id = db.Column(db.String(80), nullable=True)
    
    category = db.Column(db.String(50), default=TicketCategory.GENERAL, nullable=False)
    priority = db.Column(db.String(20), default=TicketPriority.MEDIUM, nullable=False)
    sentiment = db.Column(db.String(20), default="Neutral", nullable=False)
    status = db.Column(db.String(30), default=TicketStatus.OPEN, nullable=False, index=True)
    assigned_team = db.Column(db.String(60), default=SupportTeam.UNASSIGNED, nullable=False)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    user = db.relationship("User", back_populates="tickets")
    messages = db.relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan", order_by="TicketMessage.created_at.asc()")
    internal_notes = db.relationship("InternalNote", back_populates="ticket", cascade="all, delete-orphan", order_by="InternalNote.created_at.desc()")
    escalations = db.relationship("Escalation", back_populates="ticket", cascade="all, delete-orphan", order_by="Escalation.escalated_at.desc()")
    audit_logs = db.relationship("TicketAuditLog", back_populates="ticket", cascade="all, delete-orphan", order_by="TicketAuditLog.created_at.desc()")
    ai_analysis = db.relationship("AIAnalysis", back_populates="ticket", uselist=False, cascade="all, delete-orphan")
    rag_resolution = db.relationship("RAGResolution", back_populates="ticket", uselist=False, cascade="all, delete-orphan")

    def to_dict(self, include_internal=False):
        """Serialize ticket data for API / client use."""
        active_escalation = next((esc for esc in self.escalations if esc.status == "ACTIVE"), None)
        data = {
            "id": self.id,
            "ticket_number": self.ticket_number,
            "user_id": self.user_id,
            "customer_name": self.user.name if self.user else "Unknown",
            "customer_email": self.user.email if self.user else "Unknown",
            "subject": self.subject,
            "description": self.description,
            "product_service": self.product_service,
            "reference_id": self.reference_id,
            "category": self.category,
            "priority": self.priority,
            "sentiment": self.sentiment,
            "status": self.status,
            "is_escalated": active_escalation is not None or self.status == "ESCALATED",
            "assigned_team": self.assigned_team,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "messages": [
                msg.to_dict() for msg in self.messages
                if not msg.is_internal or include_internal
            ],
            "ai_analysis": self.ai_analysis.to_dict() if self.ai_analysis else None,
            "rag_resolution": self.rag_resolution.to_dict() if self.rag_resolution else None,
        }
        if include_internal:
            data["internal_notes"] = [note.to_dict() for note in self.internal_notes]
            data["escalations"] = [esc.to_dict() for esc in self.escalations]
            data["audit_logs"] = [log.to_dict() for log in self.audit_logs]
        return data

    def __repr__(self):
        return f"<Ticket {self.ticket_number}: {self.status}>"
