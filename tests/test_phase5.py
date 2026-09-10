import pytest
import os
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.ticket import Ticket, TicketCategory, TicketPriority, TicketStatus, SupportTeam
from app.models.escalation import Escalation, EscalationStatus, EscalationType, EscalationReason
from app.models.audit_log import TicketAuditLog, AuditAction
from app.models.notification import Notification, NotificationType
from app.models.rag_resolution import RAGResolution, RAGStatus
from app.services.ticket_service import (
    create_ticket,
    update_ticket_status,
    update_ticket_priority,
    update_ticket_team,
    add_internal_note,
    add_support_reply,
    reopen_ticket,
    request_human_support,
    get_admin_stats,
)
from app.services.escalation_service import EscalationService
from app.services.notification_service import (
    create_notification,
    notify_support_staff,
    get_user_notifications,
    get_unread_count,
    mark_as_read,
    mark_all_as_read,
)


@pytest.fixture
def app(tmp_path):
    app = create_app("testing")
    vector_dir = str(tmp_path / "vector_store")
    upload_dir = str(tmp_path / "knowledge_docs")
    os.makedirs(vector_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)
    
    app.config["VECTOR_STORE_PATH"] = vector_dir
    app.config["UPLOAD_FOLDER"] = upload_dir

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seed_users(app):
    with app.app_context():
        cust = User(name="Test Customer", email="customer@test.com", role="customer")
        cust.set_password("password123")

        support = User(name="Test Support", email="support@test.com", role="support")
        support.set_password("password123")

        admin = User(name="Test Admin", email="admin@test.com", role="admin")
        admin.set_password("password123")

        db.session.add_all([cust, support, admin])
        db.session.commit()
        return {"cust_id": cust.id, "support_id": support.id, "admin_id": admin.id}


# ---------------------------------------------------------------------------
# Escalation Engine Tests
# ---------------------------------------------------------------------------

def test_auto_escalate_critical_priority(app, seed_users):
    """Tickets with CRITICAL priority are automatically escalated."""
    with app.app_context():
        ticket = create_ticket(
            user_id=seed_users["cust_id"],
            subject="System total outage on server",
            description="Our primary database is corrupted and the entire application is down.",
            product_service="Cloud Hosting",
            priority=TicketPriority.CRITICAL,
        )
        assert ticket.status == TicketStatus.ESCALATED
        assert ticket.priority == TicketPriority.CRITICAL
        assert len(ticket.escalations) == 1
        assert ticket.escalations[0].escalation_type == EscalationType.AUTOMATIC


def test_auto_escalate_security_category(app, seed_users):
    """Tickets with Security/Privacy Breach category are auto-escalated to Technical/Security team."""
    with app.app_context():
        ticket = create_ticket(
            user_id=seed_users["cust_id"],
            subject="Unauthorized data access detected",
            description="Someone accessed my account from an unknown IP and changed billing details.",
            product_service="Account System",
            category=TicketCategory.SECURITY,
        )
        assert ticket.status == TicketStatus.ESCALATED
        assert ticket.assigned_team == SupportTeam.TECHNICAL_SUPPORT
        assert len(ticket.escalations) == 1


def test_escalation_idempotency(app, seed_users):
    """Multiple evaluations of an escalated ticket do not create duplicate active records."""
    with app.app_context():
        ticket = create_ticket(
            user_id=seed_users["cust_id"],
            subject="Critical server panic",
            description="Kernel panic on restart.",
            product_service="Linux VPS",
            priority=TicketPriority.CRITICAL,
        )
        first_esc = EscalationService.evaluate(ticket)
        second_esc = EscalationService.evaluate(ticket)
        
        assert first_esc.id == second_esc.id
        total_esc = db.session.query(Escalation).filter_by(ticket_id=ticket.id).count()
        assert total_esc == 1


