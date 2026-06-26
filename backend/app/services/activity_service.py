import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.activity_log import ActivityLog
from app.models.user import User


async def log_activity(
    db: AsyncSession,
    *,
    user: User,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    entity_label: str,
    changes: dict | None = None,
) -> None:
    entry = ActivityLog(
        organization_id=user.organization_id,
        user_id=user.id,
        user_display_name=user.display_name or user.email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        changes=changes,
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception:
        # Best-effort logging: if the insert fails (e.g. a constraint/DB error),
        # roll back so the aborted transaction does not poison the caller's
        # session and cause a spurious 500 on the subsequent response query.
        await db.rollback()
        raise


def compute_changes(old_values: dict, new_values: dict) -> dict | None:
    """Compare old vs new field values and return a dict of changes."""
    changes = {}
    for key, new_val in new_values.items():
        old_val = old_values.get(key)
        if old_val != new_val:
            changes[key] = {"old": _serialize(old_val), "new": _serialize(new_val)}
    return changes if changes else None


def _serialize(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return str(val)
    return val
