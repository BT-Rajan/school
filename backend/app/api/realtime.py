"""Live updates: WebSocket, with Server-Sent Events as the fallback (FR-RT1 to FR-RT3).

Both authenticate with the session cookie. Browsers send cookies on a cross-site
WebSocket too, so the WebSocket also checks the Origin header. Each connection is
re-checked every minute without counting as activity, and closes when its session
ends, so a signed-out or idle screen stops receiving events.
"""

import asyncio
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.auth import service as auth
from app.auth.deps import SESSION_COOKIE, Principal, current_principal
from app.config import get_settings
from app.db import session_factory
from app.realtime.broadcaster import broadcaster

router = APIRouter(prefix="/api/realtime", tags=["realtime"])

KEEPALIVE_SECONDS = 25
RECHECK_SECONDS = 60


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    allowed = urlsplit(get_settings().public_base_url)
    sent = urlsplit(origin)
    return (sent.scheme, sent.netloc) == (allowed.scheme, allowed.netloc)


def _open_session(token: str | None) -> tuple[int, int] | None:
    if not token:
        return None
    with session_factory()() as db:
        found = auth.find_session(db, token)
        return (found[1].id, found[0].id) if found else None


def _still_valid(session_id: int) -> bool:
    with session_factory()() as db:
        return auth.session_still_valid(db, session_id)


async def _messages(connection):
    """Events for this connection, with keepalives, until its session ends."""
    waited = 0.0
    while True:
        try:
            yield await asyncio.wait_for(connection.outbox.get(), timeout=KEEPALIVE_SECONDS)
        except TimeoutError:
            waited += KEEPALIVE_SECONDS
            if waited >= RECHECK_SECONDS:
                waited = 0.0
                if not await run_in_threadpool(_still_valid, connection.session_id):
                    return
            yield {"type": "ping"}


@router.websocket("/ws")
async def websocket(socket: WebSocket):
    if not _origin_allowed(socket.headers.get("origin")):
        await socket.close(code=4403)
        return
    opened = await run_in_threadpool(_open_session, socket.cookies.get(SESSION_COOKIE))
    if opened is None:
        await socket.close(code=4401)
        return
    await socket.accept()
    connection = broadcaster.connect(*opened)
    try:
        await socket.send_json({"type": "ready"})
        async for message in _messages(connection):
            await socket.send_json(message)
        await socket.close(code=4401)
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.disconnect(connection)


@router.get("/events")
async def server_sent_events(request: Request, principal: Principal = Depends(current_principal)):
    connection = broadcaster.connect(principal.user.id, principal.session.id)

    async def stream():
        try:
            yield "retry: 3000\n\n" + _sse({"type": "ready"})
            async for message in _messages(connection):
                if await request.is_disconnected():
                    return
                yield _sse(message)
        finally:
            broadcaster.disconnect(connection)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _sse(message: dict) -> str:
    return f"data: {json.dumps(message)}\n\n"
