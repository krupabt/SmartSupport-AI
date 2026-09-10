import pytest
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory, SupportTeam
from app.models.ticket_message import TicketMessage, SenderType
from app.models.internal_note import InternalNote
from app.models.escalation import Escalation, EscalationStatus
from app.services.ticket_service import (
    generate_unique_ticket_number,
    create_ticket,
    add_ticket_message,
    update_ticket_status,
    update_ticket_priority,
    update_ticket_team,
    add_internal_note,
    escalate_ticket,
    get_customer_stats,
    get_admin_stats,
)


@pytest.fixture
def app():
    """Create testing application context with clean database."""
    app = create_app("testing")

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Testing client."""
    return app.test_client()


@pytest.fixture
def seed_users(app):
    """Seed customer A, customer B, and support agent."""
    with app.app_context():
        cust_a = User(name="Alice Customer", email="alice@test.com", role="customer")
        cust_a.set_password("password123")

        cust_b = User(name="Bob Customer", email="bob@test.com", role="customer")
        cust_b.set_password("password123")

        support = User(name="Sarah Support", email="support@test.com", role="support")
        support.set_password("password123")

        admin = User(name="Alex Admin", email="admin@test.com", role="admin")
        admin.set_password("password123")

        db.session.add_all([cust_a, cust_b, support, admin])
        db.session.commit()

        return {
            "cust_a_id": cust_a.id,
            "cust_b_id": cust_b.id,
            "support_id": support.id,
            "admin_id": admin.id,
        }


# ---------------------------------------------------------------------------
# 1. Model Creation & 2. Ticket Number Generation
# ---------------------------------------------------------------------------

def test_ticket_model_and_number_generation(app, seed_users):
    """Test Ticket model creation and format TKT-YYYY-XXXXXX."""
    with app.app_context():
        num1 = generate_unique_ticket_number()
        assert num1.startswith("TKT-")
        assert len(num1.split("-")[-1]) == 6

        ticket = create_ticket(
            user_id=seed_users["cust_a_id"],
            subject="Delayed delivery issue",
            description="My package has been stuck in transit for 5 days.",
            product_service="Standard Shipping",
            reference_id="ORD-10023",
        )
        assert ticket.id is not None
        assert ticket.ticket_number.startswith("TKT-")
        assert ticket.status == TicketStatus.OPEN
        assert ticket.category in (TicketCategory.GENERAL, "Delivery")
        assert len(ticket.messages) == 2  # Customer initial description + System log


# ---------------------------------------------------------------------------
# 3. Customer Complaint Submission & 4. Database Storage
# ---------------------------------------------------------------------------

def test_customer_complaint_submission_web(client, seed_users):
    """Test customer submitting complaint via web form."""
    # Login as Alice
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})

    response = client.post("/submit-complaint", data={
        "subject": "Double charged for Pro Subscription",
        "description": "I was charged twice on my credit card for invoice #9921.",
        "product_service": "Pro Plan",
        "reference_id": "INV-9921",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b"Complaint registered successfully!" in response.data
    assert b"Double charged for Pro Subscription" in response.data


# ---------------------------------------------------------------------------
# 5. Customer Sees Own Ticket & 6. Customer Cannot See Other's Ticket
# ---------------------------------------------------------------------------

def test_ticket_access_isolation(client, seed_users):
    """Test that customer A can see their own ticket, but customer B gets 403 Forbidden."""
    # Alice creates ticket
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    res = client.post("/api/tickets", json={
        "subject": "Alice Private Complaint",
        "description": "Sensitive billing details for Alice",
        "product_service": "Payment Gateway",
    })
    ticket_num = res.json["data"]["ticket_number"]

    # Alice views her own ticket -> 200 OK
    alice_view = client.get(f"/tickets/{ticket_num}")
    assert alice_view.status_code == 200
    assert b"Alice Private Complaint" in alice_view.data

    # Logout Alice and Login Bob
    client.get("/logout")
    client.post("/login", data={"email": "bob@test.com", "password": "password123"})

    # Bob attempts to view Alice's ticket -> 403 Forbidden
    bob_view = client.get(f"/tickets/{ticket_num}")
    assert bob_view.status_code == 403
    assert b"403" in bob_view.data

    # Bob attempts to view via API -> 403 Forbidden
    bob_api = client.get(f"/api/tickets/{ticket_num}")
    assert bob_api.status_code == 403
    assert bob_api.json["success"] is False


# ---------------------------------------------------------------------------
# 7. Customer Ticket List with Search & Filter
# ---------------------------------------------------------------------------

def test_customer_ticket_listing(client, seed_users):
    """Test customer listing their tickets with filtering."""
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    
    # Create 2 tickets for Alice
    client.post("/api/tickets", json={
        "subject": "First Delivery Issue",
        "description": "Package missing description text",
        "product_service": "Delivery",
    })
    client.post("/api/tickets", json={
        "subject": "Second Billing Question",
        "description": "Invoice breakdown needed text",
        "product_service": "Billing",
    })

    # Fetch list
    list_res = client.get("/tickets")
    assert list_res.status_code == 200
    assert b"First Delivery Issue" in list_res.data
    assert b"Second Billing Question" in list_res.data

    # Search filter
    search_res = client.get("/tickets?q=Delivery")
    assert b"First Delivery Issue" in search_res.data
    assert b"Second Billing Question" not in search_res.data


# ---------------------------------------------------------------------------
# 8. Customer Reply & 9. Closed Ticket Reply Prevention
# ---------------------------------------------------------------------------

def test_customer_reply_and_closed_ticket_rules(client, app, seed_users):
    """Test customer adding reply and ensuring closed ticket cannot be replied to."""
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    res = client.post("/api/tickets", json={
        "subject": "Warranty claim inquiry",
        "description": "Screen cracked on day 2",
        "product_service": "Laptop",
    })
    ticket_num = res.json["data"]["ticket_number"]

    # Add valid customer reply
    reply_res = client.post(f"/tickets/{ticket_num}", data={
        "message": "Here is additional serial number info: SN-88219"
    }, follow_redirects=True)
    assert reply_res.status_code == 200
    assert b"Reply added to ticket thread" in reply_res.data
    assert b"SN-88219" in reply_res.data

    # Now close the ticket from backend
    with app.app_context():
        ticket = Ticket.query.filter_by(ticket_number=ticket_num).first()
        update_ticket_status(ticket, TicketStatus.CLOSED, "Sarah Support")

    # Attempt customer reply to closed ticket -> friendly warning / error
    closed_reply_res = client.post(f"/tickets/{ticket_num}", data={
        "message": "Can I still ask a question?"
    }, follow_redirects=True)
    assert b"Cannot reply to a closed ticket" in closed_reply_res.data


# ---------------------------------------------------------------------------
# 10. Support and 11. Admin Access & 12. Customer Blocked from Admin
# ---------------------------------------------------------------------------

def test_support_and_admin_queue_access(client, seed_users):
    """Test support and admin can view queue while normal customer is blocked with 403."""
    # Customer blocked
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    cust_res = client.get("/admin/tickets")
    assert cust_res.status_code == 403

    # Support allowed
    client.get("/logout")
    client.post("/login", data={"email": "support@test.com", "password": "password123"})
    support_res = client.get("/admin/tickets")
    assert support_res.status_code == 200
    assert b"Support Ticket Queue" in support_res.data

    # Admin allowed
    client.get("/logout")
    client.post("/login", data={"email": "admin@test.com", "password": "password123"})
    admin_res = client.get("/admin/tickets")
    assert admin_res.status_code == 200


# ---------------------------------------------------------------------------
# 13. Status, 14. Priority, 15. Team Changes & 16. Internal Notes
# ---------------------------------------------------------------------------

def test_support_management_actions(client, app, seed_users):
    """Test support changing status, priority, team, and adding internal notes."""
    # Alice creates ticket
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    res = client.post("/api/tickets", json={
        "subject": "Technical login crash",
        "description": "App crashes on login page on iOS",
        "product_service": "iOS App",
    })
    ticket_num = res.json["data"]["ticket_number"]

    # Support login
    client.get("/logout")
    client.post("/login", data={"email": "support@test.com", "password": "password123"})

    # Update Priority to HIGH
    client.post(f"/admin/tickets/{ticket_num}", data={
        "action": "update_priority",
        "priority": TicketPriority.HIGH,
    }, follow_redirects=True)

    # Assign Technical Support team
    client.post(f"/admin/tickets/{ticket_num}", data={
        "action": "update_team",
        "assigned_team": SupportTeam.TECHNICAL_SUPPORT,
    }, follow_redirects=True)

    # Add Internal Note
    client.post(f"/admin/tickets/{ticket_num}", data={
        "action": "internal_note",
        "note": "Known issue with iOS build 18.2. Escalating to engineering team.",
    }, follow_redirects=True)

    # Post Support Reply
    client.post(f"/admin/tickets/{ticket_num}", data={
        "action": "reply",
        "message": "Hello Alice, our engineering team is investigating this iOS crash.",
    }, follow_redirects=True)

    # Update Status to RESOLVED
    client.post(f"/admin/tickets/{ticket_num}", data={
        "action": "update_status",
        "status": TicketStatus.RESOLVED,
    }, follow_redirects=True)

    with app.app_context():
        t = Ticket.query.filter_by(ticket_number=ticket_num).first()
        assert t.priority == TicketPriority.HIGH
        assert t.assigned_team == SupportTeam.TECHNICAL_SUPPORT
        assert t.status == TicketStatus.RESOLVED
        assert t.resolved_at is not None
        assert len(t.internal_notes) == 1
        assert "Known issue with iOS build" in t.internal_notes[0].note


# ---------------------------------------------------------------------------
# 17. Customer Cannot See Internal Notes
# ---------------------------------------------------------------------------

def test_customer_cannot_see_internal_notes(client, seed_users):
    """Verify internal staff notes never leak into customer HTML or customer API."""
    # Alice creates ticket
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    res = client.post("/api/tickets", json={
        "subject": "Account cancellation query",
        "description": "Want to cancel plan next month",
        "product_service": "Billing",
    })
    ticket_num = res.json["data"]["ticket_number"]

    # Support adds internal note
    client.get("/logout")
    client.post("/login", data={"email": "support@test.com", "password": "password123"})
    client.post(f"/api/admin/tickets/{ticket_num}/notes", json={
        "note": "CONFIDENTIAL: Customer is high-value churn risk, offer 20% discount if asked."
    })

    # Alice views ticket via web and API
    client.get("/logout")
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})

    web_view = client.get(f"/tickets/{ticket_num}")
    assert b"CONFIDENTIAL" not in web_view.data
    assert b"churn risk" not in web_view.data

    api_view = client.get(f"/api/tickets/{ticket_num}")
    assert "internal_notes" not in api_view.json["data"]
    assert "CONFIDENTIAL" not in str(api_view.json)


# ---------------------------------------------------------------------------
# 18. Manual Escalation
# ---------------------------------------------------------------------------

def test_manual_escalation_workflow(client, app, seed_users):
    """Test manual escalation creates Escalation record and updates status."""
    # Create ticket
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    res = client.post("/api/tickets", json={
        "subject": "Data corruption in reports",
        "description": "Monthly revenue numbers show NaN",
        "product_service": "Analytics Engine",
    })
    ticket_num = res.json["data"]["ticket_number"]

    # Support escalates ticket
    client.get("/logout")
    client.post("/login", data={"email": "support@test.com", "password": "password123"})

    esc_res = client.post(f"/admin/tickets/{ticket_num}", data={
        "action": "escalate",
        "target_team": SupportTeam.SENIOR_SUPPORT,
        "reason": "Severe data reporting anomaly requiring senior engineering intervention.",
    }, follow_redirects=True)

    assert esc_res.status_code == 200
    assert b"Ticket successfully escalated" in esc_res.data

    with app.app_context():
        ticket = Ticket.query.filter_by(ticket_number=ticket_num).first()
        assert ticket.status == TicketStatus.ESCALATED
        assert ticket.assigned_team == SupportTeam.SENIOR_SUPPORT
        assert len(ticket.escalations) == 1
        assert "Severe data reporting anomaly" in ticket.escalations[0].reason


# ---------------------------------------------------------------------------
# 19. Customer & 20. Admin Dashboard Statistics from SQLite
# ---------------------------------------------------------------------------

def test_dashboard_live_statistics(client, app, seed_users):
    """Test real SQL aggregate counts on customer and admin dashboards."""
    # Alice creates 2 tickets
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    client.post("/api/tickets", json={
        "subject": "Ticket One", "description": "Description text one", "product_service": "Service A"
    })
    client.post("/api/tickets", json={
        "subject": "Ticket Two", "description": "Description text two", "product_service": "Service B"
    })

    # Check Customer Dashboard API
    cust_stats = client.get("/api/dashboard/customer")
    assert cust_stats.status_code == 200
    assert cust_stats.json["data"]["total_tickets"] == 2
    assert cust_stats.json["data"]["open_tickets"] == 2

    # Support logs in and resolves Ticket One
    client.get("/logout")
    client.post("/login", data={"email": "support@test.com", "password": "password123"})

    with app.app_context():
        t1 = Ticket.query.filter_by(subject="Ticket One").first()
        update_ticket_status(t1, TicketStatus.RESOLVED, "Support")

    # Check Admin Dashboard API
    admin_stats = client.get("/api/dashboard/admin")
    assert admin_stats.status_code == 200
    assert admin_stats.json["data"]["total_tickets"] == 2
    assert admin_stats.json["data"]["resolved_tickets"] == 1
    assert admin_stats.json["data"]["open_tickets"] == 1


# ---------------------------------------------------------------------------
# 21. Nonexistent Ticket 404 & 22. Unauthenticated Redirects
# ---------------------------------------------------------------------------

def test_error_and_authorization_guards(client):
    """Test 404 on invalid ticket number and login redirects for unauthenticated users."""
    # Unauthenticated access to /submit-complaint -> redirect to login
    submit_redirect = client.get("/submit-complaint")
    assert submit_redirect.status_code == 302
    assert "/login" in submit_redirect.headers["Location"]

    # Login and query invalid ticket -> 404 Not Found
    client.post("/register", data={
        "name": "Test User",
        "email": "tester@test.com",
        "password": "password123",
        "confirm_password": "password123",
        "role": "customer",
    })
    client.post("/login", data={
        "email": "tester@test.com",
        "password": "password123",
    })
    invalid_ticket = client.get("/tickets/TKT-2026-999999")
    assert invalid_ticket.status_code == 404
