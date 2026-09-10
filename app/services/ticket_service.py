import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple
from sqlalchemy import func, and_

from app.extensions import db
from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory, SupportTeam
from app.models.ticket_message import TicketMessage, SenderType
from app.models.internal_note import InternalNote
from app.models.escalation import Escalation, EscalationStatus, EscalationType, EscalationReason
from app.models.audit_log import TicketAuditLog, AuditAction
from app.models.notification import Notification, NotificationType
from app.models.ai_analysis import AIAnalysis, AIAnalysisStatus
from app.models.rag_resolution import RAGResolution, RAGStatus
from app.models.user import User
from app.services.notification_service import create_notification, notify_support_staff

logger = logging.getLogger(__name__)

# Allowed status transitions
VALID_STATUS_TRANSITIONS = {
    TicketStatus.OPEN: [TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED, TicketStatus.RESOLVED, TicketStatus.CLOSED],
    TicketStatus.IN_PROGRESS: [TicketStatus.WAITING_FOR_CUSTOMER, TicketStatus.ESCALATED, TicketStatus.RESOLVED, TicketStatus.CLOSED],
    TicketStatus.WAITING_FOR_CUSTOMER: [TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED, TicketStatus.RESOLVED, TicketStatus.CLOSED],
    TicketStatus.ESCALATED: [TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED],
    TicketStatus.RESOLVED: [TicketStatus.CLOSED, TicketStatus.IN_PROGRESS],
    TicketStatus.CLOSED: [TicketStatus.IN_PROGRESS],
}


def generate_unique_ticket_number() -> str:
    """Generate sequential unique ticket number in format TKT-YYYY-XXXXXX."""
    current_year = datetime.now(timezone.utc).year
    prefix = f"TKT-{current_year}-"

    highest_ticket = (
        db.session.query(Ticket.ticket_number)
        .filter(Ticket.ticket_number.like(f"{prefix}%"))
        .order_by(Ticket.id.desc())
        .first()
    )

    next_sequence = 1
    if highest_ticket and highest_ticket[0]:
        try:
            seq_part = highest_ticket[0].split("-")[-1]
            next_sequence = int(seq_part) + 1
        except (ValueError, IndexError):
            next_sequence = db.session.query(func.count(Ticket.id)).scalar() + 1

    candidate = f"{prefix}{next_sequence:06d}"
    attempts = 0
    while db.session.query(Ticket.id).filter_by(ticket_number=candidate).first() is not None and attempts < 100:
        next_sequence += 1
        candidate = f"{prefix}{next_sequence:06d}"
        attempts += 1

    return candidate


