# AI Customer Support & Complaint Resolution System

An enterprise-grade, production-hardened AI Customer Support & Complaint Resolution web platform. The system combines multi-factor AI complaint classification, dense vector semantic search using Sentence Transformers and FAISS, grounded Retrieval-Augmented Generation (RAG) with policy citations, automated intelligent ticket escalation, support specialist collaboration workflows, immutable audit trails, and live database analytics.

---

## 🏗️ System Architecture

```
                               ┌────────────────────────┐
                               │   Customer Complaint   │
                               │     (Web or API)       │
                               └───────────┬────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │   Flask Core Backend   │
                               │   (Auth, RBAC, DB)     │
                               └───────────┬────────────┘
                                           │
             ┌─────────────────────────────┴─────────────────────────────┐
             │                                                           │
             ▼                                                           ▼
┌─────────────────────────┐                                 ┌─────────────────────────┐
│   AI Complaint Triage   │                                 │   RAG Retrieval Engine  │
│  (Category, Sentiment,  │                                 │ (Sentence Transformers  │
│    Priority, Risk)      │                                 │  + FAISS Vector Store)  │
└────────────┬────────────┘                                 └────────────┬────────────┘
             │                                                           │
             └─────────────────────────────┬─────────────────────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │   LLM Grounded Answer  │
                               │   + Source Citations   │
                               └───────────┬────────────┘
                                           │
                                           ▼
                               ┌────────────────────────┐
                               │  Escalation Engine     │
                               │ (Deterministic Rules & │
                               │   Target Team Suggest) │
                               └───────────┬────────────┘
                                           │
                 ┌─────────────────────────┴─────────────────────────┐
                 │                                                   │
                 ▼                                                   ▼
┌─────────────────────────────────┐                 ┌─────────────────────────────────┐
│   Customer Portal Experience    │                 │    Support Operations Center    │
│ • Grounded Policy Resolution    │                 │ • Priority Queue & Filters      │
│ • Source Document Citations     │                 │ • Internal Staff Notes          │
│ • "Request Human Agent" Action  │                 │ • Public Replies to Customer    │
│ • Reopen Resolved Tickets       │                 │ • Reassignment & Escalation     │
│ • Real-time In-App Alerts       │                 │ • Immutable Activity Audit Trail│
└─────────────────────────────────┘                 └─────────────────────────────────┘
```

---

## 🚀 Key Features

### 1. Intelligent AI Complaint Triage
- Multi-factor complaint classification across 10 categories (Billing, Payment, Refund, Delivery, Technical Issue, Product Issue, Account, Subscription, Security, General).
- Real-time sentiment polarity assessment (`Positive`, `Neutral`, `Negative`, `Very Negative`).
- Urgency-based priority scoring (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).

### 2. Verified RAG Knowledge Base & Vector Store
- **Multi-Format Ingestion:** Ingests `.txt`, `.md`, `.pdf` (PyMuPDF page-aware extraction), and `.docx` files.
- **Local Dense Embeddings:** Integrated `sentence-transformers/all-MiniLM-L6-v2` generating 384-dimensional unit-normalized dense vectors with **zero external embedding API costs**.
- **FAISS Vector Index:** Cosine similarity retrieval (`IndexFlatIP`) with local persistence and NumPy fallback.
- **Anti-Hallucination Guardrails:** System prompts restrict responses strictly to retrieved knowledge chunks. If no matching policy is found, the system outputs `NO_RELEVANT_CONTEXT` and flags the ticket for human escalation rather than fabricating policies.
- **Source Citations:** Every resolution links back to specific document titles, filenames, page numbers, match scores, and verbatim excerpts.

### 3. Intelligent Ticket Resolution & Escalation Engine
- **Deterministic Escalation Rules:**
  - `CRITICAL` Priority complaints.
  - Security / Privacy compromise risks.
  - Severe negative sentiment on high-urgency issues.
  - Grounded RAG confidence falling below threshold (default 0.60).
  - Explicit customer request for human agent assistance.
- **Smart Department Routing:** Heuristic assignment to specialized departments (`Billing Support`, `Technical Support`, `Delivery Support`, `Account Support`, `Senior Support`).

