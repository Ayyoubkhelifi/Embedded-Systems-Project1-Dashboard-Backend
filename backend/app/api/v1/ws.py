import uuid

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.api.deps import authenticate_ws_token
from app.core.errors import ApiError
from app.db.session import get_db
from app.services.realtime import manager

router = APIRouter(prefix="/ws", tags=["realtime"])


@router.websocket("/telemetry")
async def ws_telemetry(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Real-time telemetry/alert stream. Auth: `?token=<access_token>`.

    The bootstrap cookie auth path cannot complete a cross-origin WS upgrade,
    so the dashboard connects with its short-lived access token query param.
    """
    session = None
    session_gen = get_db()
    try:
        session = await session_gen.__anext__()
        user = await authenticate_ws_token(token, session)
    except ApiError as exc:
        await websocket.close(code=4401, reason=exc.message)
        return
    finally:
        if session is not None:
            try:
                await session_gen.aclose()
            except Exception:  # noqa: BLE001
                pass

    conn_id = uuid.uuid4().hex
    if not await manager.reserve(conn_id):
        await websocket.close(code=4429, reason="Too many WebSocket connections")
        return
    try:
        await websocket.accept()
        await manager.register(websocket, conn_id)
        await websocket.send_text(
            '{"type":"hello","data":{"user":'
            f'"{user.username}"'
            ',"conn_id":"' + conn_id + '"}}'
        )
        while True:
            # Inbound traffic: only pings/disconnects are supported.
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text('{"type":"pong","data":{}}')
            elif message == "close":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(conn_id)
