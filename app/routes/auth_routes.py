from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from app.extensions import db
from app.models.user import User
from app.services.auth_service import validate_email, validate_password

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Handle new user registration."""
    if "user_id" in session:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = request.form.get("role", "customer").strip().lower()

        # Validation
        if not name:
            flash("Full name is required.", "danger")
            return render_template("register.html", name=name, email=email), 400

        if not validate_email(email):
            flash("Please enter a valid email address.", "danger")
            return render_template("register.html", name=name, email=email), 400

        valid_pwd, pwd_msg = validate_password(password)
        if not valid_pwd:
            flash(pwd_msg, "danger")
            return render_template("register.html", name=name, email=email), 400

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("register.html", name=name, email=email), 400

        # Check existing user
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("An account with this email address already exists. Please log in.", "warning")
            return render_template("register.html", name=name, email=email), 400

        # Prevent arbitrary public registration of admin accounts unless designated
        assigned_role = "customer"
        if role in ("support", "customer"):
            assigned_role = role

        try:
            new_user = User(name=name, email=email, role=assigned_role)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

            # Set session
            session["user_id"] = new_user.id
            session["user_name"] = new_user.name
            session["user_email"] = new_user.email
            session["user_role"] = new_user.role

            flash("Registration successful! Welcome to SmartSupport AI.", "success")
            if new_user.is_support:
                return redirect(url_for("main.admin_dashboard"))
            return redirect(url_for("main.dashboard"))
        except Exception as e:
            db.session.rollback()
            flash("An error occurred during registration. Please try again.", "danger")
            return render_template("register.html", name=name, email=email), 500

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Handle user authentication."""
    if "user_id" in session:
        role = session.get("user_role")
        if role in ("admin", "support"):
            return redirect(url_for("main.admin_dashboard"))
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        next_page = request.form.get("next") or request.args.get("next")

        if not email or not password:
            flash("Please provide both email and password.", "danger")
            return render_template("login.html", email=email), 400

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password. Please try again.", "danger")
            return render_template("login.html", email=email), 401

        # Store session
        session["user_id"] = user.id
        session["user_name"] = user.name
        session["user_email"] = user.email
        session["user_role"] = user.role

        flash(f"Welcome back, {user.name}!", "success")

        # Redirect based on next param or role
        if next_page and next_page.startswith("/"):
            return redirect(next_page)

        if user.is_support:
            return redirect(url_for("main.admin_dashboard"))
        return redirect(url_for("main.dashboard"))

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """Handle user logout."""
    session.clear()
    flash("You have been securely logged out.", "info")
    return redirect(url_for("main.index"))
