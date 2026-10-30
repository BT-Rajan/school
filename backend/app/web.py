"""Serving the built web app from the API process, for installs without the Caddy front end
(install.sh). The same rules as frontend/Caddyfile: hashed assets are cached for a year,
everything else, including the page and the service worker, is fetched fresh, and any path
that is not a file gets index.html so the app's own routes work on reload.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# The page's rules, as in the Caddyfile. API responses keep their own stricter ones.
PAGE_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def mount(app: FastAPI, web_root: str) -> None:
    root = Path(web_root).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"SCES_WEB_ROOT has no index.html: {root}")

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            target = index
        cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return FileResponse(target, headers={"Cache-Control": cache, "Content-Security-Policy": PAGE_CSP})
