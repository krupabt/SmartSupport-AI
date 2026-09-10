import pytest
import os
import json
import numpy as np
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.ticket import Ticket, TicketCategory, TicketPriority, TicketStatus
from app.models.knowledge_doc import KnowledgeDocument, KnowledgeChunk, DocumentStatus
from app.models.rag_resolution import RAGResolution, RAGSource, RAGStatus
from app.services.rag.document_loader import DocumentLoader
from app.services.rag.document_processor import DocumentProcessor
from app.services.rag.chunker import TextChunker
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.vector_store import VectorStore
from app.services.rag.retriever import RAGRetriever
from app.services.rag.resolution_generator import ResolutionGenerator
from app.services.rag.rag_service import RAGService
from app.services.ai.llm_service import FakeLLMProvider, LLMService
from app.services.ticket_service import create_ticket


@pytest.fixture
def app(tmp_path):
    """Testing application fixture with temporary vector store and uploads path."""
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

        db.session.add_all([cust, support])
        db.session.commit()
        return {"cust_id": cust.id, "support_id": support.id}


@pytest.fixture
def sample_text_file(tmp_path):
    f = tmp_path / "refund_policy.txt"
    f.write_text(
        "# Refund Policy\n\n"
        "Customers can request a 100% full refund within 14 calendar days of purchase.\n"
        "Between 15 and 30 days, customers receive store credit only.\n"
        "Refunds take 3 to 5 business days for credit cards.\n",
        encoding="utf-8"
    )
    return str(f)


@pytest.fixture
def sample_markdown_file(tmp_path):
    f = tmp_path / "shipping_policy.md"
    f.write_text(
        "# Shipping and Delivery Policy\n\n"
        "Standard delivery takes 3 to 5 business days.\n"
        "Express priority shipping takes 1 to 2 business days.\n"
        "Lost parcels are refunded or replaced within 7 business days.\n",
        encoding="utf-8"
    )
    return str(f)


# ---------------------------------------------------------------------------
# 1. Document Loaders & Processors Tests
# ---------------------------------------------------------------------------

def test_document_loader_txt(sample_text_file):
    pages = DocumentLoader.load(sample_text_file)
    assert len(pages) == 1
    assert "100% full refund" in pages[0][0]
    assert pages[0][1] == 1


def test_document_loader_markdown(sample_markdown_file):
    pages = DocumentLoader.load(sample_markdown_file)
    assert len(pages) == 1
    assert "Express priority shipping" in pages[0][0]
    assert pages[0][1] == 1


