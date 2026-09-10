import logging
from typing import List, Optional
from datetime import datetime, timezone
from app.extensions import db
from app.models.user import User
from app.models.notification import Notification, NotificationType

logger = logging.getLogger(__name__)


def create_notification(
    user_id: int,
    title: str,
    message: str,
    notification_type: str = NotificationType.SYSTEM_ALERT,
    ticket_id: Optional[int] = None,
    link: Optional[str] = None,
) -> Notification:
    """Create an in-app notification for a customer or staff member."""
    try:
        user = db.session.get(User, user_id)
        if not user:
            logger.warning(f"Cannot create notification for non-existent user_id {user_id}")
            return None

        notif = Notification(
            user_id=user.id,
            ticket_id=ticket_id,
            type=notification_type if notification_type in NotificationType.ALL else NotificationType.SYSTEM_ALERT,
            title=title.strip()[:200],
            message=message.strip(),
            link=link.strip() if link else None,
            is_read=False,
        )
        db.session.add(notif)
        db.session.commit()
        return notif
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to create notification: {str(e)}", exc_info=True)
        return None


def notify_support_staff(
    title: str,
    message: str,
    notification_type: str = NotificationType.TICKET_ESCALATED,
    ticket_id: Optional[int] = None,
    link: Optional[str] = None,
) -> int:
    """Broadcast an operational notification to all support and admin users."""
    try:
        support_users = User.query.filter(User.role.in_(["support", "admin"])).all()
        created_count = 0
        for staff in support_users:
            notif = Notification(
                user_id=staff.id,
                ticket_id=ticket_id,
                type=notification_type,
                title=title.strip()[:200],
                message=message.strip(),
                link=link.strip() if link else None,
                is_read=False,
            )
            db.session.add(notif)
            created_count += 1
        db.session.commit()
        return created_count
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to notify support staff: {str(e)}", exc_info=True)
        return 0


def get_user_notifications(user_id: int, limit: int = 15, unread_only: bool = False) -> List[Notification]:
    """Fetch recent notifications for a user."""
    query = Notification.query.filter_by(user_id=user_id)
    if unread_only:
        query = query.filter_by(is_read=False)
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


def get_unread_count(user_id: int) -> int:
    """Get the number of unread notifications for a user."""
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def mark_as_read(notification_id: int, user_id: int) -> bool:
    """Mark a single notification as read, ensuring ownership."""
    notif = db.session.get(Notification, notification_id)
    if not notif or notif.user_id != user_id:
        return False

    notif.is_read = True
    db.session.commit()
    return True


def mark_all_as_read(user_id: int) -> int:
    """Mark all unread notifications as read for a given user."""
    updated = Notification.query.filter_by(user_id=user_id, is_read=False).update(
        {"is_read": True},
        synchronize_session=False,
    )
    db.session.commit()
    return updated