def create_ticket(
    user_id: int,
    subject: str,
    description: str,
    product_service: str,
    reference_id: str = None,
    category: str = TicketCategory.GENERAL,
    priority: str = TicketPriority.MEDIUM,
) -> Ticket:
    """Create a new complaint ticket with transaction safety, audit history, AI, RAG, and auto-escalation."""
    subject = subject.strip()
    description = description.strip()
    product_service = product_service.strip()
    reference_id = reference_id.strip() if reference_id else None

    if not subject:
        raise ValueError("Subject is required.")
    if len(subject) > 200:
        raise ValueError("Subject must not exceed 200 characters.")
    if not description:
        raise ValueError("Complaint description is required.")
    if not product_service:
        raise ValueError("Product or service name is required.")

    user = db.session.get(User, user_id)
    if not user:
        raise ValueError("Valid authenticated user is required to submit a complaint.")

    ticket_number = generate_unique_ticket_number()

    try:
        ticket = Ticket(
            ticket_number=ticket_number,
            user_id=user.id,
            subject=subject,
            description=description,
            product_service=product_service,
            reference_id=reference_id,
            category=category if category in TicketCategory.ALL else TicketCategory.GENERAL,
            priority=priority if priority in TicketPriority.ALL else TicketPriority.MEDIUM,
            sentiment="Neutral",
            status=TicketStatus.OPEN,
            assigned_team=SupportTeam.UNASSIGNED,
        )
        db.session.add(ticket)
        db.session.flush()

        # Initial conversation message containing customer's full complaint
        initial_msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=user.id,
            sender_name=user.name,
            sender_type=SenderType.CUSTOMER,
            message=description,
            is_internal=False,
        )
        db.session.add(initial_msg)

        # Initial system audit message
        sys_msg = TicketMessage(
            ticket_id=ticket.id,
            sender_id=None,
            sender_name="System",
            sender_type=SenderType.SYSTEM,
            message=f"Ticket {ticket.ticket_number} created with status '{ticket.status}' and priority '{ticket.priority}'.",
            is_internal=False,
        )
        db.session.add(sys_msg)

        # Initial Audit Log Record
        audit_log = TicketAuditLog(
            ticket_id=ticket.id,
            user_id=user.id,
            actor_name=user.name,
            action=AuditAction.STATUS_CHANGED,
            old_value=None,
            new_value=TicketStatus.OPEN,
            details=f"Ticket registered by {user.name} ({user.email}).",
        )
        db.session.add(audit_log)

        db.session.commit()
        logger.info(f"Ticket created: {ticket.ticket_number} by User {user.id}")

        # 1. Trigger AI Complaint Analysis (Fault-tolerant)
        try:
            from app.services.ai.complaint_analyzer import ComplaintAnalyzer
            analyzer = ComplaintAnalyzer()
            analyzer.analyze_and_store(ticket)
        except Exception as ai_err:
            logger.warning(f"Background AI analysis step failed safely: {str(ai_err)}")

        # 2. Trigger RAG Knowledge Retrieval & Grounded Resolution (Fault-tolerant)
        try:
            from app.services.rag.rag_service import RAGService
            rag_service = RAGService()
            rag_service.resolve_ticket(ticket)
        except Exception as rag_err:
            logger.warning(f"Background RAG resolution step failed safely: {str(rag_err)}", exc_info=True)

        # 3. Trigger Intelligent Escalation Engine (Phase 5)
        try:
            from app.services.escalation_service import EscalationService
            EscalationService.evaluate(ticket)
        except Exception as esc_err:
            logger.warning(f"Background escalation evaluation failed safely: {str(esc_err)}", exc_info=True)

        # Notify support if Critical
        if ticket.priority == TicketPriority.CRITICAL:
            notify_support_staff(
                title=f"CRITICAL Priority Ticket {ticket.ticket_number}",
                message=f"New critical complaint from {user.name}: '{ticket.subject[:60]}'",
                notification_type=NotificationType.CRITICAL_TICKET,
                ticket_id=ticket.id,
                link=f"/admin/tickets/{ticket.ticket_number}",
            )

        return ticket
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to create ticket: {str(e)}", exc_info=True)
        raise e


def add_ticket_message(
    ticket: Ticket,
    sender_id: int | None,
    sender_name: str,
    sender_type: str,
    message: str,
    is_internal: bool = False,
) -> TicketMessage:
    """Add a customer or support reply to the ticket thread with state handling."""
    message = message.strip()
    if not message:
        raise ValueError("Message content cannot be empty.")

    if ticket.status == TicketStatus.CLOSED and sender_type == SenderType.CUSTOMER:
        raise ValueError("Cannot reply to a closed ticket. Please open a new complaint.")

    # If customer replies to a resolved ticket, reopen to IN_PROGRESS
    if ticket.status == TicketStatus.RESOLVED and sender_type == SenderType.CUSTOMER:
        ticket.status = TicketStatus.IN_PROGRESS
        ticket.resolved_at = None
        reopen_sys = TicketMessage(
            ticket_id=ticket.id,
            sender_id=None,
            sender_name="System",
            sender_type=SenderType.SYSTEM,
            message="Ticket automatically reopened to 'In Progress' upon receiving customer reply.",
            is_internal=False,
        )
        db.session.add(reopen_sys)
        
        audit = TicketAuditLog(
            ticket_id=ticket.id,
            user_id=sender_id,
            actor_name=sender_name,
            action=AuditAction.REOPENED,
            old_value=TicketStatus.RESOLVED,
            new_value=TicketStatus.IN_PROGRESS,
            details="Customer replied to resolved ticket.",
        )
        db.session.add(audit)

    # If customer replies to WAITING_FOR_CUSTOMER, move to IN_PROGRESS
    elif ticket.status == TicketStatus.WAITING_FOR_CUSTOMER and sender_type == SenderType.CUSTOMER:
        ticket.status = TicketStatus.IN_PROGRESS

    msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=sender_id,
        sender_name=sender_name,
        sender_type=sender_type if sender_type in SenderType.ALL else SenderType.CUSTOMER,
        message=message,
        is_internal=is_internal,
    )
    db.session.add(msg)
    ticket.updated_at = datetime.now(timezone.utc)

    # Audit log
    audit_action = AuditAction.CUSTOMER_REPLIED if sender_type == SenderType.CUSTOMER else AuditAction.SUPPORT_REPLIED
    audit = TicketAuditLog(
        ticket_id=ticket.id,
        user_id=sender_id,
        actor_name=sender_name,
        action=audit_action,
        details=f"{'Internal Note' if is_internal else 'Message'}: {message[:100]}...",
    )
    db.session.add(audit)

    # Notify customer if support replied
    if sender_type == SenderType.SUPPORT and not is_internal:
        create_notification(
            user_id=ticket.user_id,
            title=f"Support Agent Replied to {ticket.ticket_number}",
            message=f"{sender_name}: '{message[:80]}...'",
            notification_type=NotificationType.SUPPORT_REPLY,
            ticket_id=ticket.id,
            link=f"/tickets/{ticket.ticket_number}",
        )

    db.session.commit()
    return msg


