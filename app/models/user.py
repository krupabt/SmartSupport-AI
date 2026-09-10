from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class User(db.Model):
    """User account model supporting Customer, Support, and Admin roles."""
    __tablename__ = "users"

    VALID_ROLES = ("customer", "support", "admin")

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default="customer", nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    tickets = db.relationship("Ticket", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")

    def __init__(self, name: str, email: str, role: str = "customer", password: str = None):
        self.name = name.strip()
        self.email = email.strip().lower()
        self.role = role if role in self.VALID_ROLES else "customer"
        if password:
            self.set_password(password)

    def set_password(self, password: str) -> None:
        """Hash and store the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Check the password against the stored hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_support(self) -> bool:
        return self.role in ("support", "admin")

    def to_dict(self) -> dict:
        """Serialize user data safely without exposing password hash."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<User {self.id}: {self.email} ({self.role})>"
