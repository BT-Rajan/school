import io
import os
import socket
import struct
import threading

import pikepdf
import pytest
from cryptography.exceptions import InvalidTag
from PIL import Image
from sqlalchemy import select

from app.db import session_factory
from app.files import service
from app.files.scanner import EICAR, ClamdScanner, ScannerUnavailable
from app.models import AuditLog, MfaMethod, Role
from app.models.files import StoredFile

from .helpers import deliver_mail, login, make_user, signed_in

# Builders ------------------------------------------------------------------------


def pdf_bytes(
    pages: int = 1,
    *,
    javascript: bool = False,
    attachment: bool = False,
    uri_link: bool = False,
    extra_text: bytes = b"",
) -> bytes:
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(200, 200))
    if extra_text:
        page = pdf.pages[0]
        page.obj.Contents = pdf.make_stream(b"% " + extra_text + b"\nBT ET")
    if javascript:
        action = pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert('x')")))
        pdf.Root.OpenAction = action
        pdf.Root.Names = pikepdf.Dictionary(
            JavaScript=pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String("a"), action]))
        )
    if attachment:
        names = pdf.Root.get("/Names") or pikepdf.Dictionary()
        spec = pikepdf.AttachedFileSpec(pdf, b"MZ fake executable", mime_type="application/octet-stream")
        pdf.attachments["payload.exe"] = spec
        del names  # attachments API writes /Names /EmbeddedFiles itself
    if uri_link:
        link = pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([0, 0, 50, 50]),
            A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String("https://evil.example")),
        )
        pdf.pages[0].obj.Annots = pikepdf.Array([pdf.make_indirect(link)])
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def jpeg_with_gps() -> bytes:
    image = Image.new("RGB", (40, 30), "red")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (29.0, 22.0, 30.0)
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    return out.getvalue()