def add_support_reply(ticket: Ticket, sender_id: int, sender_name: str, message: str) -> TicketMessage:
    """Convenience method for support agent responses."""
    msg = add_ticket_message(
        ticket=ticket,
        sender_id=sender_id,
        sender_name=sender_name,
        sender_type=SenderType.SUPPORT,
        message=message,
        is_internal=False,
    )
    # Transition to WAITING_FOR_CUSTOMER if in progress or open
    if ticket.status in (TicketStatus.OPEN, TicketStatus.IN_PROGRESS):
        ticket.status = TicketStatus.WAITING_FOR_CUSTOMER
        db.session.commit()
    return msg


def update_ticket_status(ticket: Ticket, new_status: str, actor_name: str, user_id: Optional[int] = None) -> Ticket:
    """Update ticket lifecycle status with strict transition validation and audit logging."""
    if new_status not in TicketStatus.ALL:
        raise ValueError(f"Invalid status '{new_status}'.")

    old_status = ticket.status
    if old_status == new_status:
        return ticket

    # Validate transition
    allowed = VALID_STATUS_TRANSITIONS.get(old_status, [])
    if new_status not in allowed:
        raise ValueError(f"Invalid status transition from '{old_status}' to '{new_status}'.")

    ticket.status = new_status
    ticket.updated_at = datetime.now(timezone.utc)

    if new_status == TicketStatus.RESOLVED:
        ticket.resolved_at = datetime.now(timezone.utc)
        # Resolve active escalations
        for esc in ticket.escalations:
            if esc.status == EscalationStatus.ACTIVE:
                esc.status = EscalationStatus.RESOLVED
                esc.resolved_at = datetime.now(timezone.utc)
        # Notify customer
        create_notification(
            user_id=ticket.user_id,
            title=f"Ticket {ticket.ticket_number} Resolved",
            message=f"Your ticket '{ticket.subject[:50]}' has been marked as resolved by {actor_name}.",
            notification_type=NotificationType.TICKET_RESOLVED,
            ticket_id=ticket.id,
            link=f"/tickets/{ticket.ticket_number}",
        )
    elif new_status == TicketStatus.CLOSED:
        ticket.closed_at = datetime.now(timezone.utc)
        if not ticket.resolved_at:
            ticket.resolved_at = datetime.now(timezone.utc)
    elif old_status in (TicketStatus.RESOLVED, TicketStatus.CLOSED) and new_status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        ticket.resolved_at = None
        ticket.closed_at = None

    # System message
    sys_msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=None,
        sender_name="System",
        sender_type=SenderType.SYSTEM,
        message=f"Status changed from '{old_status}' to '{new_status}' by {actor_name}.",
        is_internal=False,
    )
    db.session.add(sys_msg)

    # Audit Log
    audit = TicketAuditLog(
        ticket_id=ticket.id,
        user_id=user_id,
        actor_name=actor_name,
        action=AuditAction.STATUS_CHANGED,
        old_value=old_status,
        new_value=new_status,
        details=f"Status transitioned from {old_status} to {new_status} by {actor_name}.",
    )
    db.session.add(audit)

    db.session.commit()
    return ticket


