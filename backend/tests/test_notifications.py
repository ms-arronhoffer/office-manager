"""Tests for the Notifications API (clear-all in particular)."""
import pytest
from sqlalchemy import select

from app.models.notification import Notification
from app.models.user import User
from tests.conftest import auth_headers


async def _seed(db, user: User, n: int) -> None:
    for i in range(n):
        db.add(Notification(user_id=user.id, kind="test", title=f"N{i}"))
    await db.commit()


@pytest.mark.asyncio
async def test_clear_all_notifications(client, viewer_user: User, db_session):
    await _seed(db_session, viewer_user, 3)

    listing = await client.get("/api/v1/notifications", headers=auth_headers(viewer_user))
    assert len(listing.json()) == 3

    resp = await client.delete("/api/v1/notifications", headers=auth_headers(viewer_user))
    assert resp.status_code == 204

    rows = (
        await db_session.execute(
            select(Notification).where(Notification.user_id == viewer_user.id)
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_clear_all_only_affects_current_user(
    client, viewer_user: User, admin_user: User, db_session
):
    await _seed(db_session, viewer_user, 2)
    await _seed(db_session, admin_user, 2)

    resp = await client.delete("/api/v1/notifications", headers=auth_headers(viewer_user))
    assert resp.status_code == 204

    others = (
        await db_session.execute(
            select(Notification).where(Notification.user_id == admin_user.id)
        )
    ).scalars().all()
    assert len(others) == 2