def test_team_suggestion_heuristics():
    """Verify category to support department mapping logic."""
    assert EscalationService.suggest_team_for_category(TicketCategory.BILLING) == SupportTeam.BILLING_SUPPORT
    assert EscalationService.suggest_team_for_category(TicketCategory.REFUND) == SupportTeam.BILLING_SUPPORT
    assert EscalationService.suggest_team_for_category(TicketCategory.TECHNICAL_ISSUE) == SupportTeam.TECHNICAL_SUPPORT
    assert EscalationService.suggest_team_for_category(TicketCategory.SECURITY) == SupportTeam.TECHNICAL_SUPPORT
    assert EscalationService.suggest_team_for_category(TicketCategory.DELIVERY) == SupportTeam.DELIVERY_SUPPORT
    assert EscalationService.suggest_team_for_category(TicketCategory.ACCOUNT) == SupportTeam.ACCOUNT_SUPPORT
    assert EscalationService.suggest_team_for_category("Unknown") == SupportTeam.SENIOR_SUPPORT


# ---------------------------------------------------------------------------
# Status Workflow & Transitions
# ---------------------------------------------------------------------------

def test_valid_and_invalid_status_transitions(app, seed_users):
    """Strict validation prevents illegal lifecycle jumps."""
    with app.app_context():
        ticket = create_ticket(
            user_id=seed_users["cust_id"],
            subject="Billing question",
            description="Need invoice copy.",
            product_service="Billing Service",
        )
        assert ticket.status == TicketStatus.OPEN

        # Valid transition: OPEN -> IN_PROGRESS
        update_ticket_status(ticket, TicketStatus.IN_PROGRESS, "Support Agent")
        assert ticket.status == TicketStatus.IN_PROGRESS

        # Valid transition: IN_PROGRESS -> RESOLVED
        update_ticket_status(ticket, TicketStatus.RESOLVED, "Support Agent")
        assert ticket.status == TicketStatus.RESOLVED
        assert ticket.resolved_at is not None

        # Invalid transition: RESOLVED -> WAITING_FOR_CUSTOMER (must go through IN_PROGRESS or CLOSED)
        with pytest.raises(ValueError, match="Invalid status transition"):
            update_ticket_status(ticket, TicketStatus.WAITING_FOR_CUSTOMER, "Support Agent")


def test_customer_and_staff_reopen_workflow(app, seed_users):
    """Resolved or closed tickets can be reopened to IN_PROGRESS."""
    with app.app_context():
        ticket = create_ticket(
            user_id=seed_users["cust_id"],
            subject="Refund query",
            description="Checking status.",
            product_service="Store",
        )
        update_ticket_status(ticket, TicketStatus.IN_PROGRESS, "Agent")
        update_ticket_status(ticket, TicketStatus.RESOLVED, "Agent")
        assert ticket.status == TicketStatus.RESOLVED

        # Reopen
        reopened = reopen_ticket(ticket, seed_users["cust_id"], "Test Customer", "Issue recurred today")
        assert reopened.status == TicketStatus.IN_PROGRESS
        assert reopened.resolved_at is None

        # Audit log verified
        logs = db.session.query(TicketAuditLog).filter_by(ticket_id=ticket.id, action=AuditAction.REOPENED).all()
        assert len(logs) == 1
        assert "Issue recurred today" in logs[0].details


def test_customer_request_human_support(app, seed_users):
    """Customer can request human support escalation."""
    with app.app_context():
        ticket = create_ticket(
            user_id=seed_users["cust_id"],
            subject="Complex custom configuration",
            description="Need custom VPC setup instructions.",
            product_service="VPC",
        )
        assert ticket.status == TicketStatus.OPEN

        esc = request_human_support(ticket, seed_users["cust_id"], "Test Customer", "Automated guide was too brief")
        assert esc.status == EscalationStatus.ACTIVE
        assert ticket.status == TicketStatus.ESCALATED
        assert esc.escalation_type == EscalationType.MANUAL


# ---------------------------------------------------------------------------
# Support Reply & Public Threading
# ---------------------------------------------------------------------------

def test_support_reply_updates_state_and_notifies_customer(app, seed_users):
    """Support response moves ticket to WAITING_FOR_CUSTOMER and sends notification."""
    with app.app_context():
        ticket = create_ticket(
            user_id=seed_users["cust_id"],
            subject="Account login issues",
            description="Password reset token expired.",
            product_service="Auth",
        )
        update_ticket_status(ticket, TicketStatus.IN_PROGRESS, "Agent")

        msg = add_support_reply(ticket, seed_users["support_id"], "Agent Dave", "We have reset your session.")
        assert msg.sender_type == "SUPPORT"
        assert ticket.status == TicketStatus.WAITING_FOR_CUSTOMER

        # Check customer notification
        notifs = get_user_notifications(seed_users["cust_id"])
        assert len(notifs) >= 1
        assert "Agent Dave" in notifs[0].message