def reopen_ticket(ticket: Ticket, actor_id: int, actor_name: str, reason: str = "") -> Ticket:
    """Customer or staff action to reopen a resolved/closed ticket."""
    if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise ValueError("Only resolved or closed tickets can be reopened.")

    old_status = ticket.status
    ticket.status = TicketStatus.IN_PROGRESS
    ticket.resolved_at = None
    ticket.closed_at = None
    ticket.updated_at = datetime.now(timezone.utc)

    # System announcement
    reopen_text = f"Ticket reopened to 'In Progress' by {actor_name}."
    if reason:
        reopen_text += f" Reason: {reason}"

    sys_msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=None,
        sender_name="System",
        sender_type=SenderType.SYSTEM,
        message=reopen_text,
        is_internal=False,
    )
    db.session.add(sys_msg)

    # Audit Log
    audit = TicketAuditLog(
        ticket_id=ticket.id,
        user_id=actor_id,
        actor_name=actor_name,
        action=AuditAction.REOPENED,
        old_value=old_status,
        new_value=TicketStatus.IN_PROGRESS,
        details=reopen_text,
    )
    db.session.add(audit)

    # Notify Support Staff
    notify_support_staff(
        title=f"Ticket {ticket.ticket_number} Reopened",
        message=f"{actor_name} reopened ticket '{ticket.subject[:50]}'.",
        notification_type=NotificationType.TICKET_REOPENED,
        ticket_id=ticket.id,
        link=f"/admin/tickets/{ticket.ticket_number}",
    )

    db.session.commit()
    return ticket


def request_human_support(ticket: Ticket, user_id: int, user_name: str, reason: str = "") -> Escalation:
    """Customer-initiated request to escalate ticket to human support."""
    active_esc = (
        db.session.query(Escalation)
        .filter_by(ticket_id=ticket.id, status=EscalationStatus.ACTIVE)
        .first()
    )
    if active_esc:
        return active_esc

    from app.services.escalation_service import EscalationService
    if ticket.assigned_team == SupportTeam.UNASSIGNED:
        ticket.assigned_team = EscalationService.suggest_team_for_category(ticket.category)

    old_status = ticket.status
    ticket.status = TicketStatus.ESCALATED
    ticket.updated_at = datetime.now(timezone.utc)

    esc_reason = reason.strip() or "Customer requested direct human support assistance."
    escalation = Escalation(
        ticket_id=ticket.id,
        reason=f"[{EscalationReason.CUSTOMER_REQUESTED_SUPPORT}] {esc_reason}",
        escalated_by=user_name,
        escalation_type=EscalationType.MANUAL,
        target_team=ticket.assigned_team,
        status=EscalationStatus.ACTIVE,
    )
    db.session.add(escalation)

    # System message in thread
    sys_msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=None,
        sender_name="System",
        sender_type=SenderType.SYSTEM,
        message=f"Human support requested by customer. Ticket escalated to {ticket.assigned_team}.",
        is_internal=False,
    )
    db.session.add(sys_msg)

    # Audit Log
    audit = TicketAuditLog(
        ticket_id=ticket.id,
        user_id=user_id,
        actor_name=user_name,
        action=AuditAction.CONTACT_SUPPORT_REQUESTED,
        old_value=old_status,
        new_value=TicketStatus.ESCALATED,
        details=esc_reason,
    )
    db.session.add(audit)

    # Broadcast notification to support staff
    notify_support_staff(
        title=f"Customer Requested Human Support: {ticket.ticket_number}",
        message=f"{user_name} requested human support for '{ticket.subject[:50]}'. Assigned: {ticket.assigned_team}",
        notification_type=NotificationType.TICKET_ESCALATED,
        ticket_id=ticket.id,
        link=f"/admin/tickets/{ticket.ticket_number}",
    )

    db.session.commit()
    return escalation


def update_ticket_priority(ticket: Ticket, new_priority: str, actor_name: str, user_id: Optional[int] = None) -> Ticket:
    """Update ticket priority rating with audit logging."""
    if new_priority not in TicketPriority.ALL:
        raise ValueError(f"Invalid priority '{new_priority}'.")

    old_priority = ticket.priority
    if old_priority == new_priority:
        return ticket

    ticket.priority = new_priority
    ticket.updated_at = datetime.now(timezone.utc)

    sys_msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=None,
        sender_name="System",
        sender_type=SenderType.SYSTEM,
        message=f"Priority updated from '{old_priority}' to '{new_priority}' by {actor_name}.",
        is_internal=False,
    )
    db.session.add(sys_msg)

    audit = TicketAuditLog(
        ticket_id=ticket.id,
        user_id=user_id,
        actor_name=actor_name,
        action=AuditAction.PRIORITY_CHANGED,
        old_value=old_priority,
        new_value=new_priority,
        details=f"Priority changed from {old_priority} to {new_priority}.",
    )
    db.session.add(audit)

    db.session.commit()
    return ticket


