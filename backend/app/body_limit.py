"""Refuse oversized request bodies before they are read (section 15).

Multipart uploads would otherwise be spooled to disk in full before the route can
check the size, so a single request could fill the server's disk. A declared
Content-Length over the limit is refused at once; a body sent without one is
counted as it arrives and stopped at the limit.
"""

import json
import re

from app.config import get_settings
from app.errors import AppError

_UPLOAD_PATHS = re.compile(r"^/api/(files|imports/[a-z_]+/preview|uploads/\d+/chunks)$")


def _limit(path: str) -> int:
    settings = get_settings()
    if _UPLOAD_PATHS.match(path):
        return settings.max_upload_request_mb * 1024 * 1024
    return settings.max_json_request_kb * 1024


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = _limit(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            body = json.dumps({"error": {"code": "request_too_large", "detail": {"max_bytes": limit}}}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        received = 0

        async def counted():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Raised inside the route, so the app's error handler answers 413.
                    raise AppError(413, "request_too_large", {"max_bytes": limit})
            return message

        await self.app(scope, counted, send)