def test_document_loader_invalid_extension(tmp_path):
    f = tmp_path / "file.xyz"
    f.write_text("Hello World", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported document format"):
        DocumentLoader.load(str(f))


def test_document_loader_nonexistent_file():
    with pytest.raises(FileNotFoundError):
        DocumentLoader.load("non_existent_file_path.pdf")


def test_document_processor_clean_and_hash():
    raw_text = "  # Title \n\n Some text with   irregular    spaces. \n"
    cleaned = DocumentProcessor.clean_text(raw_text)
    assert "Some text with irregular spaces." in cleaned

    h1 = DocumentProcessor.compute_hash("Test document content")
    h2 = DocumentProcessor.compute_hash("Test document content")
    h3 = DocumentProcessor.compute_hash("Different document content")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


# ---------------------------------------------------------------------------
# 2. Text Chunker Tests
# ---------------------------------------------------------------------------

def test_text_chunker_basic():
    chunker = TextChunker(chunk_size=200, chunk_overlap=40)
    pages = [(
        "This is paragraph one explaining the refund policy terms in detail. " * 3 + "\n\n" +
        "This is paragraph two explaining billing disputes and credit card charges. " * 3,
        1
    )]
    chunks = chunker.chunk_document_pages(pages)
    assert len(chunks) > 1
    for chunk_text, page_num in chunks:
        assert len(chunk_text) > 0
        assert page_num == 1


def test_text_chunker_multipage():
    chunker = TextChunker(chunk_size=150, chunk_overlap=30)
    pages = [
        ("First page content explaining terms and initial conditions.", 1),
        ("Second page content explaining termination and dispute resolution.", 2),
    ]
    chunks = chunker.chunk_document_pages(pages)
    assert len(chunks) >= 2
    page_numbers = [p for _, p in chunks]
    assert 1 in page_numbers
    assert 2 in page_numbers


# ---------------------------------------------------------------------------
# 3. Embedding Service & Vector Store Tests
# ---------------------------------------------------------------------------

def test_embedding_service_dimensions():
    service = EmbeddingService()
    emb = service.embed_query("How do I request a refund?")
    assert isinstance(emb, (list, np.ndarray))
    assert len(emb) == 384
    # Check normalized vector
    norm = np.linalg.norm(emb)
    assert pytest.approx(norm, 0.01) == 1.0


def test_embedding_service_batch():
    service = EmbeddingService()
    texts = [
        "Refund policy covers 14 days.",
        "Shipping takes 3 to 5 business days.",
        "Account password reset instructions.",
    ]
    embeddings = service.embed_documents(texts)
    assert len(embeddings) == 3
    assert len(embeddings[0]) == 384


def test_vector_store_indexing_and_search(tmp_path):
    store_dir = str(tmp_path / "vstore_test")
    vstore = VectorStore(storage_path=store_dir)

    service = EmbeddingService()
    docs = [
        {"chunk_id": 1, "document_id": 10, "chunk_index": 1, "content": "Refunds are processed within 14 days to original payment.", "document_title": "Refund Policy", "filename": "refund.txt", "category": "Billing", "page_number": 1},
        {"chunk_id": 2, "document_id": 10, "chunk_index": 2, "content": "After 30 days products cannot be returned.", "document_title": "Refund Policy", "filename": "refund.txt", "category": "Billing", "page_number": 1},
        {"chunk_id": 3, "document_id": 20, "chunk_index": 1, "content": "Express shipping delivers in 1-2 business days via FedEx.", "document_title": "Shipping Policy", "filename": "shipping.txt", "category": "Logistics", "page_number": 1},
    ]
    texts = [d["content"] for d in docs]
    embeddings = service.embed_documents(texts)

    vstore.add_chunks(docs, embeddings)
    assert vstore.count() == 3

    # Search for refund query
    query_vec = service.embed_query("Can I get money back for my purchase?")
    results = vstore.search(query_vec, top_k=2)
    assert len(results) > 0
    top_chunk = results[0]
    assert "Refund" in top_chunk.document_title
    assert top_chunk.similarity_score >= 0.0

    # Test delete document
    vstore.delete_document(10)
    assert vstore.count() == 1

    # Reload from disk
    vstore_reloaded = VectorStore(storage_path=store_dir)
    assert vstore_reloaded.count() == 1


# ---------------------------------------------------------------------------
# 4. RAG Retriever Tests
# ---------------------------------------------------------------------------

def test_rag_retriever_query_construction():
    retriever = RAGRetriever(
        vector_store=VectorStore(),
        embedding_service=EmbeddingService(),
    )
    query = retriever.build_query(
        subject="Delay in delivery",
        description="My package has not arrived after 6 days.",
        category=TicketCategory.DELIVERY,
        product_service="Smart Watch",
    )
    assert "Delay in delivery" in query
    assert "Smart Watch" in query
    assert "Delivery" in query


# ---------------------------------------------------------------------------
# 5. Resolution Generator & Anti-Hallucination Tests
# ---------------------------------------------------------------------------

def test_resolution_generator_with_context():
    fake_llm = FakeLLMProvider()
    generator = ResolutionGenerator(llm_service=LLMService(provider=fake_llm))

    from app.services.rag.schemas import RetrievedChunk
    retrieved = [
        RetrievedChunk(
            chunk_id=1,
            document_id=10,
            chunk_index=1,
            content="Customers are entitled to a full refund within 14 calendar days of purchase.",
            document_title="Refund Policy",
            filename="refund.txt",
            category="Billing",
            similarity_score=0.88,
            page_number=1,
        )
    ]

    result = generator.generate_resolution(
        subject="Refund Request",
        description="I want a refund for my order.",
        product_service="Electronics",
        reference_id="ORD-1234",
        chunks=retrieved,
    )

    assert result.status == RAGStatus.COMPLETED
    assert len(result.sources) == 1
    assert result.sources[0].source_title == "Refund Policy"
    assert result.sources[0].page_number == 1
    assert result.confidence > 0.5
    assert not result.needs_escalation


def test_resolution_generator_no_context():
    fake_llm = FakeLLMProvider()
    generator = ResolutionGenerator(llm_service=LLMService(provider=fake_llm))

    result = generator.generate_resolution(
        subject="Unknown Hardware Inquiry",
        description="How do I modify the internal capacitor on version 9.2?",
        product_service="Special Hardware",
        reference_id=None,
        chunks=[],  # No chunks retrieved
    )

    assert result.status == RAGStatus.NO_RELEVANT_CONTEXT
    assert result.needs_escalation is True
    assert len(result.sources) == 0
    assert "support team" in result.answer.lower()


# ---------------------------------------------------------------------------
# 6. End-to-End RAG Service Integration
# ---------------------------------------------------------------------------

def test_rag_service_ingest_and_resolve(app, seed_users, sample_text_file):
    with app.app_context():
        rag = RAGService()

        # Ingest document
        doc = rag.ingest_document(
            file_path=sample_text_file,
            title="Standard Refund Policy",
            category="Billing",
            description="Policy governing standard consumer returns",
        )
        assert doc.status == DocumentStatus.ACTIVE
        assert doc.chunk_count >= 1

        # Create ticket
        ticket = create_ticket(
            user_id=seed_users["cust_id"],
            subject="Requesting refund within 5 days",
            description="I purchased the item 5 days ago and need a refund to my credit card.",
            product_service="Smart Speaker",
            category=TicketCategory.BILLING,
        )

        # RAG should have automatically run or can be called explicitly
        resolution = RAGResolution.query.filter_by(ticket_id=ticket.id).first()
        assert resolution is not None
        assert resolution.status == RAGStatus.COMPLETED
        assert len(resolution.sources) >= 1
        assert resolution.sources[0].source_title == "Standard Refund Policy"

        # Check serialization in ticket.to_dict()
        t_dict = ticket.to_dict()
        assert "rag_resolution" in t_dict
        assert t_dict["rag_resolution"]["status"] == RAGStatus.COMPLETED
        assert len(t_dict["rag_resolution"]["sources"]) >= 1


# ---------------------------------------------------------------------------
# 7. Knowledge Base Web Routes & Admin Views
# ---------------------------------------------------------------------------

def test_admin_knowledge_base_routes(client, seed_users, sample_text_file):
    # Support login
    login_res = client.post("/login", data={
        "email": "support@test.com",
        "password": "password123",
    }, follow_redirects=True)
    assert login_res.status_code == 200

    # GET /admin/knowledge-base
    kb_res = client.get("/admin/knowledge-base")
    assert kb_res.status_code == 200
    assert b"Knowledge Base" in kb_res.data

    # POST /admin/knowledge-base/upload
    with open(sample_text_file, "rb") as f:
        upload_res = client.post(
            "/admin/knowledge-base/upload",
            data={
                "file": (f, "refund_policy.txt"),
                "title": "Uploaded Refund Policy",
                "category": "Billing & Payments",
                "description": "Uploaded for testing",
            },
            follow_redirects=True,
            content_type="multipart/form-data",
        )
    assert upload_res.status_code == 200
    assert b"Uploaded Refund Policy" in upload_res.data

    # Check document in database
    doc = KnowledgeDocument.query.filter_by(title="Uploaded Refund Policy").first()
    assert doc is not None
    assert doc.chunk_count >= 1

    # GET /admin/knowledge-base/<doc_id>
    detail_res = client.get(f"/admin/knowledge-base/{doc.id}")
    assert detail_res.status_code == 200
    assert b"Chunk #1" in detail_res.data

    # POST /admin/knowledge-base/<doc_id>/reindex
    reindex_res = client.post(f"/admin/knowledge-base/{doc.id}/reindex", follow_redirects=True)
    assert reindex_res.status_code == 200

    # POST /admin/knowledge-base/rebuild
    rebuild_res = client.post("/admin/knowledge-base/rebuild", follow_redirects=True)
    assert rebuild_res.status_code == 200

    # POST /admin/knowledge-base/<doc_id>/delete
    del_res = client.post(f"/admin/knowledge-base/{doc.id}/delete", follow_redirects=True)
    assert del_res.status_code == 200
    assert db.session.get(KnowledgeDocument, doc.id) is None


# ---------------------------------------------------------------------------
# 8. RAG REST API Endpoints
# ---------------------------------------------------------------------------

def test_rag_rest_apis(client, seed_users, sample_text_file):
    # Support login
    client.post("/login", data={"email": "support@test.com", "password": "password123"})

    # Ingest document first
    rag = RAGService()
    rag.ingest_document(
        file_path=sample_text_file,
        title="Payment & Refund Policy",
        category="Billing",
    )

    # Create ticket
    ticket = create_ticket(
        user_id=seed_users["cust_id"],
        subject="Refund question",
        description="Can I return within 10 days?",
        product_service="Software Sub",
    )

    # GET /api/tickets/<ticket_number>/resolution
    res_api = client.get(f"/api/tickets/{ticket.ticket_number}/resolution")
    assert res_api.status_code == 200
    res_data = res_api.get_json()
    assert res_data["success"] is True
    assert res_data["data"]["status"] == RAGStatus.COMPLETED
    assert len(res_data["data"]["sources"]) >= 1

    # POST /api/tickets/<ticket_number>/resolve (Regenerate)
    regen_api = client.post(f"/api/tickets/{ticket.ticket_number}/resolve")
    assert regen_api.status_code == 200
    regen_data = regen_api.get_json()
    assert regen_data["success"] is True

    # GET /api/admin/knowledge-base
    kb_api = client.get("/api/admin/knowledge-base")
    assert kb_api.status_code == 200
    assert len(kb_api.get_json()["data"]) >= 1

    # POST /api/admin/knowledge-base/rebuild
    reb_api = client.post("/api/admin/knowledge-base/rebuild")
    assert reb_api.status_code == 200
    assert reb_api.get_json()["success"] is True
