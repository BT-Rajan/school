"""Viewer watermark on every page, applied when a document is served (FR-D27).

The stored original is never changed. The mark names the viewer, so a leaked
copy shows who opened it.
"""

import io
from importlib import resources

import pikepdf
from fpdf import FPDF


def _overlay(width: float, height: float, text: str) -> bytes:
    pdf = FPDF(unit="pt", format=(width, height))
    fonts = resources.files("app.pdf").joinpath("fonts")
    pdf.add_font("sces", "", str(fonts.joinpath("SCES-Regular.ttf")))
    pdf.set_text_shaping(use_shaping_engine=True)
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_text_color(170, 30, 30)
    size = max(7.0, min(width, height) / 60)
    pdf.set_font("sces", "", size)
    with pdf.local_context(fill_opacity=0.55, stroke_opacity=0.55):
        # A clear line at the top and bottom, and a faint diagonal across the middle.
        for y in (6, height - size - 8):
            pdf.set_xy(0, y)
            pdf.cell(width, size + 2, text, align="C")
    with pdf.local_context(fill_opacity=0.12, stroke_opacity=0.12):
        pdf.set_font("sces", "", size * 2.2)
        with pdf.rotation(angle=35, x=width / 2, y=height / 2):
            pdf.set_xy(0, height / 2 - size)
            pdf.cell(width, size * 2.5, text, align="C")
    return bytes(pdf.output())


def apply(content: bytes, text: str) -> bytes:
    with pikepdf.open(io.BytesIO(content)) as target:
        overlays: dict[tuple[float, float], pikepdf.Pdf] = {}
        for page in target.pages:
            box = page.mediabox
            width, height = float(box[2]) - float(box[0]), float(box[3]) - float(box[1])
            key = (round(width, 1), round(height, 1))
            if key not in overlays:
                overlays[key] = pikepdf.open(io.BytesIO(_overlay(width, height, text)))
            page.add_overlay(overlays[key].pages[0])
        out = io.BytesIO()
        target.save(out)
        for overlay in overlays.values():
            overlay.close()
        return out.getvalue()
