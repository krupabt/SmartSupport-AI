# SmartSupport AI

**SmartSupport AI** is an AI-powered customer support and complaint resolution system that leverages Retrieval-Augmented Generation (RAG) to provide grounded, policy-accurate responses from an enterprise knowledge base. It streamlines customer inquiries with multi-factor AI triage, automated priority detection, verified document citations, and intelligent escalation.

---

## 🔗 Live Demo

Live Demo: [Open SmartSupport AI](https://chatgpt.com/c/YOUR_LIVE_DEMO_URL)

> Try the deployed application using the link above.

---

## 🎥 Demo Video

Demo Video: [Watch the SmartSupport AI Demo](https://chatgpt.com/c/YOUR_DEMO_VIDEO_URL)

> A short walkthrough demonstrating user registration, login, complaint submission, AI analysis, RAG-based response generation, and resolution.

---

## ✨ Features

- **User Registration & Login:** Secure authentication with password hashing (`scrypt`/`pbkdf2`), input validation, and Flask session management.
- **Customer Complaint Submission:** Streamlined form allowing customers to submit issues with category details and reference IDs.
- **AI-Based Complaint Analysis:** Multi-factor triage assessing complaint intent, sentiment polarity, and urgency.
- **Complaint Categorization:** Automated routing across Billing, Technical, Product, Delivery, and Security domains.
- **Priority Detection:** Dynamic multi-factor priority matrix calculating `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` urgency.
- **RAG-Based Knowledge Retrieval:** Dense vector similarity search powered by Sentence Transformers and FAISS index.
- **Grounded AI Responses:** Factual, anti-hallucination resolution generator linking directly to verified policy source citations.
- **Complaint Status Tracking:** Real-time customer tracking and lifecycle updates (`OPEN`, `IN_PROGRESS`, `RESOLVED`, `CLOSED`, `REOPENED`).
- **Support & Admin Operations Dashboard:** Live operational analytics, support queue management, internal agent collaboration notes, and knowledge base administration.
- **Intelligent Escalation:** Automatic routing to specialized support teams when information is insufficient, sentiment is severe, or critical security issues are detected.

---

## 🛠️ Tech Stack

- **Backend:** Python 3.11+, Flask 3.1.0, Werkzeug
- **Database & ORM:** SQLite 3, Flask-SQLAlchemy, SQLAlchemy 2.0
- **AI & LLM Integration:** Google Gemini SDK (`google-generativeai`), OpenAI SDK (Modular Provider Abstraction)
- **Vector Retrieval & RAG:** Sentence Transformers (`all-MiniLM-L6-v2`), FAISS (`faiss-cpu`), NumPy, PyMuPDF (`fitz`), `python-docx`
- **Frontend UI:** HTML5, CSS3, JavaScript (ES6+), Bootstrap 5.3.3, Bootstrap Icons
- **Testing:** Pytest (70/70 automated unit, integration, security, and end-to-end tests)

---

## 🔄 How It Works

```
User
  ↓
Login / Register
  ↓
Submit Question or Complaint
  ↓
AI Analysis (Category, Sentiment, Priority)
  ↓
RAG Retrieval (Dense Embeddings + FAISS Semantic Search)
  ↓
Grounded Response (Contextual Solution with Policy Citations)
  ↓
Resolution or Escalation (Direct Answer or Team Escalation)
```

1. **Submission:** Customer registers/logs in and submits a complaint with product and order details.
2. **AI Analysis:** The system analyzes the text to determine category, sentiment, and urgency level.
3. **RAG Retrieval:** Query embeddings are matched against knowledge base chunks indexed in FAISS.
4. **Grounded Resolution:** The LLM synthesizes a response strictly from retrieved context chunks with source citations.
5. **Resolution / Escalation:** High-confidence solutions are presented immediately; complex or low-confidence tickets are escalated to human support teams.

---

## 🚀 How to Run Locally

### 1. Prerequisites
- Python 3.11 or 3.12 installed on your machine
- Git

### 2. Setup and Execution (Windows PowerShell)

```powershell
# Navigate to the project folder
cd "D:\SmartSupport AI"

# Activate the virtual environment
.\venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt

# Run the Flask development server
python run.py
```

### 3. Open the Application
Open your web browser and navigate to:
```
http://127.0.0.1:5000
```
- Access the Login page at `http://127.0.0.1:5000/login`
- Access the Register page at `http://127.0.0.1:5000/register`
- Submit a complaint and view real-time AI triage & RAG resolution.

---

## 🔐 Environment Variables

Sensitive configuration values and API keys are stored in a `.env` file in the root directory. **Never commit the `.env` file to GitHub.** The `.gitignore` file is pre-configured to ignore `.env`.

Create a `.env` file in the project root:

```ini
# Flask Configuration
FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY=your-secure-random-secret-key-here

# AI / LLM Configuration
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_api_key_here

# RAG & Escalation Parameters
RAG_SIMILARITY_THRESHOLD=0.25
RAG_TOP_K=5
AI_CONFIDENCE_THRESHOLD=0.70
RAG_CONFIDENCE_THRESHOLD=0.60
```

> **Note:** If no API key is set, the system gracefully uses rule-based fallback classification and FAISS similarity retrieval.

---

## 📁 Project Structure

```
SmartSupport AI/
├── app/
│   ├── __init__.py                # Flask application factory (create_app)
│   ├── config.py                  # App configuration settings
│   ├── extensions.py              # SQLAlchemy extension setup
│   │
│   ├── models/                    # Database models (SQLite / SQLAlchemy)
│   │   ├── user.py                # User model with password hashing & roles
│   │   ├── ticket.py              # Ticket model and lifecycle enums
│   │   ├── ticket_message.py      # Conversation messages
│   │   ├── internal_note.py       # Staff internal collaboration notes
│   │   ├── escalation.py          # Escalation records & team assignments
│   │   ├── audit_log.py           # Immutable audit log
│   │   ├── notification.py        # In-app notifications
│   │   ├── ai_analysis.py         # AI complaint triage model
│   │   ├── knowledge_doc.py       # Knowledge base documents & chunks
│   │   └── rag_resolution.py      # Grounded RAG resolutions & citations
│   │
│   ├── services/                  # Core business logic layer
│   │   ├── auth_service.py        # Session & authorization guards
│   │   ├── ticket_service.py      # Ticket lifecycle & database operations
│   │   ├── escalation_service.py  # Deterministic escalation rules
│   │   ├── notification_service.py# In-app notification management
│   │   ├── ai/                    # AI classification & LLM provider abstraction
│   │   └── rag/                   # Document parsing, FAISS vector store & RAG
│   │
│   ├── routes/                    # Blueprint route handlers
│   │   ├── main_routes.py         # Web views (Customer portal, Dashboard)
│   │   ├── auth_routes.py         # Login, Registration, Logout
│   │   └── api_routes.py          # RESTful JSON APIs
│   │
│   ├── templates/                 # Jinja2 HTML templates
│   │   ├── base.html              # Shared layout & navigation
│   │   ├── index.html             # Landing page
│   │   ├── login.html             # Login view
│   │   ├── register.html          # Registration view
│   │   ├── customer/              # Customer portal templates
│   │   └── admin/                 # Support operations templates
│   │
│   └── static/                    # CSS stylesheets and UI assets
│
├── tests/                         # Pytest test suites (70 passing tests)
│   ├── test_phase1.py             # Auth, RBAC, Sessions, Routing
│   ├── test_phase2.py             # Tickets, Messages, Internal Notes
│   ├── test_phase3.py             # AI Classification & Sentiment Triage
│   ├── test_phase4.py             # Document Ingestion, FAISS & RAG
│   ├── test_phase5.py             # Escalation, Status Lifecycle & Audit Trail
│   ├── test_phase6.py             # IDOR, XSS, Security & Error Handling
│   └── test_e2e_flow.py           # End-to-end full lifecycle test
│
├── run.py                         # Application entry point
├── requirements.txt               # Python package dependencies
├── .env.example                   # Template for environment variables
├── .gitignore                     # Git ignore rules (includes .env & DBs)
└── README.md                      # Project documentation
```

---

## 🧪 Automated Testing

Run the full automated test suite to verify application integrity:

```powershell
python -m pytest -v
```

**Results:** 70 passed, 0 failed (100% test pass rate across unit, integration, and security test suites).

---

## 📸 Screenshots

*(Add screenshots of your application here after running locally or deploying)*

| Screen | Description | Placeholder |
| :--- | :--- | :--- |
| **Login Page** | Clean authentication interface | `![Login](docs/screenshots/login.png)` |
| **Customer Dashboard** | Ticket overview and real-time statistics | `![Dashboard](docs/screenshots/dashboard.png)` |
| **Submit Complaint** | Complaint intake form | `![Submit](docs/screenshots/submit_complaint.png)` |
| **AI Analysis & RAG Resolution** | Grounded response with document citations | `![RAG Resolution](docs/screenshots/rag_resolution.png)` |
| **Support Queue Hub** | Agent triage and operations center | `![Support Hub](docs/screenshots/admin_hub.png)` |

---

## 👩‍💻 Author

**Krupa B T**  
- **GitHub:** [https://github.com/krupabt](https://github.com/krupabt)  
- **LinkedIn:** [https://linkedin.com/in/krupa-b-t-26a153331](https://linkedin.com/in/krupa-b-t-26a153331)

---

## 📜 License

This project is licensed under the MIT License.