### 4. Support Agent Collaboration & State Workflow
- Strict ticket lifecycle state transitions (`OPEN` → `IN_PROGRESS` → `WAITING_FOR_CUSTOMER` → `RESOLVED` → `CLOSED` → `REOPENED`).
- Public threaded support responses and private internal staff notes (`InternalNote`).
- Customer and staff ticket reopening workflows.

### 5. Immutable Audit Logging & In-App Notifications
- Complete timeline tracking (`TicketAuditLog`) for all lifecycle events, status changes, reassignments, notes, and replies.
- Role-isolated in-app notifications (`Notification`) with unread counters and live mark-as-read controls.

### 6. Production Hardening & Security
- **IDOR Protection:** Ownership enforcement ensuring customers can only access their own tickets and messages.
- **XSS Sanitization:** Automatic template escaping preventing script injection in subjects, complaints, and notes.
- **File Upload Security:** Disallowed extension rejection, MIME verification, path traversal prevention, and 16MB file size limits.
- **Real SQLite Database Analytics:** Live operational statistics calculated via SQLite queries (Avg Response Time, Avg Resolution Time, SLA compliance, AI Resolution Rate) with zero mock or fake data.

---

## 🛠️ Technology Stack

- **Backend:** Python 3.11+ / 3.12, Flask 3.1.0, Werkzeug 3.1.3
- **Database & ORM:** SQLite 3, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.0.36
- **AI / LLM Integration:** Google Gemini SDK (`google-generativeai`), OpenAI SDK, Modular `LLMService` Provider Abstraction
- **Vector Retrieval & RAG:** `sentence-transformers` (all-MiniLM-L6-v2), `faiss-cpu`, `numpy`, `PyMuPDF` (fitz), `python-docx`
- **Frontend UI:** HTML5, CSS3, JavaScript (ES6+), Bootstrap 5.3.3, Bootstrap Icons 1.11.3
- **Testing:** Pytest 9.1.1 (**70/70 automated unit, integration, and security tests passing**)

---

## 📂 Project Structure

```
SmartSupport AI/
├── app/
│   ├── __init__.py                # Application factory (create_app), blueprints, error handlers
│   ├── config.py                  # Development, Testing, Production configurations
│   ├── extensions.py              # SQLAlchemy extension
│   │
│   ├── models/                    # SQLAlchemy database models
│   │   ├── __init__.py
│   │   ├── user.py                # User model with Werkzeug password hashing & RBAC
│   │   ├── ticket.py              # Ticket model, lifecycle enums, relationships
│   │   ├── ticket_message.py      # Conversation messages & sender types
│   │   ├── internal_note.py       # Private staff collaboration notes
│   │   ├── escalation.py          # Automatic & manual escalation records
│   │   ├── audit_log.py           # Immutable activity audit log
│   │   ├── notification.py        # In-app notifications
│   │   ├── ai_analysis.py         # AI complaint triage entities
│   │   ├── knowledge_doc.py       # KnowledgeDocument & KnowledgeChunk models
│   │   └── rag_resolution.py      # Grounded RAGResolution & RAGSource citations
│   │
│   ├── services/                  # Business logic layer
│   │   ├── __init__.py
│   │   ├── auth_service.py        # Session management & role-based guards
│   │   ├── ticket_service.py      # Ticket lifecycle, replies, reopen, analytics
│   │   ├── escalation_service.py  # Deterministic escalation engine
│   │   ├── notification_service.py# In-app notification creation & read status
│   │   │
│   │   ├── ai/                    # AI classification & LLM provider abstraction
│   │   │   ├── llm_service.py     # GeminiProvider, OpenAIProvider, FakeLLMProvider
│   │   │   ├── complaint_analyzer.py # Structured classification & sentiment
│   │   │   ├── prompts.py         # AI analysis prompts
│   │   │   └── schemas.py         # Validation schemas
│   │   │
│   │   └── rag/                   # RAG knowledge base pipeline
│   │       ├── document_loader.py # Multi-format parser (.txt, .md, .pdf, .docx)
│   │       ├── document_processor.py # Text cleaner & SHA-256 deduplication
│   │       ├── chunker.py         # Recursive token-aware chunker
│   │       ├── embeddings.py      # SentenceTransformer dense vectors
│   │       ├── vector_store.py    # FAISS Cosine Index & NumPy fallback
│   │       ├── retriever.py       # Semantic query builder & retriever
│   │       ├── resolution_generator.py # Grounded generator & citation mapper
│   │       └── rag_service.py     # Master RAG orchestrator
│   │
│   ├── routes/                    # Route controllers
│   │   ├── __init__.py
│   │   ├── main_routes.py         # Web views (Customer portal, Admin hub)
│   │   ├── auth_routes.py         # Authentication views
│   │   └── api_routes.py          # RESTful JSON APIs
│   │
│   ├── templates/                 # Jinja2 HTML templates
│   │   ├── base.html              # Layout, navbar, notifications dropdown
│   │   ├── index.html             # Landing page
│   │   ├── customer/              # Customer portal views
│   │   └── admin/                 # Support & Operations views
│   │
│   └── static/                    # CSS stylesheets & client assets
│
├── tests/                         # Automated test suites (70 tests)
│   ├── test_phase1.py             # Foundation, Auth, UI
│   ├── test_phase2.py             # Ticket management, Notes, Escalation
│   ├── test_phase3.py             # AI Complaint classification & Triage
│   ├── test_phase4.py             # Document Ingestion, FAISS, RAG Grounding
│   ├── test_phase5.py             # Escalation Engine, Status Workflow, Audit, Notifications
│   ├── test_phase6.py             # Security, IDOR, XSS, Uploads, Error handling
│   └── test_e2e_flow.py           # Complete 12-stage customer-to-support lifecycle test
│
├── run.py                         # Application entry point
├── requirements.txt               # Project dependencies
├── .env.example                   # Environment configuration template
└── README.md                      # Project documentation
```

