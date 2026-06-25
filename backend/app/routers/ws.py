"""WebSocket endpoint — live connection for authenticated users."""
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

from app.database import async_session
from app.auth.jwt_handler import decode_access_token
from app.models.user import User
from app.services.ws_manager import manager, Connection

router = APIRouter()


@router.websocket("/ws/connect")
async def ws_connect(
    websocket: WebSocket,
    token: str = Query(...),
):
    """
    Authenticate via JWT token query param, then maintain a live WebSocket connection.

    Client can send JSON messages:
      {"type": "presence", "entity_type": "ticket", "entity_id": "<uuid>"}
      {"type": "ping"}

    Server pushes JSON messages:
      {"type": "notification", "notification": {...}}
      {"type": "ticket_updated", "ticket_id": "...", "status": "..."}
      {"type": "presence_update", "entity_type": "...", "entity_id": "...", "viewers": [...]}
      {"type": "pong"}
    """
    payload = decode_access_token(token)
    if payload is None:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id_str = payload.get("sub")
    if not user_id_str:
        await websocket.close(code=4001, reason="Invalid token")
        return

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id_str)))
        user = result.scalar_one_or_none()

    if not user or not user.is_active:
        await websocket.close(code=4003, reason="User not found or inactive")
        return

    conn = Connection(
        websocket=websocket,
        user_id=user.id,
        org_id=user.organization_id,
    )
    await manager.connect(conn)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "presence" and conn.org_id:
                entity_type = data.get("entity_type", "")
                entity_id = data.get("entity_id", "")
                conn.page = f"{entity_type}:{entity_id}" if entity_type and entity_id else None

                # Broadcast updated viewer list to all org members on this entity
                viewers = manager.get_presence(conn.org_id, entity_type, entity_id)
                await manager.broadcast_to_org(conn.org_id, {
                    "type": "presence_update",
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "viewers": viewers,
                })

    except WebSocketDisconnect:
        pass
    finally:
        old_page = conn.page
        manager.disconnect(conn)
        # Notify others that this user left the page
        if old_page and conn.org_id:
            parts = old_page.split(":", 1)
            if len(parts) == 2:
                entity_type, entity_id = parts
                viewers = manager.get_presence(conn.org_id, entity_type, entity_id)
                await manager.broadcast_to_org(conn.org_id, {
                    "type": "presence_update",
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "viewers": viewers,
                })
