import datetime
import decimal
import enum
import logging
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.activity_log import ActivityLog
from app.models.user import User

log = logging.getLogger(__name__)


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
        # The caller has already committed its own work, so failing here must
        # never surface as a failed request. Roll back so the aborted
        # transaction cannot poison the caller's session, then swallow.
        log.exception(
            "Activity logging failed for %s %s (%s)", action, entity_type, entity_id
        )
        try:
            await db.rollback()
        except Exception:
            log.exception("Rollback after failed activity logging also failed")


def compute_changes(old_values: dict, new_values: dict) -> dict | None:
    """Compare old vs new field values and return a dict of changes."""
    changes = {}
    for key, new_val in new_values.items():
        old_val = old_values.get(key)
        if old_val != new_val:
            changes[key] = {"old": _serialize(old_val), "new": _serialize(new_val)}
    return changes if changes else None


def _serialize(val):
    """Coerce a column value into something the JSONB `changes` column accepts."""
    if val is None or isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, enum.Enum):
        return _serialize(val.value)
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, decimal.Decimal):
        # str keeps the exact value; float would round money.
        return str(val)
    if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
        return val.isoformat()
    if isinstance(val, (list, tuple, set)):
        return [_serialize(v) for v in val]
    if isinstance(val, dict):
        return {str(k): _serialize(v) for k, v in val.items()}
    return str(val)
