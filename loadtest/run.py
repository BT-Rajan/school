"""Load test at design scale (section 15), against a server seeded by loadtest/seed_scale.py.

  1. List queries: each list, search, dashboard and report a role uses, 20 times in a row;
     section 15 asks for list queries under 300 ms.
  2. Mixed load: 50 people at once, each loading a list every second or so, for a minute.
  3. Realtime: 500 open connections (admins and a supervisor); an admin acknowledges reports and
     each connection that may see them should hear within 2 seconds.
  4. Uploads: 20 supervisors' 10-page scans uploaded at once through the resumable upload.

Usage: python loadtest/run.py <base url> <seed.json> [results.json]
"""

import asyncio
import io
import json
import random
import statistics
import sys
import time

import httpx
import pyotp
import websockets
from PIL import Image

BASE, SEED = sys.argv[1], json.load(open(sys.argv[2]))
OUT = sys.argv[3] if len(sys.argv) > 3 else None
results: dict = {}


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


async def sign_in(key: str) -> httpx.AsyncClient:
    user = SEED["users"][key]
    client = httpx.AsyncClient(base_url=BASE, timeout=60)
    start = await client.post("/api/auth/login", json={"email": user["email"], "password": SEED["password"]})
    start.raise_for_status()
    r = await client.post(
        "/api/auth/login/verify",
        json={"challenge": start.json()["challenge"], "code": pyotp.TOTP(user["secret"]).now()},
    )
    r.raise_for_status()
    client.headers["X-CSRF-Token"] = client.cookies["sces_csrf"]
    return client


async def timed(client: httpx.AsyncClient, path: str) -> float:
    t = time.perf_counter()
    r = await client.get(path)
    elapsed = (time.perf_counter() - t) * 1000
    if r.status_code != 200:
        raise RuntimeError(f"{path}: {r.status_code} {r.text[:200]}")
    return elapsed


LISTS = {
    "admin": [
        "/api/documents?page=1&page_size=50",
        "/api/documents?page=200&page_size=50",
        "/api/documents?q=L07-03&page_size=50",
        "/api/documents?status=acknowledged&page_size=50",
        "/api/evaluations?page_size=50",
        "/api/schools?page_size=50",
        "/api/schools?q=Scale%20School%2013&page_size=50",
        "/api/teachers?page_size=50",
        "/api/teachers?q=Teacher%20L19&page_size=50",
        "/api/supervisors?page_size=50",
        "/api/requests?page_size=50",
        "/api/search?q=L12-05",
        "/api/admin/audit?page_size=50",
        "/api/dashboard",
        "/api/standard-reports/evaluations_by_school",
        "/api/standard-reports/scanned_reports?group=school",
        "/api/standard-reports/request_completion",
    ],
    "head": [
        "/api/evaluations?page_size=50",
        "/api/teachers?page_size=50",
        "/api/schools?page_size=50",
        "/api/dashboard",
    ],
    "supa": [
        "/api/documents?page_size=50",
        "/api/evaluations?page_size=50",
        "/api/documents/dashboard",
        "/api/dashboard",
    ],
}
LIST_ONLY = (
    "/api/documents",
    "/api/evaluations",
    "/api/schools",
    "/api/teachers",
    "/api/supervisors",
    "/api/requests",
    "/api/admin/audit",
)


async def list_latency(clients: dict[str, httpx.AsyncClient]) -> None:
    rows = []
    for role, paths in LISTS.items():
        for path in paths:
            await timed(clients[role], path)  # warm
            times = [await timed(clients[role], path) for _ in range(20)]
            rows.append(
                {
                    "role": role,
                    "path": path,
                    "p50": round(statistics.median(times)),
                    "p95": round(pct(times, 95)),
                    "max": round(max(times)),
                }
            )
            print(f"{role:6} {path:70} p50 {rows[-1]['p50']:5} ms  p95 {rows[-1]['p95']:5} ms", flush=True)
    lists = [r for r in rows if r["path"].split("?")[0] in LIST_ONLY]
    results["latency"] = rows
    results["lists_p95_max"] = max(r["p95"] for r in lists)


async def mixed_load(clients: dict[str, httpx.AsyncClient], users: int = 50, seconds: int = 60) -> None:
    times: list[float] = []
    errors = 0
    stop = time.perf_counter() + seconds
    paths = [(role, p) for role, ps in LISTS.items() for p in ps if not p.startswith("/api/standard-reports")]

    async def person(i: int) -> None:
        nonlocal errors
        rng = random.Random(i)  # noqa: S311 - load pattern, not a secret
        while time.perf_counter() < stop:
            role, path = rng.choice(paths)
            try:
                times.append(await timed(clients[role], path))
            except Exception:  # noqa: BLE001 - counted
                errors += 1
            await asyncio.sleep(rng.uniform(0.5, 1.5))

    await asyncio.gather(*(person(i) for i in range(users)))
    results["mixed"] = {
        "users": users,
        "seconds": seconds,
        "requests": len(times),
        "errors": errors,
        "per_second": round(len(times) / seconds, 1),
        "p50": round(statistics.median(times)),
        "p95": round(pct(times, 95)),
    }
    print("mixed:", results["mixed"], flush=True)


