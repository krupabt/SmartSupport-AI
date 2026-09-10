import os
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify
from app.config import config_by_name
from app.extensions import db
from app.services.auth_service import get_current_user


def create_app(config_name=None):
    """Application factory for Flask."""
    if config_name is None:
        config_name = os.getenv("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name["default"]))

    # Initialize extensions
    db.init_app(app)

    # Register blueprints
    from app.routes.main_routes import main_bp
    from app.routes.auth_routes import auth_bp
    from app.routes.api_routes import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)

    # Inject context into templates
    @app.context_processor
    def inject_context():
        return {
            "current_user": get_current_user(),
            "current_year": datetime.now(timezone.utc).year,
        }

    # Custom Error Handlers
    @app.errorhandler(403)
    def forbidden_error(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Forbidden", "message": "Access denied"}), 403
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found_error(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not Found", "message": "The requested resource was not found"}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal Server Error", "message": "An unexpected server error occurred"}), 500
        return render_template("errors/500.html"), 500

    # Auto-create tables in development
    with app.app_context():
        db.create_all()

    return app
