"""Detect file types from content and make uploads safe to serve (FR-FS2).

- The type comes from the file's bytes, not its name. A mismatch is rejected.
- PDFs lose JavaScript, embedded files, forms, launch and web-link actions.
  Encrypted PDFs are rejected.
- Images are decoded and re-encoded, which drops EXIF data including GPS.
  HEIC photos become JPEG and TIFF scans become PDF, so every browser can show them.
"""

import io
from dataclasses import dataclass

import pikepdf
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from app.errors import invalid

register_heif_opener()
# Refuse decompression bombs: a 25 MB file should never expand past this.
Image.MAX_IMAGE_PIXELS = 80_000_000

EXTENSIONS = {
    "pdf": {".pdf"},
    "jpeg": {".jpg", ".jpeg"},
    "png": {".png"},
    "tiff": {".tif", ".tiff"},
    "heic": {".heic", ".heif"},
}


@dataclass
class Clean:
    content: bytes
    mime_type: str
    extension: str
    page_count: int | None


def sniff(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if content[4:8] == b"ftyp" and content[8:12] in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
        return "heic"
    return None


def detect(filename: str, content: bytes) -> str:
    kind = sniff(content)
    if kind is None:
        raise invalid("file_type_unsupported")
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in EXTENSIONS[kind]:
        raise invalid("file_type_mismatch", {"detected": kind})
    return kind


# PDF -----------------------------------------------------------------------

# /AF and /EF also carry attachments (PDF 2.0 associated files and file specifications).
_DROP_KEYS = (
    "/JS",
    "/JavaScript",
    "/AA",
    "/OpenAction",
    "/AcroForm",
    "/EmbeddedFiles",
    "/EmbeddedFile",
    "/XFA",
    "/AF",
    "/EF",
)
_UNSAFE_ACTIONS = ("/JavaScript", "/Launch", "/URI", "/SubmitForm", "/ImportData", "/GoToR", "/GoToE", "/Rendition")
_UNSAFE_ANNOTS = ("/FileAttachment", "/Widget", "/Screen", "/Movie", "/Sound", "/RichMedia", "/3D")


def sanitize_pdf(content: bytes, max_pages: int) -> Clean:
    try:
        pdf = pikepdf.open(io.BytesIO(content))
    except pikepdf.PasswordError as exc:
        raise invalid("pdf_encrypted") from exc
    except pikepdf.PdfError as exc:
        raise invalid("file_unreadable") from exc
    with pdf:
        if pdf.is_encrypted:
            raise invalid("pdf_encrypted")
        pages = len(pdf.pages)
        if pages == 0:
            raise invalid("file_empty")
        if pages > max_pages:
            raise invalid("too_many_pages", {"max": max_pages})
        for page in pdf.pages:
            annots = page.obj.get("/Annots")
            if annots is not None:
                page.obj.Annots = pikepdf.Array(
                    [a for a in annots if isinstance(a, pikepdf.Dictionary) and a.get("/Subtype") not in _UNSAFE_ANNOTS]
                )
        for obj in pdf.objects:
            if not isinstance(obj, pikepdf.Dictionary):
                continue
            for key in _DROP_KEYS:
                if key in obj:
                    del obj[key]
            action = obj.get("/A")
            if isinstance(action, pikepdf.Dictionary) and action.get("/S") in _UNSAFE_ACTIONS:
                del obj["/A"]
            if obj.get("/S") in _UNSAFE_ACTIONS:
                # A free-standing action object: neutralize it.
                for key in list(obj.keys()):
                    del obj[key]
        names = pdf.Root.get("/Names")
        if isinstance(names, pikepdf.Dictionary):
            for key in ("/JavaScript", "/EmbeddedFiles"):
                if key in names:
                    del names[key]
        out = io.BytesIO()
        # Only objects still reachable from the document are written.
        pdf.save(out)
    return Clean(out.getvalue(), "application/pdf", ".pdf", pages)


# Images ---------------------------------------------------------------------


def _open_image(content: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(content))
        image.load()
        return image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise invalid("file_unreadable") from exc


def sanitize_image(kind: str, content: bytes, max_pages: int) -> Clean:
    image = _open_image(content)
    if kind == "tiff":
        frames = []
        for index in range(getattr(image, "n_frames", 1)):
            if index >= max_pages:
                raise invalid("too_many_pages", {"max": max_pages})
            image.seek(index)
            frames.append(image.convert("RGB") if image.mode not in ("RGB", "L", "1") else image.copy())
        out = io.BytesIO()
        frames[0].save(out, "PDF", save_all=True, append_images=frames[1:], resolution=200)
        return Clean(out.getvalue(), "application/pdf", ".pdf", len(frames))
    # Apply the camera's rotation before the EXIF data is dropped.
    image = ImageOps.exif_transpose(image)
    out = io.BytesIO()
    if kind == "png":
        image.save(out, "PNG", optimize=True)
        return Clean(out.getvalue(), "image/png", ".png", 1)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    # Saving without an exif argument writes no EXIF block.
    image.save(out, "JPEG", quality=90, optimize=True)
    return Clean(out.getvalue(), "image/jpeg", ".jpg", 1)


def clean(filename: str, content: bytes, max_pages: int) -> Clean:
    kind = detect(filename, content)
    if kind == "pdf":
        return sanitize_pdf(content, max_pages)
    return sanitize_image(kind, content, max_pages)
