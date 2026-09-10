import logging
from flask import Blueprint, jsonify, request, session
from app.extensions import db
from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory, SupportTeam
from app.models.ticket_message import SenderType
from app.models.notification import Notification
from app.models.user import User
from app.services.auth_service import (
    validate_email,
    validate_password,
    get_current_user,
    login_required,
    support_required,
)
from app.services.ticket_service import (
    create_ticket,
    add_ticket_message,
    add_support_reply,
    reopen_ticket,
    request_human_support,
    update_ticket_status,
    update_ticket_priority,
    update_ticket_category,
    update_ticket_team,
    add_internal_note,
    escalate_ticket,
    get_customer_stats,
    get_admin_stats,
)
from app.services.notification_service import (
    get_user_notifications,
    get_unread_count,
    mark_as_read,
    mark_all_as_read,
)

logger = logging.getLogger(__name__)
api_bp = Blueprint("api", __name__, url_prefix="/api")


def api_success(data=None, message="Success", status_code=200):
    return jsonify({
        "success": True,
        "data": data,
        "message": message,
    }), status_code


def api_error(code: str, message: str, status_code=400):
    return jsonify({
        "success": False,
        "error": {
            "code": code,
            "message": message,
        }
    }), status_code


# ---------------------------------------------------------------------------
# System & Auth APIs
# ---------------------------------------------------------------------------

@api_bp.route("/health", methods=["GET"])
def health_check():
    """System health check probe with subsystem status."""
    db_status = "connected"
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"

    from flask import current_app
    ai_provider = current_app.config.get("LLM_PROVIDER", "gemini")
    vector_store_type = "faiss"
    
    return jsonify({
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "ai_provider": ai_provider,
        "vector_store": vector_store_type,
        "version": "1.0.0-phase6",
    }), 200