def update_ticket_category(ticket: Ticket, new_category: str, actor_name: str, user_id: Optional[int] = None) -> Ticket:
    """Update ticket category with audit logging and auto-team suggestion."""
    if new_category not in TicketCategory.ALL:
        raise ValueError(f"Invalid category '{new_category}'.")

    old_cat = ticket.category
    if old_cat == new_category:
        return ticket

    ticket.category = new_category
    ticket.updated_at = datetime.now(timezone.utc)

    sys_msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=None,
        sender_name="System",
        sender_type=SenderType.SYSTEM,
        message=f"Category updated from '{old_cat}' to '{new_category}' by {actor_name}.",
        is_internal=False,
    )
    db.session.add(sys_msg)

    audit = TicketAuditLog(
        ticket_id=ticket.id,
        user_id=user_id,
        actor_name=actor_name,
        action=AuditAction.CATEGORY_CHANGED,
        old_value=old_cat,
        new_value=new_category,
        details=f"Category updated from {old_cat} to {new_category}.",
    )
    db.session.add(audit)

    db.session.commit()
    return ticket


def update_ticket_team(ticket: Ticket, new_team: str, actor_name: str, user_id: Optional[int] = None) -> Ticket:
    """Update assigned support team with audit logging."""
    if new_team not in SupportTeam.ALL:
        raise ValueError(f"Invalid support team '{new_team}'.")

    old_team = ticket.assigned_team
    if old_team == new_team:
        return ticket

    ticket.assigned_team = new_team
    ticket.updated_at = datetime.now(timezone.utc)

    sys_msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=None,
        sender_name="System",
        sender_type=SenderType.SYSTEM,
        message=f"Assigned team changed from '{old_team}' to '{new_team}' by {actor_name}.",
        is_internal=False,
    )
    db.session.add(sys_msg)

    audit = TicketAuditLog(
        ticket_id=ticket.id,
        user_id=user_id,
        actor_name=actor_name,
        action=AuditAction.TEAM_CHANGED,
        old_value=old_team,
        new_value=new_team,
        details=f"Assigned team changed from {old_team} to {new_team}.",
    )
    db.session.add(audit)

    db.session.commit()
    return ticket


def add_internal_note(ticket: Ticket, author_id: int, author_name: str, note: str) -> InternalNote:
    """Add a support-only internal note to a ticket with audit logging."""
    note = note.strip()
    if not note:
        raise ValueError("Internal note cannot be empty.")

    internal_note = InternalNote(
        ticket_id=ticket.id,
        author_id=author_id,
        author_name=author_name,
        note=note,
    )
    db.session.add(internal_note)
    ticket.updated_at = datetime.now(timezone.utc)

    audit = TicketAuditLog(
        ticket_id=ticket.id,
        user_id=author_id,
        actor_name=author_name,
        action=AuditAction.INTERNAL_NOTE_ADDED,
        details=f"Internal note added: {note[:80]}...",
    )
    db.session.add(audit)

    db.session.commit()
    return internal_note


