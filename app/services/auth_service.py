import re
from functools import wraps
from flask import session, redirect, url_for, flash, request, jsonify, abort
from app.extensions import db
from app.models.user import User


EMAIL_REGEX = re.compile(r"^[\w\.-]+@([\w\.-]+\.)+[a-zA-Z]{2,}$")


def validate_email(email: str) -> bool:
    """Validate email format with regex."""
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def validate_password(password: str) -> tuple[bool, str]:
    """Validate password constraints (min length 6)."""
    if not password or len(password) < 6:
        return False, "Password must be at least 6 characters long."
    return True, ""


def get_current_user() -> User | None:
    """Retrieve the currently logged-in user object from session, or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def login_required(f):
    """Decorator to require user authentication before accessing a view."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles):
    """Decorator to restrict access to specific roles (e.g. 'admin', 'support')."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
                flash("Please log in to access this page.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            
            user_role = session.get("user_role")
            if user_role not in allowed_roles:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Forbidden", "message": "Insufficient permissions"}), 403
                flash("Access denied: You do not have permission to view this resource.", "danger")
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """Decorator shortcut to require admin role."""
    return role_required("admin")(f)


def support_required(f):
    """Decorator shortcut to require support or admin role."""
    return role_required("support", "admin")(f)
