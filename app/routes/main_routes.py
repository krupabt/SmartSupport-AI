import os
import logging
from datetime import datetime, timezone, timedelta
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, session, redirect, url_for, request, flash, abort, current_app, jsonify
from app.extensions import db
from app.models.ticket import Ticket, TicketStatus, TicketPriority, TicketCategory, SupportTeam
from app.models.ticket_message import SenderType
from app.models.user import User
from app.models.knowledge_doc import KnowledgeDocument, KnowledgeChunk, DocumentStatus
from app.models.rag_resolution import RAGResolution, RAGSource, RAGStatus
from app.models.audit_log import TicketAuditLog, AuditAction
from app.models.notification import Notification, NotificationType
from app.services.auth_service import login_required, support_required
from app.services.ticket_service import (
    create_ticket,
    add_ticket_message,
    add_support_reply,
    update_ticket_status,
    reopen_ticket,
    request_human_support,
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
from app.services.rag.rag_service import RAGService

logger = logging.getLogger(__name__)
main_bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Template Context Processor (Notifications & Status helpers)
# ---------------------------------------------------------------------------

@main_bp.app_context_processor
def inject_notifications():
    """Inject user notifications and unread badge into all base templates."""
    user_id = session.get("user_id")
    if user_id:
        unread = get_unread_count(user_id)
        notifs = get_user_notifications(user_id, limit=10)
        return {
            "unread_notifs_count": unread,
            "unread_notifications_count": unread,
            "recent_notifs": notifs,
            "user_notifications": notifs,
        }
    return {
        "unread_notifs_count": 0,
        "unread_notifications_count": 0,
        "recent_notifs": [],
        "user_notifications": [],
    }


# ---------------------------------------------------------------------------
# Public / Landing Routes
# ---------------------------------------------------------------------------

@main_bp.route("/")
def index():
    """Public landing page."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Customer Routes
# ---------------------------------------------------------------------------

@main_bp.route("/dashboard")
@login_required
def dashboard():
    """Customer dashboard with real database statistics and recent tickets."""
    user_id = session.get("user_id")
    stats = get_customer_stats(user_id)
    recent_tickets = (
        Ticket.query.filter_by(user_id=user_id)
        .order_by(Ticket.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "customer/dashboard.html",
        user_name=session.get("user_name"),
        user_email=session.get("user_email"),
        total_tickets=stats["total_tickets"],
        open_tickets=stats["open_tickets"],
        resolved_tickets=stats["resolved_tickets"],
        escalated_tickets=stats["escalated_tickets"],
        recent_tickets=recent_tickets,
    )


@main_bp.route("/submit-complaint", methods=["GET", "POST"])
@login_required
def submit_complaint():
    """Submit a customer support complaint."""
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()
        product_service = request.form.get("product_service", "").strip()
        reference_id = request.form.get("reference_id", "").strip() or None

        # Server-side Validation
        errors = []
        if not subject:
            errors.append("Complaint subject is required.")
        elif len(subject) > 200:
            errors.append("Subject cannot exceed 200 characters.")

        if not description:
            errors.append("Detailed complaint description is required.")
        elif len(description) < 10:
            errors.append("Please provide more details in your complaint (minimum 10 characters).")

        if not product_service:
            errors.append("Product or service name is required.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "customer/submit_complaint.html",
                subject=subject,
                description=description,
                product_service=product_service,
                reference_id=reference_id,
            ), 400

        try:
            ticket = create_ticket(
                user_id=session["user_id"],
                subject=subject,
                description=description,
                product_service=product_service,
                reference_id=reference_id,
                category=TicketCategory.GENERAL,
                priority=TicketPriority.MEDIUM,
            )
            flash(f"Complaint registered successfully! Your Ticket ID is {ticket.ticket_number}.", "success")
            return redirect(url_for("main.customer_ticket_detail", ticket_number=ticket.ticket_number))
        except Exception as e:
            logger.error(f"Error creating ticket: {str(e)}", exc_info=True)
            flash("An error occurred while submitting your complaint. Please try again.", "danger")
            return render_template(
                "customer/submit_complaint.html",
                subject=subject,
                description=description,
                product_service=product_service,
                reference_id=reference_id,
            ), 500

    return render_template("customer/submit_complaint.html")


@main_bp.route("/tickets")
@login_required
def customer_tickets():
    """Customer's tickets list with filtering and search."""
    user_id = session.get("user_id")
    search_query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()

    query = Ticket.query.filter_by(user_id=user_id)

    if search_query:
        query = query.filter(
            (Ticket.ticket_number.ilike(f"%{search_query}%"))
            | (Ticket.subject.ilike(f"%{search_query}%"))
            | (Ticket.product_service.ilike(f"%{search_query}%"))
        )

    if status_filter and status_filter in TicketStatus.ALL:
        query = query.filter_by(status=status_filter)

    if priority_filter and priority_filter in TicketPriority.ALL:
        query = query.filter_by(priority=priority_filter)

    tickets = query.order_by(Ticket.created_at.desc()).all()

    return render_template(
        "customer/ticket_list.html",
        tickets=tickets,
        search_query=search_query,
        status_filter=status_filter,
        priority_filter=priority_filter,
        statuses=TicketStatus.ALL,
        priorities=TicketPriority.ALL,
    )


@main_bp.route("/tickets/<ticket_number>", methods=["GET", "POST"])
@login_required
def customer_ticket_detail(ticket_number):
    """Customer view of a single ticket thread."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()

    # Strict authorization check (IDOR protection)
    user_id = session.get("user_id")
    user_role = session.get("user_role")
    if ticket.user_id != user_id and user_role not in ("admin", "support"):
        abort(403)

    if request.method == "POST":
        message_text = request.form.get("message", "").strip()
        if not message_text:
            flash("Reply message cannot be empty.", "warning")
            return redirect(url_for("main.customer_ticket_detail", ticket_number=ticket.ticket_number))

        try:
            add_ticket_message(
                ticket=ticket,
                sender_id=user_id,
                sender_name=session.get("user_name", "Customer"),
                sender_type=SenderType.CUSTOMER,
                message=message_text,
                is_internal=False,
            )
            flash("Reply added to ticket thread.", "success")
            return redirect(url_for("main.customer_ticket_detail", ticket_number=ticket.ticket_number))
        except ValueError as ve:
            flash(str(ve), "danger")
            return redirect(url_for("main.customer_ticket_detail", ticket_number=ticket.ticket_number))
        except Exception as e:
            logger.error(f"Error adding reply: {str(e)}", exc_info=True)
            flash("Failed to post reply. Please try again.", "danger")
            return redirect(url_for("main.customer_ticket_detail", ticket_number=ticket.ticket_number))

    # Visible messages only (is_internal == False)
    visible_messages = [msg for msg in ticket.messages if not msg.is_internal]

    return render_template(
        "customer/ticket_detail.html",
        ticket=ticket,
        messages=visible_messages,
    )


@main_bp.route("/tickets/<ticket_number>/reopen", methods=["POST"])
@login_required
def customer_ticket_reopen(ticket_number):
    """Customer reopen action on resolved/closed ticket."""
    user_id = session.get("user_id")
    user_name = session.get("user_name", "Customer")
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()

    if ticket.user_id != user_id and session.get("user_role") not in ("admin", "support"):
        abort(403)

    reason = request.form.get("reason", "").strip()
    try:
        reopen_ticket(ticket, actor_id=user_id, actor_name=user_name, reason=reason)
        flash("Ticket successfully reopened to 'In Progress'. Our support team has been alerted.", "success")
    except Exception as e:
        logger.error(f"Failed to reopen ticket {ticket_number}: {str(e)}", exc_info=True)
        flash(f"Could not reopen ticket: {str(e)}", "danger")

    return redirect(url_for("main.customer_ticket_detail", ticket_number=ticket.ticket_number))


@main_bp.route("/tickets/<ticket_number>/contact-support", methods=["POST"])
@login_required
def customer_contact_support(ticket_number):
    """Customer request direct human support escalation."""
    user_id = session.get("user_id")
    user_name = session.get("user_name", "Customer")
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()

    if ticket.user_id != user_id and session.get("user_role") not in ("admin", "support"):
        abort(403)

    reason = request.form.get("reason", "").strip()
    try:
        request_human_support(ticket, user_id=user_id, user_name=user_name, reason=reason)
        flash("Your request has been escalated to a human support agent.", "info")
    except Exception as e:
        logger.error(f"Failed to request human support for {ticket_number}: {str(e)}", exc_info=True)
        flash("Could not escalate ticket at this time.", "danger")

    return redirect(url_for("main.customer_ticket_detail", ticket_number=ticket.ticket_number))


# ---------------------------------------------------------------------------
# Admin / Support Routes
# ---------------------------------------------------------------------------

@main_bp.route("/admin/dashboard")
@support_required
def admin_dashboard():
    """Support operations center with real live metrics, date filters, and performance KPIs."""
    date_range = request.args.get("range", "all").strip().lower()
    if date_range not in ("all", "today", "7d", "30d"):
        date_range = "all"

    stats = get_admin_stats(date_range=date_range)
    recent_tickets = Ticket.query.order_by(Ticket.created_at.desc()).limit(8).all()
    active_escalations = (
        Ticket.query.filter_by(status=TicketStatus.ESCALATED)
        .order_by(Ticket.updated_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "admin/dashboard.html",
        user_name=session.get("user_name"),
        user_role=session.get("user_role"),
        stats=stats,
        recent_tickets=recent_tickets,
        **stats,
    )


@main_bp.route("/admin/tickets")
@support_required
def admin_tickets():
    """Admin support ticket queue with urgency ordering and multi-attribute filters."""
    search_query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    priority_filter = request.args.get("priority", "").strip()
    category_filter = request.args.get("category", "").strip()
    sentiment_filter = request.args.get("sentiment", "").strip()
    team_filter = request.args.get("team", "").strip()
    escalated_only = request.args.get("escalated", "").strip().lower() == "true"
    date_range = request.args.get("range", "").strip().lower()

    query = Ticket.query.join(User)

    if search_query:
        query = query.filter(
            db.or_(
                Ticket.ticket_number.ilike(f"%{search_query}%"),
                Ticket.subject.ilike(f"%{search_query}%"),
                Ticket.product_service.ilike(f"%{search_query}%"),
                User.name.ilike(f"%{search_query}%"),
                User.email.ilike(f"%{search_query}%"),
            )
        )

    if status_filter and status_filter in TicketStatus.ALL:
        query = query.filter(Ticket.status == status_filter)

    if priority_filter and priority_filter in TicketPriority.ALL:
        query = query.filter(Ticket.priority == priority_filter)

    if category_filter and category_filter in TicketCategory.ALL:
        query = query.filter(Ticket.category == category_filter)

    if sentiment_filter:
        query = query.filter(Ticket.sentiment == sentiment_filter)

    if team_filter and team_filter in SupportTeam.ALL:
        query = query.filter(Ticket.assigned_team == team_filter)

    if escalated_only:
        query = query.filter(Ticket.status == TicketStatus.ESCALATED)

    if date_range == "today":
        now = datetime.now(timezone.utc)
        start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        query = query.filter(Ticket.created_at >= start_of_day)
    elif date_range == "7d":
        now = datetime.now(timezone.utc)
        query = query.filter(Ticket.created_at >= (now - timedelta(days=7)))
    elif date_range == "30d":
        now = datetime.now(timezone.utc)
        query = query.filter(Ticket.created_at >= (now - timedelta(days=30)))

    # Urgency Ordering:
    # 1. Priority: CRITICAL (1), HIGH (2), MEDIUM (3), LOW (4)
    # 2. Status: ESCALATED first
    # 3. Created date: oldest first
    priority_order = db.case(
        {
            TicketPriority.CRITICAL: 1,
            TicketPriority.HIGH: 2,
            TicketPriority.MEDIUM: 3,
            TicketPriority.LOW: 4,
        },
        value=Ticket.priority,
        else_=5,
    )
    escalation_order = db.case(
        {TicketStatus.ESCALATED: 1},
        value=Ticket.status,
        else_=2,
    )

    tickets = query.order_by(priority_order.asc(), escalation_order.asc(), Ticket.created_at.asc()).all()

    return render_template(
        "admin/ticket_list.html",
        tickets=tickets,
        search_query=search_query,
        status_filter=status_filter,
        priority_filter=priority_filter,
        category_filter=category_filter,
        sentiment_filter=sentiment_filter,
        team_filter=team_filter,
        escalated_only=escalated_only,
        date_range=date_range,
        statuses=TicketStatus.ALL,
        priorities=TicketPriority.ALL,
        categories=TicketCategory.ALL,
        sentiments=["Positive", "Neutral", "Negative", "Very Negative"],
        teams=SupportTeam.ALL,
    )


@main_bp.route("/admin/tickets/<ticket_number>", methods=["GET", "POST"])
@support_required
def admin_ticket_detail(ticket_number):
    """Admin full ticket view and management actions."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()
    actor_name = session.get("user_name", "Support Agent")
    user_id = session.get("user_id")

    if request.method == "POST":
        action = request.form.get("action")

        try:
            if action == "reanalyze":
                from app.services.ai.complaint_analyzer import ComplaintAnalyzer
                analyzer = ComplaintAnalyzer()
                analysis = analyzer.analyze_and_store(ticket)
                if analysis.status == "COMPLETED":
                    flash(f"AI analysis completed! Category='{analysis.category}', Priority='{analysis.priority}', Sentiment='{analysis.sentiment}'.", "success")
                elif analysis.status == "UNAVAILABLE":
                    flash("AI analysis is currently unavailable because no API key is configured in .env.", "warning")
                else:
                    flash(f"AI analysis could not be completed: {analysis.reason}", "danger")

            elif action == "reply":
                reply_text = request.form.get("message", "").strip()
                if not reply_text:
                    flash("Reply message cannot be empty.", "warning")
                else:
                    add_support_reply(
                        ticket=ticket,
                        sender_id=user_id,
                        sender_name=actor_name,
                        message=reply_text,
                    )
                    flash("Support response posted to customer.", "success")

            elif action == "internal_note":
                note_text = request.form.get("note", "").strip()
                if not note_text:
                    flash("Internal note cannot be empty.", "warning")
                else:
                    add_internal_note(ticket, user_id, actor_name, note_text)
                    flash("Internal note saved (private to staff).", "info")

            elif action == "update_status":
                new_status = request.form.get("status")
                update_ticket_status(ticket, new_status, actor_name, user_id=user_id)
                flash(f"Status updated to '{new_status}'.", "success")

            elif action == "update_priority":
                new_priority = request.form.get("priority")
                update_ticket_priority(ticket, new_priority, actor_name, user_id=user_id)
                flash(f"Priority updated to '{new_priority}'.", "success")

            elif action == "update_category":
                new_category = request.form.get("category")
                update_ticket_category(ticket, new_category, actor_name, user_id=user_id)
                flash(f"Category updated to '{new_category}'.", "success")

            elif action == "update_team":
                new_team = request.form.get("assigned_team")
                update_ticket_team(ticket, new_team, actor_name, user_id=user_id)
                flash(f"Assigned team updated to '{new_team}'.", "success")

            elif action == "escalate":
                reason = request.form.get("reason", "").strip()
                target_team = request.form.get("target_team", SupportTeam.SENIOR_SUPPORT)
                escalate_ticket(ticket, reason, actor_name, target_team, user_id=user_id)
                flash(f"Ticket successfully escalated to '{ticket.assigned_team}'.", "danger")

            elif action == "reopen":
                reason = request.form.get("reason", "").strip()
                reopen_ticket(ticket, actor_id=user_id, actor_name=actor_name, reason=reason)
                flash("Ticket reopened to 'In Progress'.", "success")

            return redirect(url_for("main.admin_ticket_detail", ticket_number=ticket.ticket_number))

        except ValueError as ve:
            flash(str(ve), "danger")
            return redirect(url_for("main.admin_ticket_detail", ticket_number=ticket.ticket_number))
        except Exception as e:
            logger.error(f"Error handling admin ticket action '{action}': {str(e)}", exc_info=True)
            flash(f"Error processing request: {str(e)}", "danger")
            return redirect(url_for("main.admin_ticket_detail", ticket_number=ticket.ticket_number))

    return render_template(
        "admin/ticket_detail.html",
        ticket=ticket,
        statuses=TicketStatus.ALL,
        priorities=TicketPriority.ALL,
        categories=TicketCategory.ALL,
        teams=SupportTeam.ALL,
    )


# ---------------------------------------------------------------------------
# In-App Notifications Routes
# ---------------------------------------------------------------------------

@main_bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@login_required
def notification_read(notif_id: int):
    """Mark a notification as read and redirect to its link or current page."""
    user_id = session.get("user_id")
    notif = db.session.get(Notification, notif_id)
    if notif and notif.user_id == user_id:
        mark_as_read(notif.id, user_id)
        if notif.link:
            return redirect(notif.link)

    return redirect(request.referrer or url_for("main.dashboard"))


@main_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notification_read_all():
    """Mark all notifications as read for current user."""
    user_id = session.get("user_id")
    mark_all_as_read(user_id)
    flash("All notifications marked as read.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


# ---------------------------------------------------------------------------
# RAG Knowledge Base Management Routes (Support / Admin)
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {"txt", "md", "pdf", "docx"}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@main_bp.route("/admin/knowledge-base")
@support_required
def admin_knowledge_base():
    """Knowledge base document list and vector indexing dashboard."""
    category_filter = request.args.get("category", "").strip()
    status_filter = request.args.get("status", "").strip()
    search_query = request.args.get("q", "").strip()

    query = KnowledgeDocument.query

    if category_filter:
        query = query.filter_by(category=category_filter)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if search_query:
        query = query.filter(
            (KnowledgeDocument.title.ilike(f"%{search_query}%"))
            | (KnowledgeDocument.filename.ilike(f"%{search_query}%"))
            | (KnowledgeDocument.description.ilike(f"%{search_query}%"))
        )

    documents = query.order_by(KnowledgeDocument.created_at.desc()).all()
    total_docs = KnowledgeDocument.query.count()
    active_docs = KnowledgeDocument.query.filter_by(status=DocumentStatus.ACTIVE).count()
    total_chunks = db.session.query(db.func.sum(KnowledgeDocument.chunk_count)).scalar() or 0

    return render_template(
        "admin/knowledge_base.html",
        documents=documents,
        total_docs=total_docs,
        active_docs=active_docs,
        total_chunks=total_chunks,
        category_filter=category_filter,
        status_filter=status_filter,
        search_query=search_query,
    )


@main_bp.route("/admin/knowledge-base/upload", methods=["POST"])
@support_required
def admin_knowledge_upload():
    """Upload and index a new knowledge base document with security hardening."""
    if "file" not in request.files:
        flash("No file part in the request.", "danger")
        return redirect(url_for("main.admin_knowledge_base"))

    file = request.files["file"]
    if file.filename == "":
        flash("No file selected for upload.", "danger")
        return redirect(url_for("main.admin_knowledge_base"))

    if not allowed_file(file.filename):
        flash("Invalid file format. Supported formats: .txt, .md, .pdf, .docx", "danger")
        return redirect(url_for("main.admin_knowledge_base"))

    title = request.form.get("title", "").strip() or file.filename.rsplit(".", 1)[0].replace("_", " ").title()
    category = request.form.get("category", "General").strip()
    description = request.form.get("description", "").strip()

    filename = secure_filename(file.filename)
    if not filename:
        flash("Invalid or malicious filename.", "danger")
        return redirect(url_for("main.admin_knowledge_base"))

    upload_folder = os.path.join(current_app.instance_path, "knowledge_docs")
    os.makedirs(upload_folder, exist_ok=True)
    saved_path = os.path.join(upload_folder, filename)

    try:
        file.save(saved_path)
        rag_service = RAGService()
        doc = rag_service.ingest_document(
            file_path=saved_path,
            title=title,
            category=category,
            description=description,
        )
        flash(f"Document '{doc.title}' successfully uploaded and indexed ({doc.chunk_count} chunks).", "success")
    except Exception as e:
        logger.error(f"Failed to ingest document '{filename}': {str(e)}", exc_info=True)
        flash(f"Failed to index document: {str(e)}", "danger")

    return redirect(url_for("main.admin_knowledge_base"))


@main_bp.route("/admin/knowledge-base/<int:doc_id>")
@support_required
def admin_knowledge_detail(doc_id: int):
    """Inspect chunks and metadata for a specific knowledge document."""
    doc = db.session.get(KnowledgeDocument, doc_id)
    if not doc:
        flash("Document not found.", "warning")
        return redirect(url_for("main.admin_knowledge_base"))

    chunks = KnowledgeChunk.query.filter_by(document_id=doc.id).order_by(KnowledgeChunk.chunk_index.asc()).all()
    return render_template(
        "admin/document_detail.html",
        document=doc,
        chunks=chunks,
    )


@main_bp.route("/admin/knowledge-base/<int:doc_id>/reindex", methods=["POST"])
@support_required
def admin_knowledge_reindex(doc_id: int):
    """Reindex an existing document."""
    doc = db.session.get(KnowledgeDocument, doc_id)
    if not doc:
        flash("Document not found.", "warning")
        return redirect(url_for("main.admin_knowledge_base"))

    if not os.path.exists(doc.file_path):
        flash(f"Source file not found on disk: {doc.file_path}", "danger")
        return redirect(url_for("main.admin_knowledge_base"))

    try:
        rag_service = RAGService()
        rag_service.ingest_document(
            file_path=doc.file_path,
            title=doc.title,
            category=doc.category,
            description=doc.description,
            document_id=doc.id,
        )
        flash(f"Document '{doc.title}' successfully re-indexed.", "success")
    except Exception as e:
        logger.error(f"Re-indexing failed for document {doc_id}: {str(e)}", exc_info=True)
        flash(f"Re-indexing failed: {str(e)}", "danger")

    return redirect(url_for("main.admin_knowledge_detail", doc_id=doc.id))


@main_bp.route("/admin/knowledge-base/<int:doc_id>/delete", methods=["POST"])
@support_required
def admin_knowledge_delete(doc_id: int):
    """Delete a document and its chunks from vector store."""
    doc = db.session.get(KnowledgeDocument, doc_id)
    if not doc:
        flash("Document not found.", "warning")
        return redirect(url_for("main.admin_knowledge_base"))

    try:
        title = doc.title
        rag_service = RAGService()
        rag_service.delete_document(doc.id)
        flash(f"Document '{title}' deleted from database and vector index.", "success")
    except Exception as e:
        logger.error(f"Failed to delete document {doc_id}: {str(e)}", exc_info=True)
        flash(f"Error deleting document: {str(e)}", "danger")

    return redirect(url_for("main.admin_knowledge_base"))


@main_bp.route("/admin/knowledge-base/rebuild", methods=["POST"])
@support_required
def admin_knowledge_rebuild():
    """Rebuild the entire FAISS vector index from active documents."""
    try:
        rag_service = RAGService()
        rag_service.rebuild_index()
        flash("Vector store index successfully rebuilt from active database documents.", "success")
    except Exception as e:
        logger.error(f"Vector index rebuild failed: {str(e)}", exc_info=True)
        flash(f"Vector rebuild failed: {str(e)}", "danger")

    return redirect(url_for("main.admin_knowledge_base"))


# ---------------------------------------------------------------------------
# RAG Ticket Resolution Trigger Routes
# ---------------------------------------------------------------------------

@main_bp.route("/tickets/<ticket_number>/resolve", methods=["POST"])
@login_required
def customer_ticket_resolve(ticket_number: str):
    """Customer-facing trigger to re-run grounded AI resolution."""
    user_id = session.get("user_id")
    ticket = Ticket.query.filter_by(ticket_number=ticket_number, user_id=user_id).first_or_404()

    try:
        rag_service = RAGService()
        rag_service.resolve_ticket(ticket, force_regenerate=True)
        flash("AI resolution generated using current knowledge base.", "success")
    except Exception as e:
        logger.error(f"Failed to generate customer RAG resolution for ticket {ticket_number}: {str(e)}", exc_info=True)
        flash("Could not generate AI resolution at this time.", "danger")

    return redirect(url_for("main.customer_ticket_detail", ticket_number=ticket.ticket_number))


@main_bp.route("/admin/tickets/<ticket_number>/resolve", methods=["POST"])
@support_required
def admin_ticket_resolve(ticket_number: str):
    """Support/Admin action to re-run grounded AI resolution."""
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()

    try:
        rag_service = RAGService()
        rag_service.resolve_ticket(ticket, force_regenerate=True)
        flash("Grounded AI resolution regenerated successfully.", "success")
    except Exception as e:
        logger.error(f"Failed to generate admin RAG resolution for ticket {ticket_number}: {str(e)}", exc_info=True)
        flash(f"Failed to generate AI resolution: {str(e)}", "danger")

    return redirect(url_for("main.admin_ticket_detail", ticket_number=ticket.ticket_number))


# ---------------------------------------------------------------------------
# Notification Action Routes
# ---------------------------------------------------------------------------

@main_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id: int):
    """Mark a single notification as read."""
    user_id = session.get("user_id")
    mark_as_read(notification_id, user_id)
    return redirect(request.referrer or url_for("main.index"))


@main_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_notifications_read():
    """Mark all notifications for current user as read."""
    user_id = session.get("user_id")
    mark_all_as_read(user_id)
    return redirect(request.referrer or url_for("main.index"))

