"""Utility functions for creating in-app notifications."""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import Notification


async def create_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
) -> None:
    """Insert a notification row for the given user and push it over WebSocket. Best-effort."""
    notif = Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(notif)
    await db.commit()

    # Push to connected WebSocket clients for this user (best-effort)
    try:
        from app.services.ws_manager import manager
        await manager.send_to_user(user_id, {
            "type": "notification",
            "notification": {
                "id": str(notif.id),
                "kind": kind,
                "title": title,
                "body": body,
                "entity_type": entity_type,
                "entity_id": str(entity_id) if entity_id else None,
                "is_read": False,
                "created_at": notif.created_at.isoformat() if notif.created_at else None,
            },
        })
    except Exception:
        pass

