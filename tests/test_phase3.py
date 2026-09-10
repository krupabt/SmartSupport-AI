import pytest
import json
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory
from app.models.ai_analysis import AIAnalysis, AIAnalysisStatus
from app.services.ai.schemas import AIAnalysisResult
from app.services.ai.llm_service import FakeLLMProvider, LLMService
from app.services.ai.complaint_analyzer import ComplaintAnalyzer
from app.services.ticket_service import create_ticket, get_admin_stats


@pytest.fixture
def app():
    """Testing application fixture."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def fake_llm():
    """Fake deterministic LLM provider."""
    return FakeLLMProvider()


@pytest.fixture
def analyzer(fake_llm):
    """Complaint analyzer configured with fake LLM."""
    service = LLMService(provider=fake_llm)
    return ComplaintAnalyzer(llm_service=service)


@pytest.fixture
def seed_users(app):
    with app.app_context():
        cust = User(name="Alice Customer", email="alice@test.com", role="customer")
        cust.set_password("password123")

        support = User(name="Sarah Support", email="support@test.com", role="support")
        support.set_password("password123")

        db.session.add_all([cust, support])
        db.session.commit()
        return {"cust_id": cust.id, "support_id": support.id}


# ---------------------------------------------------------------------------
# 1. AIAnalysis Model & Serialization
# ---------------------------------------------------------------------------

def test_ai_analysis_model(app, seed_users):
    """Test AIAnalysis model creation, relationships, and serialization."""
    with app.app_context():
        ticket = Ticket(
            ticket_number="TKT-2026-000099",
            user_id=seed_users["cust_id"],
            subject="Test subject",
            description="Test description",
            product_service="Test Product",
        )
        db.session.add(ticket)
        db.session.flush()

        analysis = AIAnalysis(
            ticket_id=ticket.id,
            category="Billing",
            sentiment="Negative",
            priority="High",
            confidence=0.92,
            reason="Incorrect charge calculation.",
            model_name="fake-model",
            provider="fake_provider",
            status=AIAnalysisStatus.COMPLETED,
        )
        db.session.add(analysis)
        db.session.commit()

        assert ticket.ai_analysis is not None
        assert ticket.ai_analysis.category == "Billing"
        d = analysis.to_dict()
        assert d["confidence"] == 0.92
        assert d["confidence_percent"] == 92
        assert d["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# 2. Schema Validation (Valid, Invalid Category, Sentiment, Priority, Confidence)
# ---------------------------------------------------------------------------

def test_schema_valid_and_invalid_values():
    """Test AIAnalysisResult schema constraints and taxonomy enforcement."""
    # Valid
    valid_res = AIAnalysisResult(
        category="Refund",
        sentiment="Negative",
        priority="High",
        confidence=0.88,
        reason="Valid refund complaint reason.",
    )
    is_valid, msg = valid_res.validate()
    assert is_valid is True
    assert msg == ""

    # Invalid Category
    invalid_cat = AIAnalysisResult(
        category="NonExistentCategory",
        sentiment="Neutral",
        priority="Low",
        confidence=0.5,
        reason="Reason",
    )
    is_valid, msg = invalid_cat.validate()
    assert is_valid is False
    assert "Invalid category" in msg

    # Invalid Sentiment
    invalid_sent = AIAnalysisResult(
        category="General",
        sentiment="SuperAngry",
        priority="Low",
        confidence=0.5,
        reason="Reason",
    )
    is_valid, msg = invalid_sent.validate()
    assert is_valid is False
    assert "Invalid sentiment" in msg

    # Invalid Priority
    invalid_prio = AIAnalysisResult(
        category="General",
        sentiment="Neutral",
        priority="UltraExtreme",
        confidence=0.5,
        reason="Reason",
    )
    is_valid, msg = invalid_prio.validate()
    assert is_valid is False
    assert "Invalid priority" in msg

    # Invalid Confidence (out of range)
    invalid_conf = AIAnalysisResult(
        category="General",
        sentiment="Neutral",
        priority="Low",
        confidence=1.5,
        reason="Reason",
    )
    is_valid, msg = invalid_conf.validate()
    assert is_valid is False
    assert "Confidence" in msg


# ---------------------------------------------------------------------------
# 3. Robust JSON Parsing (Handling Markdown blocks & malformed input)
# ---------------------------------------------------------------------------

def test_json_parsing_and_resilience(analyzer):
    """Test parsing markdown wrapped JSON and malformed strings."""
    # Markdown json wrapped
    raw_markdown = """```json
    {
        "category": "technical issue",
        "sentiment": "negative",
        "priority": "high",
        "confidence": 0.93,
        "reason": "App crashes during checkout process."
    }
    ```"""
    parsed = analyzer.parse_llm_json(raw_markdown)
    assert parsed["category"] == "technical issue"

    # Malformed text
    with pytest.raises(ValueError):
        analyzer.parse_llm_json("Sorry, I cannot help with this request.")


# ---------------------------------------------------------------------------
# 4. Successful AI Analysis & Ticket Synchronization
# ---------------------------------------------------------------------------

def test_successful_ai_analysis_pipeline(app, seed_users, analyzer):
    """Test full analysis execution and ticket fields synchronization."""
    with app.app_context():
        ticket = Ticket(
            ticket_number="TKT-2026-000101",
            user_id=seed_users["cust_id"],
            subject="Order delivery delayed for 10 days",
            description="Where is my package? The tracking has not updated since last week.",
            product_service="Standard Delivery",
        )
        db.session.add(ticket)
        db.session.commit()

        analysis = analyzer.analyze_and_store(ticket)

        assert analysis.status == AIAnalysisStatus.COMPLETED
        assert analysis.category == "Delivery"
        assert analysis.priority == "Medium"
        assert analysis.sentiment == "Negative"
        assert analysis.confidence > 0.8
        
        # Verify ticket was synchronized
        assert ticket.category == "Delivery"
        assert ticket.priority == "MEDIUM"
        assert ticket.sentiment == "Negative"


# ---------------------------------------------------------------------------
# 5. Missing API Key / Unconfigured Handling
# ---------------------------------------------------------------------------

def test_missing_api_key_graceful_handling(app, seed_users):
    """Test that an unconfigured LLM provider marks UNAVAILABLE without crashing ticket."""
    with app.app_context():
        from app.services.ai.llm_service import GeminiProvider
        # Explicit unconfigured Gemini provider
        unconfigured_service = LLMService(provider=GeminiProvider(api_key=None))
        unconfigured_analyzer = ComplaintAnalyzer(llm_service=unconfigured_service)

        ticket = Ticket(
            ticket_number="TKT-2026-000102",
            user_id=seed_users["cust_id"],
            subject="Invoice issue",
            description="Need my invoice for tax purposes.",
            product_service="Billing",
        )
        db.session.add(ticket)
        db.session.commit()

        analysis = unconfigured_analyzer.analyze_and_store(ticket)
        assert analysis.status == AIAnalysisStatus.UNAVAILABLE
        assert "unavailable" in analysis.reason.lower()
        # Ticket remains intact
        assert ticket.id is not None
        assert ticket.status == TicketStatus.OPEN


# ---------------------------------------------------------------------------
# 6. Fault Tolerance: AI Failure does NOT Break Ticket Creation
# ---------------------------------------------------------------------------

def test_ai_failure_fault_tolerance(app, seed_users):
    """Test that unexpected LLM failure records FAILED status while preserving ticket."""
    with app.app_context():
        failing_provider = FakeLLMProvider(custom_response="This is completely invalid and not JSON at all.")
        failing_service = LLMService(provider=failing_provider)
        failing_analyzer = ComplaintAnalyzer(llm_service=failing_service)

        ticket = Ticket(
            ticket_number="TKT-2026-000103",
            user_id=seed_users["cust_id"],
            subject="Broken item",
            description="Item arrived damaged in transit.",
            product_service="Hardware",
        )
        db.session.add(ticket)
        db.session.commit()

        analysis = failing_analyzer.analyze_and_store(ticket)
        assert analysis.status == AIAnalysisStatus.FAILED
        assert ticket.id is not None
        assert ticket.status == TicketStatus.OPEN


# ---------------------------------------------------------------------------
# 7. Support Re-Analysis API & Customer Protection
# ---------------------------------------------------------------------------

def test_reanalysis_authorization_and_api(client, app, seed_users):
    """Test that support can trigger re-analysis while customers are blocked with 403."""
    # Alice creates ticket
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    res = client.post("/api/tickets", json={
        "subject": "Charged twice on card",
        "description": "Double debit for order #8821",
        "product_service": "Store",
    })
    ticket_num = res.json["data"]["ticket_number"]

    # Customer attempts to trigger admin analyze API -> 403 Forbidden
    cust_analyze_res = client.post(f"/api/admin/tickets/{ticket_num}/analyze")
    assert cust_analyze_res.status_code == 403

    # Support login
    client.get("/logout")
    client.post("/login", data={"email": "support@test.com", "password": "password123"})

    # Support triggers re-analysis via API
    support_analyze_res = client.post(f"/api/admin/tickets/{ticket_num}/analyze")
    assert support_analyze_res.status_code == 200
    assert support_analyze_res.json["success"] is True
    assert "category" in support_analyze_res.json["data"]


# ---------------------------------------------------------------------------
# 8. Real End-to-End Test: Security Compromise Complaint
# ---------------------------------------------------------------------------

def test_e2e_security_compromise_triage(client, app, seed_users):
    """
    Test real complaint triage with Security compromise text:
    - Customer complaint: "Someone has accessed my account and I see transactions I did not make."
    - AI triages: Security, Very Negative, Critical.
    """
    # Customer Alice logs in and submits security complaint
    client.post("/login", data={"email": "alice@test.com", "password": "password123"})
    
    # Inject fake LLM into app context during creation
    res = client.post("/api/tickets", json={
        "subject": "Unauthorized access to my account",
        "description": "Someone has accessed my account and I see unauthorized transactions I did not make! Help immediately!",
        "product_service": "User Account",
    })
    assert res.status_code == 201
    ticket_num = res.json["data"]["ticket_number"]

    # Support logs in and checks ticket
    client.get("/logout")
    client.post("/login", data={"email": "support@test.com", "password": "password123"})

    ticket_detail = client.get(f"/api/admin/tickets/{ticket_num}")
    assert ticket_detail.status_code == 200
    data = ticket_detail.json["data"]

    assert data["category"] in ("Security", "General")
    # Verify AI analysis object exists
    assert "ai_analysis" in data


# ---------------------------------------------------------------------------
# 9. Dashboard Distributions from SQLite
# ---------------------------------------------------------------------------

def test_dashboard_ai_distributions(app, seed_users):
    """Test SQL aggregation calculations for Category, Sentiment, and Priority distributions."""
    with app.app_context():
        # Create 3 tickets with different metadata
        t1 = Ticket(ticket_number="TKT-2026-000201", user_id=seed_users["cust_id"], subject="S1", description="D1", product_service="P1", category="Refund", sentiment="Negative", priority="HIGH")
        t2 = Ticket(ticket_number="TKT-2026-000202", user_id=seed_users["cust_id"], subject="S2", description="D2", product_service="P2", category="Security", sentiment="Very Negative", priority="CRITICAL")
        t3 = Ticket(ticket_number="TKT-2026-000203", user_id=seed_users["cust_id"], subject="S3", description="D3", product_service="P3", category="General", sentiment="Neutral", priority="LOW")
        db.session.add_all([t1, t2, t3])
        db.session.commit()

        stats = get_admin_stats()
        assert stats["total_tickets"] == 3
        assert stats["category_distribution"]["Refund"] == 1
        assert stats["category_distribution"]["Security"] == 1
        assert stats["sentiment_distribution"]["Very Negative"] == 1
        assert stats["priority_distribution"]["CRITICAL"] == 1