def tiff_pages(n: int) -> bytes:
    frames = [Image.new("L", (60, 80), shade) for shade in range(0, 250, 250 // n)][:n]
    out = io.BytesIO()
    frames[0].save(out, "TIFF", save_all=True, append_images=frames[1:])
    return out.getvalue()


def upload(client, name: str, content: bytes):
    return client.post("/api/files", files={"file": (name, content)})


def scan():
    with session_factory()() as db:
        service.scan_pending(db)


def link(client, file_id: int, disposition: str = "attachment"):
    return client.post(f"/api/files/{file_id}/link", json={"disposition": disposition})


@pytest.fixture
def sup(new_client, outbox):
    client, user = signed_in(new_client, outbox, Role.SUPERVISOR, "sup@example.org")
    return client


# Sanitization ----------------------------------------------------------------------


def test_pdf_active_content_is_removed(sup):
    r = upload(sup, "report.pdf", pdf_bytes(2, javascript=True, attachment=True, uri_link=True))
    assert r.status_code == 201, r.text
    assert r.json()["pages"] == 2 and r.json()["status"] == "pending"
    scan()
    url = link(sup, r.json()["id"]).json()["url"]
    stored = sup.get(url).content
    for marker in (b"/JavaScript", b"/OpenAction", b"/EmbeddedFile", b"/URI", b"app.alert", b"MZ fake"):
        assert marker not in stored, marker
    with pikepdf.open(io.BytesIO(stored)) as pdf:
        assert len(pdf.pages) == 2


def test_forged_extension_and_unknown_types_rejected(sup):
    png = io.BytesIO()
    Image.new("RGB", (5, 5)).save(png, "PNG")
    r = upload(sup, "scan.pdf", png.getvalue())
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_type_mismatch"
    r = upload(sup, "notes.txt", b"just text")
    assert r.json()["error"]["code"] == "file_type_unsupported"
    r = upload(sup, "evil.pdf", b"MZ\x90\x00 windows executable")
    assert r.json()["error"]["code"] == "file_type_unsupported"


def test_encrypted_pdf_rejected(sup):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    out = io.BytesIO()
    pdf.save(out, encryption=pikepdf.Encryption(owner="o", user="u"))
    r = upload(sup, "locked.pdf", out.getvalue())
    assert r.json()["error"]["code"] == "pdf_encrypted"


def test_image_exif_and_gps_removed(sup):
    original = jpeg_with_gps()
    assert Image.open(io.BytesIO(original)).getexif()
    r = upload(sup, "photo.JPG", original)
    assert r.status_code == 201
    scan()
    stored = sup.get(link(sup, r.json()["id"]).json()["url"]).content
    image = Image.open(io.BytesIO(stored))
    assert image.format == "JPEG" and not image.getexif()
    assert b"PhoneMaker" not in stored


def test_multipage_tiff_becomes_pdf(sup):
    r = upload(sup, "scan.tiff", tiff_pages(3))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mime_type"] == "application/pdf" and body["pages"] == 3 and body["name"] == "scan.pdf"


def test_heic_becomes_jpeg(sup):
    out = io.BytesIO()
    Image.new("RGB", (32, 32), "blue").save(out, "HEIF")
    r = upload(sup, "IMG_0001.HEIC", out.getvalue())
    assert r.status_code == 201, r.text
    assert r.json()["mime_type"] == "image/jpeg"


def test_page_and_size_limits(sup, db):
    from app.models import District

    district = db.execute(select(District)).scalar_one()
    district.settings = {**district.settings, "upload_max_pages": 3, "upload_max_mb": 1}
    db.commit()
    assert upload(sup, "big.pdf", pdf_bytes(4)).json()["error"]["code"] == "too_many_pages"
    assert upload(sup, "huge.pdf", b"%PDF-" + b"0" * (1024 * 1024 + 10)).json()["error"]["code"] == "file_too_large"


def test_storage_quota(sup, db):
    from app.models import District

    district = db.execute(select(District)).scalar_one()
    district.settings = {**district.settings, "storage_quota_mb_per_user": 0}
    db.commit()
    assert upload(sup, "a.pdf", pdf_bytes()).json()["error"]["code"] == "storage_quota_exceeded"


# Scanning -----------------------------------------------------------------------------


def test_infected_file_is_quarantined_and_never_served(new_client, outbox, db):
    from app.files import scanner
    from app.files.scanner import ScanResult

    class Flags:
        def scan(self, content):
            return ScanResult(False, "Eicar-Test-Signature")

    scanner.set_scanner(Flags())
    make_user(Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    client, _ = signed_in(new_client, outbox, Role.SUPERVISOR, "sup@example.org")
    r = upload(client, "virus.pdf", pdf_bytes())
    file_id = r.json()["id"]
    # Not served while the scan is pending.
    assert link(client, file_id).json()["error"]["code"] == "file_not_ready"
    scan()
    assert client.get(f"/api/files/{file_id}").json()["status"] == "quarantined"
    assert link(client, file_id).json()["error"]["code"] == "file_quarantined"
    entry = db.execute(select(AuditLog).where(AuditLog.action == "file.quarantined")).scalar_one()
    assert entry.after["signature"] == "Eicar-Test-Signature"
    deliver_mail()
    recipients = {m.to for m in outbox}
    assert {"sup@example.org", "admin@example.org"} <= recipients


def test_scanner_outage_keeps_file_pending(sup, db):
    from app.files import scanner

    class Down:
        def scan(self, content):
            raise ScannerUnavailable("connection refused")

    scanner.set_scanner(Down())
    file_id = upload(sup, "a.pdf", pdf_bytes()).json()["id"]
    scan()
    assert sup.get(f"/api/files/{file_id}").json()["status"] == "pending"
    assert link(sup, file_id).json()["error"]["code"] == "file_not_ready"


def test_clamd_protocol():
    """INSTREAM framing against a minimal clamd stand-in."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]
    received = {}

    def serve():
        conn, _ = server.accept()
        with conn:
            data = b""
            while not data.endswith(struct.pack("!L", 0)):
                data += conn.recv(65536)
            received["data"] = data
            body = data[len(b"zINSTREAM\0") :]
            content, offset = b"", 0
            while True:
                (size,) = struct.unpack("!L", body[offset : offset + 4])
                offset += 4
                if size == 0:
                    break
                content += body[offset : offset + size]
                offset += size
            reply = b"stream: Eicar-Signature FOUND\0" if EICAR in content else b"stream: OK\0"
            conn.sendall(reply)

    for payload, clean in ((b"hello" * 30000, True), (EICAR, False)):
        thread = threading.Thread(target=serve)
        thread.start()
        result = ClamdScanner("127.0.0.1", port).scan(payload)
        thread.join()
        assert result.clean is clean
        assert received["data"].startswith(b"zINSTREAM\0")
    server.close()
    with pytest.raises(ScannerUnavailable):
        ClamdScanner("127.0.0.1", port, timeout=1).scan(b"x")


@pytest.mark.skipif(not os.environ.get("TEST_CLAMD_HOST"), reason="no clamd server configured")
def test_real_clamd_detects_eicar():
    scanner = ClamdScanner(os.environ["TEST_CLAMD_HOST"], int(os.environ.get("TEST_CLAMD_PORT", "3310")))
    assert scanner.scan(EICAR).clean is False
    assert scanner.scan(pdf_bytes()).clean is True


# Access and links -------------------------------------------------------------------


def test_links_are_bound_to_session_and_expire(new_client, outbox, monkeypatch):
    user, _ = make_user(Role.SUPERVISOR, "sup@example.org")
    first = new_client()
    login(first, outbox, "sup@example.org")
    file_id = upload(first, "a.pdf", pdf_bytes()).json()["id"]
    scan()
    url = link(first, file_id, "inline").json()["url"]
    ok = first.get(url)
    assert ok.status_code == 200
    assert ok.headers["cache-control"] == "private, no-store"
    assert ok.headers["x-content-type-options"] == "nosniff"
    assert "object-src 'self'" in ok.headers["content-security-policy"]

    # The same user's other session cannot use the link.
    second = new_client()
    login(second, outbox, "sup@example.org")
    assert second.get(url).status_code == 404
    # Nor can anyone after signing out.
    first.post("/api/auth/logout")
    assert first.get(url).status_code == 401
    # Links expire after 5 minutes.
    url = link(second, file_id).json()["url"]
    real = service.time.time
    monkeypatch.setattr(service.time, "time", lambda: real() + 301)
    assert second.get(url).status_code == 410


def test_other_users_cannot_see_or_link_a_file(new_client, outbox, db):
    owner, _ = signed_in(new_client, outbox, Role.SUPERVISOR, "a@example.org")
    other, _ = signed_in(new_client, outbox, Role.SUPERVISOR, "b@example.org")
    admin, _ = signed_in(new_client, outbox, Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    file_id = upload(owner, "a.pdf", pdf_bytes()).json()["id"]
    scan()
    url = link(owner, file_id).json()["url"]
    assert other.get(f"/api/files/{file_id}").status_code == 404
    assert link(other, file_id).status_code == 404
    assert other.get(url).status_code == 404
    # An unattached upload belongs to its uploader alone, until a feature takes it over.
    assert admin.get(f"/api/files/{file_id}").status_code == 404
    assert db.execute(select(AuditLog).where(AuditLog.action == "permission.denied")).scalars().first()


def test_tampered_link_rejected(sup):
    file_id = upload(sup, "a.pdf", pdf_bytes()).json()["id"]
    scan()
    url = link(sup, file_id).json()["url"]
    assert sup.get(url[:-2] + ("aa" if not url.endswith("aa") else "bb")).status_code == 404


def test_stored_objects_are_encrypted(sup, file_store, db):
    marker = b"UNIQUE-PLAINTEXT-MARKER-12345"
    file_id = upload(sup, "a.pdf", pdf_bytes(extra_text=marker)).json()["id"]
    file = db.get(StoredFile, file_id)
    raw = file_store.get(file.storage_key)
    assert marker not in raw
    with pikepdf.open(io.BytesIO(service.read_content(file))) as pdf:
        assert marker in pdf.pages[0].Contents.read_bytes()
    # A changed object fails decryption rather than being served.
    file_store.put(file.storage_key, raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(InvalidTag):
        service.read_content(file)


def test_upload_rate_limit(sup, db):
    from app.models import District

    district = db.execute(select(District)).scalar_one()
    district.settings = {**district.settings, "upload_rate_per_hour": 2}
    db.commit()
    assert upload(sup, "a.pdf", pdf_bytes()).status_code == 201
    assert upload(sup, "b.pdf", pdf_bytes()).status_code == 201
    assert upload(sup, "c.pdf", pdf_bytes()).status_code == 429