async def realtime(clients: dict[str, httpx.AsyncClient], connections: int = 500, events: int = 10) -> None:
    ws_base = BASE.replace("http", "ws", 1) + "/api/realtime/ws"
    origin = BASE
    received: dict[int, list[float]] = {}
    sockets = []
    # Connections from the admin and from the report's owner, who may see each change, and from
    # hundreds of other supervisors, who may not: as many people as the district has.
    others = SEED["sessions"][: connections - 100]
    cookies = [("admin", clients["admin"].cookies["sces_session"])] * 50
    cookies += [("supa", clients["supa"].cookies["sces_session"])] * 50
    cookies += [("other", token) for token in others]
    for i, (role, token) in enumerate(cookies):
        ws = await websockets.connect(
            ws_base, additional_headers={"Cookie": f"sces_session={token}", "Origin": origin}, max_size=2**20
        )
        sockets.append((i, role, ws))
    print(f"realtime: {len(sockets)} connections open", flush=True)

    leaked: list[int] = []

    async def listen(i: int, role: str, ws) -> None:
        try:
            async for message in ws:
                data = json.loads(message)
                if data.get("type") == "changed" and data.get("entity") == "document":
                    if role == "other":
                        leaked.append(int(data["id"]))
                    else:
                        received.setdefault(int(data["id"]), []).append(time.perf_counter())
        except websockets.ConnectionClosed:
            pass

    listeners = [asyncio.create_task(listen(i, role, ws)) for i, role, ws in sockets]
    await asyncio.sleep(2)
    # Reports of the signed-in supervisor waiting for review: the admin and the owner may see them.
    page = (await clients["supa"].get("/api/documents?status=submitted&page_size=50")).json()["items"][:events]
    sent: dict[int, float] = {}
    for doc in page:
        detail = (await clients["admin"].get(f"/api/documents/{doc['id']}")).json()
        sent[doc["id"]] = time.perf_counter()
        r = await clients["admin"].post(f"/api/documents/{doc['id']}/acknowledge", json={"version": detail["version"]})
        r.raise_for_status()
        await asyncio.sleep(0.5)
    await asyncio.sleep(3)
    delays = [(t - sent[d]) * 1000 for d, ts in received.items() if d in sent for t in ts]
    per_event = {d: len(ts) for d, ts in received.items() if d in sent}
    results["realtime"] = {
        "connections": len(sockets),
        "events": len(sent),
        "deliveries": len(delays),
        "expected": len(sent) * sum(1 for _, role, _ in sockets if role != "other"),
        "to_others": len(leaked),
        "p50_ms": round(statistics.median(delays)) if delays else None,
        "p95_ms": round(pct(delays, 95)) if delays else None,
        "max_ms": round(max(delays)) if delays else None,
        "min_per_event": min(per_event.values()) if per_event else 0,
    }
    print("realtime:", results["realtime"], flush=True)
    for t in listeners:
        t.cancel()
    for _, _, ws in sockets:
        await ws.close()


def scan_pdf_pages() -> bytes:
    """A 10-page PDF the size a phone scan makes: each page a JPEG at about 200 dpi."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")

    for _ in range(10):
        img = Image.effect_noise((827, 1170), 40).convert("RGB").resize((1654, 2339))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=60)
        pdf.add_page()
        pdf.image(io.BytesIO(buf.getvalue()), x=0, y=0, w=210, h=297)

    return bytes(pdf.output())


async def uploads(clients: dict[str, httpx.AsyncClient], count: int = 20) -> None:
    content = scan_pdf_pages()
    chunk = 1024 * 1024
    supa = clients["supa"]

    async def one(i: int) -> float:
        t = time.perf_counter()
        body = content + f"%{i}".encode()  # a different file each time
        start = await supa.post(
            "/api/uploads", json={"client_key": f"load-{time.time()}-{i}", "name": f"scan-{i}.pdf", "size": len(body)}
        )
        start.raise_for_status()
        up = start.json()
        offset = 0
        while offset < len(body):
            r = await supa.put(
                f"/api/uploads/{up['id']}/chunks?offset={offset}",
                content=body[offset : offset + chunk],
                headers={"Content-Type": "application/octet-stream"},
            )
            r.raise_for_status()
            offset = r.json()["received"]
        done = await supa.post(f"/api/uploads/{up['id']}/complete")
        done.raise_for_status()
        return (time.perf_counter() - t) * 1000

    times = await asyncio.gather(*(one(i) for i in range(count)))
    results["uploads"] = {
        "count": count,
        "size_mb": round(len(content) / 1024 / 1024, 2),
        "p50_ms": round(statistics.median(times)),
        "max_ms": round(max(times)),
    }
    print("uploads:", results["uploads"], flush=True)


async def main() -> None:
    clients = {}
    for key in ("admin", "head", "supa"):
        clients[key] = await sign_in(key)
    await list_latency(clients)
    await mixed_load(clients)
    await realtime(clients)
    await uploads(clients)
    for c in clients.values():
        await c.aclose()
    if OUT:
        json.dump(results, open(OUT, "w"), indent=2)


asyncio.run(main())
