"""The API serving the built web app itself (install.sh, no Caddy in front)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import web


def test_serves_the_app_and_never_outside_it(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>app</html>")
    (root / "assets" / "app-1234.js").write_text("console.log(1)")
    (root / "sw.js").write_text("// worker")
    (tmp_path / "secret.txt").write_text("not for the web")
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    web.mount(app, str(root))
    client = TestClient(app)

    asset = client.get("/assets/app-1234.js")
    assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
    worker = client.get("/sw.js")
    assert worker.text == "// worker" and worker.headers["cache-control"] == "no-cache"
    # The app's own routes load the page, which then routes itself.
    page = client.get("/reports/42")
    assert page.text == "<html>app</html>" and "frame-ancestors 'none'" in page.headers["content-security-policy"]
    # Nothing outside the folder, however the path is written.
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        assert "not for the web" not in client.get(path).text
    # API paths are never answered with the page.
    assert client.get("/api/ping").json() == {"ok": True}
    assert client.get("/api/unknown").status_code == 404
