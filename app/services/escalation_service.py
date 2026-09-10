import os
import logging
from typing import Optional, Tuple
from datetime import datetime, timezone
from flask import current_app, has_app_context

from app.extensions import db
from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory, SupportTeam
from app.models.escalation import Escalation, EscalationStatus, EscalationType, EscalationReason
from app.models.audit_log import TicketAuditLog, AuditAction
from app.models.rag_resolution import RAGResolution, RAGStatus
from app.services.notification_service import notify_support_staff

logger = logging.getLogger(__name__)

# Category to Support Department deterministic mapping
CATEGORY_TEAM_MAP = {
    TicketCategory.BILLING: SupportTeam.BILLING_SUPPORT,
    TicketCategory.PAYMENT: SupportTeam.BILLING_SUPPORT,
    TicketCategory.REFUND: SupportTeam.BILLING_SUPPORT,
    TicketCategory.SUBSCRIPTION: SupportTeam.BILLING_SUPPORT,
    TicketCategory.DELIVERY: SupportTeam.DELIVERY_SUPPORT,
    TicketCategory.PRODUCT_ISSUE: SupportTeam.TECHNICAL_SUPPORT,
    TicketCategory.TECHNICAL_ISSUE: SupportTeam.TECHNICAL_SUPPORT,
    TicketCategory.ACCOUNT: SupportTeam.ACCOUNT_SUPPORT,
    TicketCategory.SECURITY: SupportTeam.TECHNICAL_SUPPORT,
    TicketCategory.GENERAL: SupportTeam.SENIOR_SUPPORT,
}


