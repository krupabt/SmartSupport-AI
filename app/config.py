import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env if present
load_dotenv(BASE_DIR / ".env")


class Config:
    """Base application configuration."""
    SECRET_KEY = os.getenv("SECRET_KEY", "smartsupport-dev-insecure-secret-key-2026")
    
    # Database URL configuration (supports both SQLite and PostgreSQL)
    raw_db_url = os.getenv("DATABASE_URL")
    if raw_db_url:
        if raw_db_url.startswith("postgres://"):
            raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
        SQLALCHEMY_DATABASE_URI = raw_db_url
    else:
        instance_dir = BASE_DIR / "instance"
        instance_dir.mkdir(exist_ok=True)
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{instance_dir / 'smartsupport.db'}"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session Cookie Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours in seconds
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))  # 16 MB max upload
    
    # AI & RAG Configuration
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
    RAG_SIMILARITY_THRESHOLD = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.25"))
    RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
    
    # Vector store & Upload storage paths (Configurable for persistent volumes)
    VECTOR_STORE_PATH = os.getenv("VECTOR_STORE_PATH", str(BASE_DIR / "instance" / "vector_store"))
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "instance" / "knowledge_base"))

    # Escalation Engine Thresholds (Configurable)
    AI_CONFIDENCE_THRESHOLD = float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.70"))
    RAG_CONFIDENCE_THRESHOLD = float(os.getenv("RAG_CONFIDENCE_THRESHOLD", "0.60"))
    AUTO_ESCALATE_CRITICAL = os.getenv("AUTO_ESCALATE_CRITICAL", "true").lower() in ("true", "1", "yes")
    AUTO_ESCALATE_SECURITY = os.getenv("AUTO_ESCALATE_SECURITY", "true").lower() in ("true", "1", "yes")


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-secret-key"
    LLM_PROVIDER = "fake"
    RAG_SIMILARITY_THRESHOLD = 0.0
    RAG_TOP_K = 5
    AI_CONFIDENCE_THRESHOLD = 0.70
    RAG_CONFIDENCE_THRESHOLD = 0.60
    AUTO_ESCALATE_CRITICAL = True
    AUTO_ESCALATE_SECURITY = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("true", "1")



config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
