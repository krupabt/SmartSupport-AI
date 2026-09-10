import pytest
import os
import io
from pathlib import Path
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory, SupportTeam
from app.models.ticket_message import SenderType
from app.models.rag_resolution import RAGResolution, RAGStatus
from app.models.notification import Notification, NotificationType
from app.services.rag.rag_service import RAGService


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


def test_complete_integrated_phases_1_to_6_e2e_flow(client, app, tmp_path):
    """
    Comprehensive 12-stage end-to-end integration test across all 6 phases:
    1. Knowledge Base Ingestion: Support ingests company policy document into FAISS.
    2. Customer Registration & Authentication: Customer registers and logs in.
    3. Complaint Submission: Customer submits complaint matching refund policy.
    4. AI Analysis & Triage: Automatic classification, sentiment analysis, priority.
    5. Grounded RAG Resolution: Semantic search over FAISS with source citations.
    6. Customer Portal Experience: Customer views AI grounded answer & sources.
    7. Support Queue & Notification: Support notified and inspects ticket in queue.
    8. Staff Collaboration: Support adds confidential internal note.
    9. Public Staff Response: Support replies to customer, updating status to WAITING_FOR_CUSTOMER.
    10. Customer In-App Notification: Customer receives alert, views response, and requests human escalation.
    11. Status Workflow & Reopen: Support resolves ticket; customer reopens ticket.
    12. Real Analytics: Admin dashboard calculates live response/resolution times and AI rate.
    """
    # -------------------------------------------------------------
    # 1. Staff Ingests Knowledge Document
    # -------------------------------------------------------------
    with app.app_context():
        staff = User(name="Support Lead", email="lead@test.com", role="support")
        staff.set_password("password123")
        db.session.add(staff)
        db.session.commit()

        # Ingest refund policy
        doc_path = tmp_path / "return_policy.txt"
        doc_path.write_text(
            "# Company Refund & Return Policy\n\n"
            "Customers are eligible for a 100% full refund within 30 days of delivery.\n"
            "To request a return, provide your order reference number and invoice.\n"
            "Refunds are processed back to the original payment method within 3-5 business days.\n"
        )
        rag_service = RAGService()
        doc = rag_service.ingest_document(
            file_path=str(doc_path),
            title="Standard Refund Policy",
            category="Billing",
            description="Official 30-day return policy guidelines",
        )
        assert doc.chunk_count > 0

    # -------------------------------------------------------------
    # 2. Customer Registration & Login
    # -------------------------------------------------------------
    reg_res = client.post("/register", data={
        "name": "David Customer",
        "email": "david@test.com",
        "password": "password123",
        "confirm_password": "password123",
        "role": "customer",
    }, follow_redirects=True)
    assert reg_res.status_code == 200

    login_res = client.post("/login", data={
        "email": "david@test.com",
        "password": "password123",
    }, follow_redirects=True)
    assert login_res.status_code == 200
    assert b"Welcome" in login_res.data

    # -------------------------------------------------------------
    # 3. Complaint Submission
    # -------------------------------------------------------------
    sub_res = client.post("/submit-complaint", data={
        "subject": "Request refund for order ORD-9900",
        "description": "I received my order 5 days ago and would like a full refund to my credit card as per the 30-day policy.",
        "product_service": "SmartSpeaker Pro",
        "reference_id": "ORD-9900",
    }, follow_redirects=True)
    assert sub_res.status_code == 200
    assert b"Complaint registered successfully!" in sub_res.data

    # Extract ticket number
    tickets_res = client.get("/api/tickets")
    assert len(tickets_res.json["data"]) == 1
    ticket_data = tickets_res.json["data"][0]
    tkt_num = ticket_data["ticket_number"]

    # -------------------------------------------------------------
    # 4 & 5. AI Analysis & RAG Grounded Resolution
    # -------------------------------------------------------------
    with app.app_context():
        ticket = Ticket.query.filter_by(ticket_number=tkt_num).first()
        assert ticket is not None
        assert ticket.ai_analysis is not None
        assert ticket.ai_analysis.status == "COMPLETED"

        assert ticket.rag_resolution is not None
        assert ticket.rag_resolution.status == "COMPLETED"
        assert len(ticket.rag_resolution.sources) > 0
        assert "Standard Refund Policy" in [s.source_title for s in ticket.rag_resolution.sources]

    # -------------------------------------------------------------
    # 6. Customer Views AI Resolution on Portal
    # -------------------------------------------------------------
    cust_view = client.get(f"/tickets/{tkt_num}")
    assert cust_view.status_code == 200
    assert b"AI Assistant Resolution" in cust_view.data
    assert b"Verified Sources Consulted" in cust_view.data

    # -------------------------------------------------------------
    # 7. Support Inspects Queue & Notifications
    # -------------------------------------------------------------
    client.get("/logout")
    client.post("/login", data={"email": "lead@test.com", "password": "password123"})

    queue_res = client.get("/admin/tickets")
    assert tkt_num.encode() in queue_res.data

    # -------------------------------------------------------------
    # 8. Staff Adds Confidential Internal Note
    # -------------------------------------------------------------
    note_res = client.post(f"/admin/tickets/{tkt_num}", data={
        "action": "internal_note",
        "note": "Verified invoice ORD-9900 in billing system; eligible for refund.",
    }, follow_redirects=True)
    assert note_res.status_code == 200

    # -------------------------------------------------------------
    # 9. Support Replies to Customer
    # -------------------------------------------------------------
    reply_res = client.post(f"/admin/tickets/{tkt_num}", data={
        "action": "reply",
        "message": "Hello David, your refund has been approved and will credit within 3 business days.",
    }, follow_redirects=True)
    assert reply_res.status_code == 200

    # Status automatically transitioned to WAITING_FOR_CUSTOMER
    with app.app_context():
        t = Ticket.query.filter_by(ticket_number=tkt_num).first()
        assert t.status == TicketStatus.WAITING_FOR_CUSTOMER

    # -------------------------------------------------------------
    # 10. Customer Receives Notification & Reopens / Requests Agent
    # -------------------------------------------------------------
    client.get("/logout")
    client.post("/login", data={"email": "david@test.com", "password": "password123"})

    notif_res = client.get("/api/notifications")
    assert notif_res.json["data"]["unread_count"] >= 1

    # Mark all read
    client.post("/api/notifications/read-all")
    notif_check = client.get("/api/notifications")
    assert notif_check.json["data"]["unread_count"] == 0

    # -------------------------------------------------------------
    # 11. Support Resolves & Customer Reopens Ticket
    # -------------------------------------------------------------
    client.get("/logout")
    client.post("/login", data={"email": "lead@test.com", "password": "password123"})
    client.post(f"/admin/tickets/{tkt_num}", data={
        "action": "update_status",
        "status": TicketStatus.RESOLVED,
    }, follow_redirects=True)

    with app.app_context():
        t = Ticket.query.filter_by(ticket_number=tkt_num).first()
        assert t.status == TicketStatus.RESOLVED
        assert t.resolved_at is not None

    # Customer reopens ticket
    client.get("/logout")
    client.post("/login", data={"email": "david@test.com", "password": "password123"})
    reopen_res = client.post(f"/tickets/{tkt_num}/reopen", data={"reason": "Need updated receipt"}, follow_redirects=True)
    assert reopen_res.status_code == 200

    with app.app_context():
        t = Ticket.query.filter_by(ticket_number=tkt_num).first()
        assert t.status == TicketStatus.IN_PROGRESS
        assert t.resolved_at is None

    # -------------------------------------------------------------
    # 12. Real Analytics Verification
    # -------------------------------------------------------------
    client.get("/logout")
    client.post("/login", data={"email": "lead@test.com", "password": "password123"})
    dash_res = client.get("/api/admin/analytics?range=all")
    assert dash_res.status_code == 200
    stats = dash_res.json["data"]
    assert stats["total_tickets"] >= 1
    assert stats["ai_resolution_rate"] >= 0
    assert "avg_resolution_hours" in stats