# ---------------------------------------------------------------------------
# Audit Trail Logging
# ---------------------------------------------------------------------------

def test_comprehensive_audit_trail(app, seed_users):
    """All ticket actions create timestamped audit logs."""
    with app.app_context():
        ticket = create_ticket(
            user_id=seed_users["cust_id"],
            subject="Order tracking",
            description="Where is package?",
            product_service="Shipping",
        )
        # 1. Created audit
        created_log = db.session.query(TicketAuditLog).filter_by(ticket_id=ticket.id, action=AuditAction.STATUS_CHANGED).first()
        assert created_log is not None

        # 2. Priority change audit
        update_ticket_priority(ticket, TicketPriority.HIGH, "Agent Sarah")
        prio_log = db.session.query(TicketAuditLog).filter_by(ticket_id=ticket.id, action=AuditAction.PRIORITY_CHANGED).first()
        assert prio_log is not None
        assert prio_log.new_value == TicketPriority.HIGH

        # 3. Department change audit
        update_ticket_team(ticket, SupportTeam.DELIVERY_SUPPORT, "Agent Sarah")
        team_log = db.session.query(TicketAuditLog).filter_by(ticket_id=ticket.id, action=AuditAction.TEAM_CHANGED).first()
        assert team_log is not None
        assert team_log.new_value == SupportTeam.DELIVERY_SUPPORT

        # 4. Internal note audit
        add_internal_note(ticket, seed_users["support_id"], "Agent Sarah", "Courier tracking number is 998811.")
        note_log = db.session.query(TicketAuditLog).filter_by(ticket_id=ticket.id, action=AuditAction.INTERNAL_NOTE_ADDED).first()
        assert note_log is not None


# ---------------------------------------------------------------------------
# In-App Notifications Service & API
# ---------------------------------------------------------------------------

def test_notification_lifecycle_and_unread_counts(app, seed_users, client):
    """Verify notification creation, count, and marking read."""
    with app.app_context():
        n1 = create_notification(seed_users["cust_id"], "Title 1", "Message 1", NotificationType.SUPPORT_REPLY)
        n2 = create_notification(seed_users["cust_id"], "Title 2", "Message 2", NotificationType.TICKET_RESOLVED)

        assert get_unread_count(seed_users["cust_id"]) == 2
        
        # Mark one as read
        mark_as_read(n1.id, seed_users["cust_id"])
        assert get_unread_count(seed_users["cust_id"]) == 1

        # Mark all as read
        mark_all_as_read(seed_users["cust_id"])
        assert get_unread_count(seed_users["cust_id"]) == 0


def test_notifications_api_endpoints(client, seed_users):
    """Test API routes for notifications."""
    # Login as customer
    client.post("/api/auth/login", json={"email": "customer@test.com", "password": "password123"})

    # Fetch empty notifications
    res = client.get("/api/notifications")
    assert res.status_code == 200
    assert res.json["data"]["unread_count"] == 0

    # Read-all endpoint
    read_all = client.post("/api/notifications/read-all")
    assert read_all.status_code == 200
    assert read_all.json["data"]["marked_count"] == 0


# ---------------------------------------------------------------------------
# Real Analytics & Date Range Filtering
# ---------------------------------------------------------------------------

def test_admin_analytics_date_range_query(app, seed_users):
    """Verify get_admin_stats properly calculates metrics without mock data."""
    with app.app_context():
        ticket1 = create_ticket(
            user_id=seed_users["cust_id"],
            subject="Analytics test 1",
            description="Test query 1",
            product_service="App",
        )
        update_ticket_status(ticket1, TicketStatus.IN_PROGRESS, "Agent")
        update_ticket_status(ticket1, TicketStatus.RESOLVED, "Agent")

        stats_all = get_admin_stats(date_range="all")
        assert stats_all["total_tickets"] >= 1
        assert stats_all["resolved_tickets"] >= 1
        assert "avg_resolution_hours" in stats_all
        assert "ai_resolution_rate" in stats_all
        assert "escalation_rate" in stats_all

        stats_today = get_admin_stats(date_range="today")
        assert stats_today["total_tickets"] >= 1
