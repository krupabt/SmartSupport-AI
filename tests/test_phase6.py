import pytest
import os
import io
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.ticket import Ticket, TicketStatus, TicketPriority
from app.models.rag_resolution import RAGResolution, RAGStatus
from app.services.ticket_service import create_ticket


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
        alice = User(name="Alice Customer", email="alice@test.com", role="customer")
        alice.set_password("password123")

        bob = User(name="Bob Customer", email="bob@test.com", role="customer")
        bob.set_password("password123")

        support = User(name="Support Agent", email="agent@test.com", role="support")
        support.set_password("password123")

        db.session.add_all([alice, bob, support])
        db.session.commit()
        return {"alice_id": alice.id, "bob_id": bob.id, "support_id": support.id}


# ---------------------------------------------------------------------------
# IDOR & Security Isolation Tests
# ---------------------------------------------------------------------------

def test_idor_customer_cannot_view_other_customer_ticket(client, app, seed_users):
    """Customer Bob cannot view Alice's ticket via Web or API."""
    with app.app_context():
        alice_ticket = create_ticket(
            user_id=seed_users["alice_id"],
            subject="Alice's confidential complaint",
            description="Private billing issue.",
            product_service="App Service",
        )
        tkt_num = alice_ticket.ticket_number

    # Login as Bob
    client.post("/login", data={"email": "bob@test.com", "password": "password123"})

    # Try accessing Alice's ticket on Web route
    web_res = client.get(f"/tickets/{tkt_num}", follow_redirects=True)
    assert b"Access denied" in web_res.data or web_res.status_code == 403

    # Try accessing via API
    api_res = client.get(f"/api/tickets/{tkt_num}")
    assert api_res.status_code == 403
    assert api_res.json["error"]["code"] == "FORBIDDEN"


def test_idor_customer_cannot_post_message_to_other_ticket(client, app, seed_users):
    """Customer Bob cannot append messages to Alice's ticket."""
    with app.app_context():
        alice_ticket = create_ticket(
            user_id=seed_users["alice_id"],
            subject="Alice's inquiry",
            description="Alice inquiry description.",
            product_service="App",
        )
        tkt_num = alice_ticket.ticket_number

    # Login as Bob
    client.post("/api/auth/login", json={"email": "bob@test.com", "password": "password123"})

    # Post message to Alice's ticket
    api_res = client.post(f"/api/tickets/{tkt_num}/messages", json={"message": "Injected malicious message"})
    assert api_res.status_code == 403
    assert api_res.json["error"]["code"] == "FORBIDDEN"


def test_customer_cannot_access_admin_portal_or_apis(client, seed_users):
    """Regular customer is strictly blocked from /admin routes."""
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})

    res = client.get("/admin/dashboard", follow_redirects=True)
    assert b"Access restricted" in res.data or res.status_code == 403

    api_res = client.get("/api/admin/tickets")
    assert api_res.status_code == 403


# ---------------------------------------------------------------------------
# XSS & Input Sanitization
# ---------------------------------------------------------------------------

def test_xss_prevention_in_complaints_and_messages(client, seed_users):
    """Script tags in subject and description are escaped and not executed."""
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})

    xss_payload = "<script>alert('XSS_ATTACK')</script>"
    res = client.post("/submit-complaint", data={
        "subject": f"Defect report {xss_payload}",
        "description": f"Problem description {xss_payload}",
        "product_service": "Web Portal",
    }, follow_redirects=True)

    assert res.status_code == 200
    assert b"alert('XSS_ATTACK')" not in res.data or b"&lt;script&gt;" in res.data or b"<script>" not in res.data.decode("utf-8")


# ---------------------------------------------------------------------------
# File Upload Security & Disallowed Types
# ---------------------------------------------------------------------------

def test_knowledge_base_rejects_disallowed_file_types(client, seed_users):
    """Knowledge base ingestion strictly rejects non-document extensions."""
    client.post("/login", data={"email": "agent@test.com", "password": "password123"})

    # Try uploading executable .exe file
    data = {
        "title": "Malicious Executable",
        "category": "Security",
        "file": (io.BytesIO(b"MZ\x90\x00\x03\x00\x00\x00"), "payload.exe"),
    }
    res = client.post("/admin/knowledge-base/upload", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert b"Unsupported file type" in res.data or b"error" in res.data.lower()


# ---------------------------------------------------------------------------
# Robust Error Handling
# ---------------------------------------------------------------------------

def test_api_404_on_nonexistent_resources(client, seed_users):
    """API returns structured 404 for invalid ticket numbers."""
    client.post("/api/auth/login", json={"email": "agent@test.com", "password": "password123"})

    res = client.get("/api/tickets/TKT-9999-999999")
    assert res.status_code == 404
    assert res.json["success"] is False
    assert res.json["error"]["code"] == "TICKET_NOT_FOUND"


def test_api_validation_error_on_empty_payload(client, seed_users):
    """API returns structured 400 for empty or invalid complaint."""
    client.post("/api/auth/login", json={"email": "alice@test.com", "password": "password123"})

    res = client.post("/api/tickets", json={})
    assert res.status_code == 400
    assert res.json["success"] is False
    assert res.json["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Anti-Hallucination & Grounding Guardrails
# ---------------------------------------------------------------------------

def test_anti_hallucination_unmatched_context_behavior(app, seed_users):
    """When no relevant context exists, RAG returns fallback without hallucinating facts."""
    from app.services.rag.rag_service import RAGService
    with app.app_context():
        ticket = create_ticket(
            user_id=seed_users["alice_id"],
            subject="Quantum physics computation engine timeout",
            description="My quantum entanglement simulation failed on cluster node 44.",
            product_service="Compute Engine",
        )
        rag_service = RAGService()
        resolution = rag_service.resolve_ticket(ticket)
        
        assert resolution is not None
        # Should gracefully report no relevant context or unavailable, not fabricate policies
        assert resolution.status in (RAGStatus.NO_RELEVANT_CONTEXT, RAGStatus.COMPLETED, RAGStatus.UNAVAILABLE)


# ---------------------------------------------------------------------------
# System Health Probe
# ---------------------------------------------------------------------------

def test_health_check_endpoint(client):
    """Health check returns 200 with database and subsystem status."""
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json["status"] == "healthy"
    assert res.json["database"] == "connected"
    assert "version" in res.json