def escalate_ticket(ticket: Ticket, reason: str, escalated_by: str, target_team: str = None, user_id: Optional[int] = None) -> Escalation:
    """Manually escalate a ticket to priority support."""
    reason = reason.strip()
    if not reason:
        raise ValueError("Escalation reason is required.")

    if target_team and target_team in SupportTeam.ALL:
        ticket.assigned_team = target_team

    old_status = ticket.status
    ticket.status = TicketStatus.ESCALATED
    ticket.updated_at = datetime.now(timezone.utc)

    escalation = Escalation(
        ticket_id=ticket.id,
        reason=reason,
        escalated_by=escalated_by,
        escalation_type=EscalationType.MANUAL,
        target_team=ticket.assigned_team,
        status=EscalationStatus.ACTIVE,
    )
    db.session.add(escalation)

    customer_msg = TicketMessage(
        ticket_id=ticket.id,
        sender_id=None,
        sender_name="System",
        sender_type=SenderType.SYSTEM,
        message=f"Your ticket has been escalated to {ticket.assigned_team} for priority handling.",
        is_internal=False,
    )
    db.session.add(customer_msg)

    internal_note = InternalNote(
        ticket_id=ticket.id,
        author_id=user_id or ticket.user_id,
        author_name=escalated_by,
        note=f"[ESCALATION REASON]: {reason}",
    )
    db.session.add(internal_note)

    audit = TicketAuditLog(
        ticket_id=ticket.id,
        user_id=user_id,
        actor_name=escalated_by,
        action=AuditAction.ESCALATED,
        old_value=old_status,
        new_value=TicketStatus.ESCALATED,
        details=f"Manual escalation: {reason}",
    )
    db.session.add(audit)

    notify_support_staff(
        title=f"Ticket {ticket.ticket_number} Manually Escalated",
        message=f"{escalated_by} escalated ticket to {ticket.assigned_team}. Reason: {reason[:60]}",
        notification_type=NotificationType.TICKET_ESCALATED,
        ticket_id=ticket.id,
        link=f"/admin/tickets/{ticket.ticket_number}",
    )

    db.session.commit()
    return escalation


def get_customer_stats(user_id: int) -> dict:
    """Calculate real database metrics for a customer."""
    total = db.session.query(func.count(Ticket.id)).filter_by(user_id=user_id).scalar() or 0
    open_count = db.session.query(func.count(Ticket.id)).filter(
        Ticket.user_id == user_id,
        Ticket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_FOR_CUSTOMER])
    ).scalar() or 0
    resolved = db.session.query(func.count(Ticket.id)).filter(
        Ticket.user_id == user_id,
        Ticket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED])
    ).scalar() or 0
    escalated = db.session.query(func.count(Ticket.id)).filter(
        Ticket.user_id == user_id,
        Ticket.status == TicketStatus.ESCALATED
    ).scalar() or 0

    return {
        "total_tickets": total,
        "open_tickets": open_count,
        "resolved_tickets": resolved,
        "escalated_tickets": escalated,
    }