---

## ⚡ Quick Start Guide

### 1. Prerequisites
- Python 3.11 or 3.12
- Git

### 2. Setup Virtual Environment & Install Dependencies
```bash
# Clone the repository
git clone <repository_url>
cd "SmartSupport AI"

# Create and activate virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` as needed:
```ini
FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY=your-secure-random-secret-key-here
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key-here
RAG_SIMILARITY_THRESHOLD=0.25
RAG_TOP_K=5
AI_CONFIDENCE_THRESHOLD=0.70
RAG_CONFIDENCE_THRESHOLD=0.60
AUTO_ESCALATE_CRITICAL=true
AUTO_ESCALATE_SECURITY=true
```

### 4. Run the Application
```bash
python run.py
```
Access the application at: `http://127.0.0.1:5000`

---

## 🧪 Automated Testing

The repository includes a comprehensive 70-test automated suite verifying all layers:

```bash
# Run all tests
pytest -v

# Run specific phase test suite
pytest tests/test_phase5.py -v
pytest tests/test_phase6.py -v
pytest tests/test_e2e_flow.py -v
```

**Test Suite Coverage Summary:**
- `test_phase1.py` (12 tests): Application factory, Auth, RBAC, Sessions.
- `test_phase2.py` (11 tests): Ticket CRUD, Unique sequential IDs, Threading, Isolation.
- `test_phase3.py` (9 tests): AI Classification, Sentiment, Priority, Error resilience.
- `test_phase4.py` (16 tests): Document parsers, SentenceTransformer, FAISS retrieval, Grounding.
- `test_phase5.py` (12 tests): Escalation engine, Status lifecycle, Reopen, Audit trail, Notifications.
- `test_phase6.py` (9 tests): IDOR prevention, XSS protection, Upload verification, API consistency.
- `test_e2e_flow.py` (1 test): Complete 12-stage customer-to-support lifecycle flow.
- **Total: 70 passed, 0 failed (100% pass rate)**.

---

## 🔒 Security & Data Integrity

1. **Authentication & Password Hashing:** User passwords hashed using Werkzeug `scrypt`/`pbkdf2` algorithms.
2. **Strict Authorization & IDOR Guards:** Customer accounts cannot view, modify, or append messages to other users' tickets via browser or REST APIs.
3. **Internal Note Confidentiality:** Support staff internal notes are filtered at the database query level and never transmitted to customer clients.
4. **XSS & Injection Protection:** All user inputs in templates are sanitized through Jinja2 auto-escaping.
5. **Safe File Processing:** Knowledge base file uploads enforce strict extension checks, safe filename transformations, and isolated storage outside public static directories.
6. **No Fake Metrics:** All operational dashboards, response durations, resolution metrics, and SLA rates are computed dynamically via SQL aggregate queries from real SQLite database records.

---

## 📜 License
This project is licensed under the MIT License.