class EscalationService:
    """Intelligent, deterministic escalation engine evaluating risk, sentiment, confidence, and context coverage."""

    @staticmethod
    def suggest_team_for_category(category: str) -> str:
        """Suggest appropriate support department based on complaint category."""
        return CATEGORY_TEAM_MAP.get(category, SupportTeam.SENIOR_SUPPORT)

    @staticmethod
    def get_thresholds() -> Tuple[float, float, bool, bool]:
        """Fetch active confidence thresholds and auto-escalation flags from config/environment."""
        ai_thresh = 0.70
        rag_thresh = 0.60
        auto_crit = True
        auto_sec = True

        if has_app_context():
            ai_thresh = current_app.config.get("AI_CONFIDENCE_THRESHOLD", ai_thresh)
            rag_thresh = current_app.config.get("RAG_CONFIDENCE_THRESHOLD", rag_thresh)
            auto_crit = current_app.config.get("AUTO_ESCALATE_CRITICAL", auto_crit)
            auto_sec = current_app.config.get("AUTO_ESCALATE_SECURITY", auto_sec)
        else:
            ai_thresh = float(os.getenv("AI_CONFIDENCE_THRESHOLD", str(ai_thresh)))
            rag_thresh = float(os.getenv("RAG_CONFIDENCE_THRESHOLD", str(rag_thresh)))
            auto_crit = os.getenv("AUTO_ESCALATE_CRITICAL", "true").lower() in ("true", "1", "yes")
            auto_sec = os.getenv("AUTO_ESCALATE_SECURITY", "true").lower() in ("true", "1", "yes")

        return ai_thresh, rag_thresh, auto_crit, auto_sec

    @classmethod
    def evaluate(cls, ticket: Ticket) -> Optional[Escalation]:
        """
        Evaluate a ticket against deterministic escalation rules.
        Idempotent: will not create duplicate active escalations if already escalated.
        """
        # 1. Idempotency Guard: Check if ticket already has an active escalation
        active_esc = (
            db.session.query(Escalation)
            .filter_by(ticket_id=ticket.id, status=EscalationStatus.ACTIVE)
            .first()
        )
        if active_esc:
            logger.debug(f"Ticket {ticket.ticket_number} already has active escalation {active_esc.id}. Skipping duplicate.")
            return active_esc

        ai_thresh, rag_thresh, auto_crit, auto_sec = cls.get_thresholds()
        
        trigger_reason = None
        trigger_code = None

        # Rule A: Critical Priority
        if auto_crit and ticket.priority == TicketPriority.CRITICAL:
            trigger_code = EscalationReason.CRITICAL_PRIORITY
            trigger_reason = "Critical priority complaint requires immediate human staff review."

        # Rule B: Security Category
        elif auto_sec and ticket.category == TicketCategory.SECURITY:
            trigger_code = EscalationReason.SECURITY_RISK
            trigger_reason = "Security / account compromise risk requires manual support investigation."

        # Rule C: Very Negative Sentiment + Elevated Priority
        elif (
            getattr(ticket, "sentiment", "").lower() in ("very negative", "very_negative")
            and ticket.priority in (TicketPriority.HIGH, TicketPriority.CRITICAL)
        ):
            trigger_code = EscalationReason.HIGH_SEVERITY_SENTIMENT
            trigger_reason = "Severe negative customer sentiment detected with high/critical urgency."

        # Rule D: RAG Knowledge Retrieval & Grounding Checks
        rag_res = ticket.rag_resolution
        if not trigger_code and rag_res and rag_res.status == RAGStatus.COMPLETED:
            if rag_res.needs_escalation:
                trigger_code = EscalationReason.AI_REQUESTED_ESCALATION
                trigger_reason = rag_res.reason or "AI knowledge retrieval flagged this request for human review."
            elif rag_res.confidence is not None and rag_res.confidence < rag_thresh:
                trigger_code = EscalationReason.LOW_RAG_CONFIDENCE
                trigger_reason = f"Grounded resolution confidence ({int(rag_res.confidence * 100)}%) is below operational threshold ({int(rag_thresh * 100)}%)."

        # Rule E: AI Complaint Analysis Confidence Check
        ai_analysis = ticket.ai_analysis
        if not trigger_code and ai_analysis and ai_analysis.status == "COMPLETED":
            if ai_analysis.confidence is not None and ai_analysis.confidence < ai_thresh:
                trigger_code = EscalationReason.LOW_AI_CONFIDENCE
                trigger_reason = f"AI classification confidence ({int(ai_analysis.confidence * 100)}%) is below operational threshold ({int(ai_thresh * 100)}%)."

        # If an escalation rule matched, execute state transition
        if trigger_code:
            logger.info(f"Escalating Ticket {ticket.ticket_number}: {trigger_code} -> {trigger_reason}")
            
            # Suggest support team if unassigned
            suggested_team = cls.suggest_team_for_category(ticket.category)
            if ticket.assigned_team == SupportTeam.UNASSIGNED:
                ticket.assigned_team = suggested_team

            old_status = ticket.status
            ticket.status = TicketStatus.ESCALATED
            ticket.updated_at = datetime.now(timezone.utc)

            escalation = Escalation(
                ticket_id=ticket.id,
                reason=f"[{trigger_code}] {trigger_reason}",
                escalated_by="AI Escalation Engine",
                escalation_type=EscalationType.AUTOMATIC,
                target_team=ticket.assigned_team,
                status=EscalationStatus.ACTIVE,
            )
            db.session.add(escalation)

            # Audit Log
            audit_log = TicketAuditLog(
                ticket_id=ticket.id,
                user_id=None,
                actor_name="AI Escalation Engine",
                action=AuditAction.ESCALATED,
                old_value=old_status,
                new_value=TicketStatus.ESCALATED,
                details=f"Reason: [{trigger_code}] {trigger_reason} | Target Team: {ticket.assigned_team}",
            )
            db.session.add(audit_log)

            # In-App Notification to Support Team
            notify_support_staff(
                title=f"Ticket {ticket.ticket_number} Escalated",
                message=f"Ticket '{ticket.subject[:50]}' escalated to {ticket.assigned_team}. Reason: {trigger_reason}",
                notification_type="TICKET_ESCALATED",
                ticket_id=ticket.id,
                link=f"/admin/tickets/{ticket.ticket_number}",
            )

            db.session.commit()
            return escalation

        return None