def get_admin_stats(date_range: str = "all") -> dict:
    """Calculate real operational metrics, AI/RAG performance, and SLA distributions from SQLite."""
    now = datetime.now(timezone.utc)
    date_filter = None

    if date_range == "today":
        start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        date_filter = Ticket.created_at >= start_of_day
    elif date_range == "7d":
        date_filter = Ticket.created_at >= (now - timedelta(days=7))
    elif date_range == "30d":
        date_filter = Ticket.created_at >= (now - timedelta(days=30))

    base_query = db.session.query(Ticket)
    if date_filter is not None:
        base_query = base_query.filter(date_filter)

    total = base_query.count()
    open_count = base_query.filter(Ticket.status == TicketStatus.OPEN).count()
    in_progress = base_query.filter(Ticket.status == TicketStatus.IN_PROGRESS).count()
    waiting_cust = base_query.filter(Ticket.status == TicketStatus.WAITING_FOR_CUSTOMER).count()
    escalated = base_query.filter(Ticket.status == TicketStatus.ESCALATED).count()
    resolved = base_query.filter(Ticket.status == TicketStatus.RESOLVED).count()
    closed = base_query.filter(Ticket.status == TicketStatus.CLOSED).count()
    critical = base_query.filter(Ticket.priority == TicketPriority.CRITICAL).count()

    # Escalation Metrics
    active_escalations = db.session.query(func.count(Escalation.id)).filter_by(status=EscalationStatus.ACTIVE).scalar() or 0
    auto_escalations = db.session.query(func.count(Escalation.id)).filter_by(escalation_type=EscalationType.AUTOMATIC).scalar() or 0
    manual_escalations = db.session.query(func.count(Escalation.id)).filter_by(escalation_type=EscalationType.MANUAL).scalar() or 0
    resolved_escalations = db.session.query(func.count(Escalation.id)).filter_by(status=EscalationStatus.RESOLVED).scalar() or 0

    # AI Analysis Metrics
    ai_total = db.session.query(func.count(AIAnalysis.id)).scalar() or 0
    ai_completed = db.session.query(func.count(AIAnalysis.id)).filter_by(status=AIAnalysisStatus.COMPLETED).scalar() or 0
    ai_failures = db.session.query(func.count(AIAnalysis.id)).filter_by(status=AIAnalysisStatus.FAILED).scalar() or 0
    ai_success_rate = round((ai_completed / ai_total * 100), 1) if ai_total > 0 else 0.0

    # RAG Resolution Metrics
    rag_total = db.session.query(func.count(RAGResolution.id)).scalar() or 0
    rag_completed = db.session.query(func.count(RAGResolution.id)).filter_by(status=RAGStatus.COMPLETED).scalar() or 0
    rag_no_context = db.session.query(func.count(RAGResolution.id)).filter_by(status=RAGStatus.NO_RELEVANT_CONTEXT).scalar() or 0
    rag_failures = db.session.query(func.count(RAGResolution.id)).filter_by(status=RAGStatus.FAILED).scalar() or 0
    rag_success_rate = round((rag_completed / rag_total * 100), 1) if rag_total > 0 else 0.0

    # Performance: Average Resolution Time (in hours)
    resolved_tickets = (
        db.session.query(Ticket.created_at, Ticket.resolved_at)
        .filter(Ticket.resolved_at.isnot(None))
        .all()
    )
    resolution_durations = [
        (t.resolved_at - t.created_at).total_seconds() / 3600.0
        for t in resolved_tickets if t.resolved_at and t.created_at and t.resolved_at >= t.created_at
    ]
    avg_resolution_hours = round(sum(resolution_durations) / len(resolution_durations), 1) if resolution_durations else None

    # Performance: Average First Response Time (in minutes)
    first_responses = []
    tickets_with_msgs = db.session.query(Ticket).all()
    for t in tickets_with_msgs:
        first_support_msg = next((m for m in t.messages if m.sender_type == SenderType.SUPPORT), None)
        if first_support_msg and t.created_at:
            delta_mins = (first_support_msg.created_at - t.created_at).total_seconds() / 60.0
            if delta_mins >= 0:
                first_responses.append(delta_mins)
    avg_response_mins = round(sum(first_responses) / len(first_responses), 1) if first_responses else None
    avg_first_response_hours = round(avg_response_mins / 60.0, 1) if avg_response_mins is not None else None

    # Performance Rates
    ai_resolution_rate = round((rag_completed / total * 100), 1) if total > 0 else 0.0
    escalation_rate = round((escalated / total * 100), 1) if total > 0 else 0.0

    # Category Distribution
    category_counts = (
        base_query.with_entities(Ticket.category, func.count(Ticket.id))
        .group_by(Ticket.category)
        .all()
    )
    category_distribution = {cat: count for cat, count in category_counts if cat}

    # Sentiment Distribution
    sentiment_counts = (
        base_query.with_entities(Ticket.sentiment, func.count(Ticket.id))
        .group_by(Ticket.sentiment)
        .all()
    )
    sentiment_distribution = {sent: count for sent, count in sentiment_counts if sent}

    # Priority Distribution
    priority_counts = (
        base_query.with_entities(Ticket.priority, func.count(Ticket.id))
        .group_by(Ticket.priority)
        .all()
    )
    priority_distribution = {prio: count for prio, count in priority_counts if prio}

    return {
        "date_range": date_range,
        "total_tickets": total,
        "open_tickets": open_count,
        "in_progress_tickets": in_progress,
        "waiting_for_customer_tickets": waiting_cust,
        "escalated_tickets": escalated,
        "resolved_tickets": resolved,
        "closed_tickets": closed,
        "critical_tickets": critical,
        "active_escalations": active_escalations,
        "auto_escalations": auto_escalations,
        "manual_escalations": manual_escalations,
        "resolved_escalations": resolved_escalations,
        "ai_total": ai_total,
        "ai_completed": ai_completed,
        "ai_failures": ai_failures,
        "ai_success_rate": ai_success_rate,
        "rag_total": rag_total,
        "rag_completed": rag_completed,
        "rag_no_context": rag_no_context,
        "rag_failures": rag_failures,
        "rag_success_rate": rag_success_rate,
        "ai_resolution_rate": ai_resolution_rate,
        "escalation_rate": escalation_rate,
        "avg_resolution_hours": avg_resolution_hours,
        "avg_response_mins": avg_response_mins,
        "avg_first_response_hours": avg_first_response_hours,
        "category_distribution": category_distribution,
        "sentiment_distribution": sentiment_distribution,
        "priority_distribution": priority_distribution,
    }