@api_bp.route("/auth/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    role = data.get("role", "customer").strip().lower()

    if not name:
        return api_error("VALIDATION_ERROR", "Full name is required", 400)
    if not validate_email(email):
        return api_error("VALIDATION_ERROR", "Valid email address is required", 400)

    valid_pwd, pwd_msg = validate_password(password)
    if not valid_pwd:
        return api_error("VALIDATION_ERROR", pwd_msg, 400)

    if User.query.filter_by(email=email).first():
        return api_error("CONFLICT", "Email already registered", 409)

    assigned_role = role if role in ("support", "customer") else "customer"

    try:
        user = User(name=name, email=email, role=assigned_role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        session["user_id"] = user.id
        session["user_name"] = user.name
        session["user_email"] = user.email
        session["user_role"] = user.role

        return api_success(user.to_dict(), "User registered successfully", 201)
    except Exception as e:
        db.session.rollback()
        logger.error(f"API register error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Failed to create user account", 500)


@api_bp.route("/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return api_error("VALIDATION_ERROR", "Email and password are required", 400)

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return api_error("UNAUTHORIZED", "Invalid credentials", 401)

    session["user_id"] = user.id
    session["user_name"] = user.name
    session["user_email"] = user.email
    session["user_role"] = user.role

    return api_success(user.to_dict(), "Login successful", 200)


@api_bp.route("/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return api_success(None, "Logout successful", 200)


@api_bp.route("/auth/me", methods=["GET"])
@login_required
def api_me():
    user = get_current_user()
    if not user:
        return api_error("NOT_FOUND", "User not found", 404)
    return api_success(user.to_dict(), "Current user profile", 200)


# ---------------------------------------------------------------------------
# Customer Ticket APIs
# ---------------------------------------------------------------------------

@api_bp.route("/tickets", methods=["POST"])
@login_required
def api_create_ticket():
    """Submit a complaint and create a ticket."""
    data = request.get_json(silent=True) or {}
    subject = data.get("subject", "").strip()
    description = data.get("description", "").strip()
    product_service = data.get("product_service", "").strip()
    reference_id = data.get("reference_id", "").strip() or None

    if not subject:
        return api_error("VALIDATION_ERROR", "Subject is required", 400)
    if not description:
        return api_error("VALIDATION_ERROR", "Complaint description is required", 400)
    if not product_service:
        return api_error("VALIDATION_ERROR", "Product or service name is required", 400)

    try:
        ticket = create_ticket(
            user_id=session["user_id"],
            subject=subject,
            description=description,
            product_service=product_service,
            reference_id=reference_id,
        )
        return api_success(ticket.to_dict(include_internal=False), "Ticket created successfully", 201)
    except Exception as e:
        logger.error(f"API Create Ticket Error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", str(e), 500)


@api_bp.route("/tickets", methods=["GET"])
@login_required
def api_list_customer_tickets():
    """List authenticated customer's tickets."""
    user_id = session.get("user_id")
    status_filter = request.args.get("status")
    priority_filter = request.args.get("priority")

    query = Ticket.query.filter_by(user_id=user_id)
    if status_filter and status_filter in TicketStatus.ALL:
        query = query.filter_by(status=status_filter)
    if priority_filter and priority_filter in TicketPriority.ALL:
        query = query.filter_by(priority=priority_filter)

    tickets = query.order_by(Ticket.created_at.desc()).all()
    return api_success([t.to_dict(include_internal=False) for t in tickets], "Customer tickets retrieved")


@api_bp.route("/tickets/<ticket_number>", methods=["GET"])
@login_required
def api_get_customer_ticket(ticket_number):
    """Retrieve details and messages of a customer's ticket."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    user_id = session.get("user_id")
    user_role = session.get("user_role")
    if ticket.user_id != user_id and user_role not in ("admin", "support"):
        return api_error("FORBIDDEN", "Access denied to this ticket.", 403)

    return api_success(ticket.to_dict(include_internal=False), "Ticket details retrieved")


@api_bp.route("/tickets/<ticket_number>/messages", methods=["POST"])
@login_required
def api_add_customer_message(ticket_number):
    """Post a customer message to an existing ticket."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    user_id = session.get("user_id")
    user_role = session.get("user_role")
    if ticket.user_id != user_id and user_role not in ("admin", "support"):
        return api_error("FORBIDDEN", "Access denied to this ticket.", 403)

    data = request.get_json(silent=True) or {}
    message_text = data.get("message", "").strip()
    if not message_text:
        return api_error("VALIDATION_ERROR", "Message cannot be empty", 400)

    try:
        msg = add_ticket_message(
            ticket=ticket,
            sender_id=user_id,
            sender_name=session.get("user_name", "Customer"),
            sender_type=SenderType.CUSTOMER,
            message=message_text,
            is_internal=False,
        )
        return api_success(msg.to_dict(), "Message posted successfully", 201)
    except ValueError as ve:
        return api_error("VALIDATION_ERROR", str(ve), 400)
    except Exception as e:
        logger.error(f"API add message error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Failed to add message", 500)


@api_bp.route("/tickets/<ticket_number>/reopen", methods=["POST"])
@login_required
def api_reopen_ticket(ticket_number):
    """Customer action to reopen a closed or resolved ticket."""
    user_id = session.get("user_id")
    user_role = session.get("user_role")
    
    if user_role in ("admin", "support"):
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    else:
        ticket = Ticket.query.filter_by(ticket_number=ticket_number, user_id=user_id).first()

    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "").strip()

    try:
        updated_ticket = reopen_ticket(
            ticket=ticket,
            actor_id=user_id,
            actor_name=session.get("user_name", "User"),
            reason=reason,
        )
        return api_success(updated_ticket.to_dict(include_internal=False), "Ticket reopened successfully", 200)
    except ValueError as ve:
        return api_error("VALIDATION_ERROR", str(ve), 400)
    except Exception as e:
        logger.error(f"API reopen ticket error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Failed to reopen ticket", 500)


@api_bp.route("/tickets/<ticket_number>/contact-support", methods=["POST"])
@login_required
def api_contact_support(ticket_number):
    """Customer action to request direct human support assistance."""
    user_id = session.get("user_id")
    user_role = session.get("user_role")
    
    if user_role in ("admin", "support"):
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    else:
        ticket = Ticket.query.filter_by(ticket_number=ticket_number, user_id=user_id).first()

    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "").strip()

    try:
        escalation = request_human_support(
            ticket=ticket,
            user_id=user_id,
            user_name=session.get("user_name", "Customer"),
            reason=reason,
        )
        return api_success({
            "escalation": escalation.to_dict(),
            "ticket": ticket.to_dict(include_internal=False),
        }, "Human support requested successfully. A support specialist has been assigned.", 200)
    except ValueError as ve:
        return api_error("VALIDATION_ERROR", str(ve), 400)
    except Exception as e:
        logger.error(f"API contact support error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Failed to request human support", 500)



# ---------------------------------------------------------------------------
# Support / Admin Ticket APIs
# ---------------------------------------------------------------------------

@api_bp.route("/admin/tickets", methods=["GET"])
@support_required
def api_admin_list_tickets():
    """Admin queue listing with filters."""
    status_filter = request.args.get("status")
    priority_filter = request.args.get("priority")
    category_filter = request.args.get("category")
    team_filter = request.args.get("team")
    search = request.args.get("q", "").strip()

    query = Ticket.query.join(User)

    if search:
        query = query.filter(
            db.or_(
                Ticket.ticket_number.ilike(f"%{search}%"),
                Ticket.subject.ilike(f"%{search}%"),
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
            )
        )
    if status_filter and status_filter in TicketStatus.ALL:
        query = query.filter(Ticket.status == status_filter)
    if priority_filter and priority_filter in TicketPriority.ALL:
        query = query.filter(Ticket.priority == priority_filter)
    if category_filter and category_filter in TicketCategory.ALL:
        query = query.filter(Ticket.category == category_filter)
    if team_filter and team_filter in SupportTeam.ALL:
        query = query.filter(Ticket.assigned_team == team_filter)

    tickets = query.order_by(Ticket.created_at.desc()).all()
    return api_success([t.to_dict(include_internal=True) for t in tickets], "Admin ticket queue retrieved")


@api_bp.route("/admin/tickets/<ticket_number>", methods=["GET"])
@support_required
def api_admin_get_ticket(ticket_number):
    """Admin single ticket view including internal notes and escalations."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    return api_success(ticket.to_dict(include_internal=True), "Admin ticket details retrieved")


@api_bp.route("/admin/tickets/<ticket_number>", methods=["PATCH"])
@support_required
def api_admin_update_ticket(ticket_number):
    """Admin update ticket status, priority, category, or assigned team."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    data = request.get_json(silent=True) or {}
    actor_name = session.get("user_name", "Support Agent")

    try:
        if "status" in data:
            update_ticket_status(ticket, data["status"], actor_name)
        if "priority" in data:
            update_ticket_priority(ticket, data["priority"], actor_name)
        if "category" in data:
            update_ticket_category(ticket, data["category"], actor_name)
        if "assigned_team" in data:
            update_ticket_team(ticket, data["assigned_team"], actor_name)

        return api_success(ticket.to_dict(include_internal=True), "Ticket updated successfully")
    except ValueError as ve:
        return api_error("VALIDATION_ERROR", str(ve), 400)
    except Exception as e:
        logger.error(f"API update ticket error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Failed to update ticket", 500)


@api_bp.route("/admin/tickets/<ticket_number>/notes", methods=["POST"])
@support_required
def api_admin_add_note(ticket_number):
    """Admin add internal note to ticket."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    data = request.get_json(silent=True) or {}
    note_text = data.get("note", "").strip()
    if not note_text:
        return api_error("VALIDATION_ERROR", "Note content cannot be empty", 400)

    try:
        note = add_internal_note(
            ticket=ticket,
            author_id=session["user_id"],
            author_name=session.get("user_name", "Support Staff"),
            note=note_text,
        )
        return api_success(note.to_dict(), "Internal note saved successfully", 201)
    except Exception as e:
        logger.error(f"API add note error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Failed to add internal note", 500)


@api_bp.route("/admin/tickets/<ticket_number>/escalate", methods=["POST"])
@support_required
def api_admin_escalate_ticket(ticket_number):
    """Admin manual escalation trigger."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "").strip()
    target_team = data.get("target_team", SupportTeam.SENIOR_SUPPORT)

    if not reason:
        return api_error("VALIDATION_ERROR", "Escalation reason is required", 400)

    try:
        escalation = escalate_ticket(
            ticket=ticket,
            reason=reason,
            escalated_by=session.get("user_name", "Support Agent"),
            target_team=target_team,
        )
        return api_success({
            "escalation": escalation.to_dict(),
            "ticket": ticket.to_dict(include_internal=True),
        }, "Ticket escalated successfully", 200)
    except Exception as e:
        logger.error(f"API escalate ticket error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Failed to escalate ticket", 500)


@api_bp.route("/admin/tickets/<ticket_number>/analyze", methods=["POST"])
@support_required
def api_admin_analyze_ticket(ticket_number):
    """Admin trigger on-demand AI complaint analysis."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    try:
        from app.services.ai.complaint_analyzer import ComplaintAnalyzer
        analyzer = ComplaintAnalyzer()
        analysis = analyzer.analyze_and_store(ticket)

        if analysis.status == "COMPLETED":
            return api_success(analysis.to_dict(), "Ticket analyzed successfully", 200)
        elif analysis.status == "UNAVAILABLE":
            return api_error("AI_UNAVAILABLE", analysis.reason or "AI service not configured", 503)
        else:
            return api_error("AI_ANALYSIS_FAILED", analysis.reason or "AI analysis failed", 422)
    except Exception as e:
        logger.error(f"API analyze ticket error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Internal error during AI analysis", 500)


@api_bp.route("/admin/tickets/<ticket_number>/messages", methods=["POST"])
@support_required
def api_admin_add_message(ticket_number):
    """Support agent post a public reply to the ticket thread."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    data = request.get_json(silent=True) or {}
    message_text = data.get("message", "").strip()
    if not message_text:
        return api_error("VALIDATION_ERROR", "Message cannot be empty", 400)

    try:
        msg = add_support_reply(
            ticket=ticket,
            sender_id=session["user_id"],
            sender_name=session.get("user_name", "Support Specialist"),
            message=message_text,
        )
        return api_success(msg.to_dict(), "Support reply posted successfully", 201)
    except ValueError as ve:
        return api_error("VALIDATION_ERROR", str(ve), 400)
    except Exception as e:
        logger.error(f"API admin add message error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Failed to add support reply", 500)


# ---------------------------------------------------------------------------
# Notification APIs
# ---------------------------------------------------------------------------

@api_bp.route("/notifications", methods=["GET"])
@login_required
def api_get_notifications():
    """Retrieve notifications and unread count for current user."""
    user_id = session.get("user_id")
    unread_only = request.args.get("unread", "").lower() in ("true", "1")
    limit = min(int(request.args.get("limit", 20)), 50)

    notifs = get_user_notifications(user_id=user_id, limit=limit, unread_only=unread_only)
    unread_count = get_unread_count(user_id=user_id)

    return api_success({
        "notifications": [n.to_dict() for n in notifs],
        "unread_count": unread_count,
    }, "Notifications retrieved successfully", 200)


@api_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def api_mark_notification_read(notification_id):
    """Mark single notification as read."""
    user_id = session.get("user_id")
    success = mark_as_read(notification_id, user_id)
    if not success:
        return api_error("NOT_FOUND", "Notification not found or access denied.", 404)

    return api_success({"notification_id": notification_id, "is_read": True}, "Notification marked as read", 200)


@api_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def api_mark_all_notifications_read():
    """Mark all notifications for current user as read."""
    user_id = session.get("user_id")
    count = mark_all_as_read(user_id)
    return api_success({"marked_count": count}, "All notifications marked as read", 200)


# ---------------------------------------------------------------------------
# Dashboard Stats & Analytics APIs
# ---------------------------------------------------------------------------

@api_bp.route("/dashboard/customer", methods=["GET"])
@login_required
def api_customer_dashboard():
    """Customer dashboard stats API."""
    stats = get_customer_stats(session["user_id"])
    return api_success(stats, "Customer dashboard metrics")


@api_bp.route("/dashboard/admin", methods=["GET"])
@support_required
def api_admin_dashboard():
    """Admin dashboard stats API with date range filter support."""
    date_range = request.args.get("range") or request.args.get("date_range", "all")
    stats = get_admin_stats(date_range=date_range)
    return api_success(stats, "Admin dashboard metrics")


@api_bp.route("/admin/analytics", methods=["GET"])
@support_required
def api_admin_analytics():
    """Admin operational analytics with real DB metrics."""
    date_range = request.args.get("range") or request.args.get("date_range", "all")
    stats = get_admin_stats(date_range=date_range)
    return api_success(stats, "Admin operational analytics retrieved", 200)



# ---------------------------------------------------------------------------
# RAG Resolution & Knowledge Base APIs (Phase 4)
# ---------------------------------------------------------------------------

@api_bp.route("/tickets/<ticket_number>/resolution", methods=["GET"])
@login_required
def api_get_ticket_resolution(ticket_number):
    """Retrieve grounded AI resolution and source citations for a ticket."""
    user = get_current_user()
    if user.is_support or user.is_admin:
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    else:
        ticket = Ticket.query.filter_by(ticket_number=ticket_number, user_id=user.id).first()

    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    from app.models.rag_resolution import RAGResolution
    resolution = RAGResolution.query.filter_by(ticket_id=ticket.id).first()
    if not resolution:
        return api_error("RESOLUTION_NOT_FOUND", "No AI resolution has been generated for this ticket yet.", 404)

    return api_success(resolution.to_dict(), "Ticket AI resolution retrieved successfully", 200)


@api_bp.route("/tickets/<ticket_number>/resolve", methods=["POST"])
@login_required
def api_customer_resolve_ticket(ticket_number):
    """Trigger on-demand grounded RAG resolution for a customer ticket."""
    user = get_current_user()
    if user.is_support or user.is_admin:
        ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    else:
        ticket = Ticket.query.filter_by(ticket_number=ticket_number, user_id=user.id).first()

    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    try:
        from app.services.rag.rag_service import RAGService
        rag_service = RAGService()
        resolution = rag_service.resolve_ticket(ticket, force_regenerate=True)
        return api_success(resolution.to_dict(), "Grounded AI resolution generated successfully", 200)
    except Exception as e:
        logger.error(f"API customer resolve ticket error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Internal error during RAG resolution", 500)


@api_bp.route("/admin/tickets/<ticket_number>/resolve", methods=["POST"])
@support_required
def api_admin_resolve_ticket(ticket_number):
    """Support/Admin trigger on-demand grounded RAG resolution."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first()
    if not ticket:
        return api_error("TICKET_NOT_FOUND", "The requested ticket could not be found.", 404)

    try:
        from app.services.rag.rag_service import RAGService
        rag_service = RAGService()
        resolution = rag_service.resolve_ticket(ticket, force_regenerate=True)
        return api_success(resolution.to_dict(), "Grounded AI resolution regenerated successfully", 200)
    except Exception as e:
        logger.error(f"API admin resolve ticket error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", "Internal error during RAG resolution", 500)


@api_bp.route("/admin/knowledge-base", methods=["GET"])
@support_required
def api_admin_get_knowledge_base():
    """List all knowledge documents and chunk counts."""
    from app.models.knowledge_doc import KnowledgeDocument
    docs = KnowledgeDocument.query.order_by(KnowledgeDocument.created_at.desc()).all()
    return api_success([d.to_dict() for d in docs], "Knowledge documents retrieved", 200)


@api_bp.route("/admin/knowledge-base/<int:doc_id>", methods=["GET"])
@support_required
def api_admin_get_knowledge_document(doc_id):
    """Get single knowledge document with all chunks."""
    from app.models.knowledge_doc import KnowledgeDocument
    doc = db.session.get(KnowledgeDocument, doc_id)
    if not doc:
        return api_error("DOCUMENT_NOT_FOUND", "Knowledge document not found", 404)
    return api_success(doc.to_dict(include_chunks=True), "Document details retrieved", 200)


@api_bp.route("/admin/knowledge-base/<int:doc_id>/reindex", methods=["POST"])
@support_required
def api_admin_reindex_document(doc_id):
    """Reindex an existing document."""
    from app.models.knowledge_doc import KnowledgeDocument
    from app.services.rag.rag_service import RAGService
    doc = db.session.get(KnowledgeDocument, doc_id)
    if not doc:
        return api_error("DOCUMENT_NOT_FOUND", "Knowledge document not found", 404)

    try:
        rag_service = RAGService()
        updated_doc = rag_service.ingest_document(
            file_path=doc.file_path,
            title=doc.title,
            category=doc.category,
            description=doc.description,
            document_id=doc.id,
        )
        return api_success(updated_doc.to_dict(include_chunks=True), "Document reindexed successfully", 200)
    except Exception as e:
        logger.error(f"API reindex document error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", f"Failed to reindex document: {str(e)}", 500)


@api_bp.route("/admin/knowledge-base/<int:doc_id>", methods=["DELETE"])
@support_required
def api_admin_delete_document(doc_id):
    """Delete a document and purge its vectors."""
    from app.models.knowledge_doc import KnowledgeDocument
    from app.services.rag.rag_service import RAGService
    doc = db.session.get(KnowledgeDocument, doc_id)
    if not doc:
        return api_error("DOCUMENT_NOT_FOUND", "Knowledge document not found", 404)

    try:
        rag_service = RAGService()
        rag_service.delete_document(doc.id)
        return api_success(None, "Document deleted successfully", 200)
    except Exception as e:
        logger.error(f"API delete document error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", f"Failed to delete document: {str(e)}", 500)


@api_bp.route("/admin/knowledge-base/rebuild", methods=["POST"])
@support_required
def api_admin_rebuild_vector_store():
    """Rebuild entire FAISS vector store index."""
    try:
        from app.services.rag.rag_service import RAGService
        rag_service = RAGService()
        rag_service.rebuild_index()
        return api_success(None, "Vector store index rebuilt successfully", 200)
    except Exception as e:
        logger.error(f"API rebuild vector store error: {str(e)}", exc_info=True)
        return api_error("SERVER_ERROR", f"Failed to rebuild vector store: {str(e)}", 500)

