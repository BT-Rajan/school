"""A fake camera feed for the Phase 4 browser test: a printed page, a little tilted, on a
dark desk, written as Motion JPEG for Chromium's --use-file-for-fake-video-capture.

Usage: python e2e/make_scan_video.py out.mjpeg
"""

import io
import sys

from PIL import Image, ImageDraw


def frame() -> bytes:
    desk = Image.new("RGB", (1280, 960), (62, 48, 40))
    page = Image.new("RGB", (620, 860), (238, 236, 228))
    draw = ImageDraw.Draw(page)
    draw.rectangle((40, 40, 580, 110), outline=(30, 30, 30), width=3)
    for i in range(22):
        y = 150 + i * 30
        draw.line((50, y, 570 - (i % 5) * 40, y), fill=(35, 35, 35), width=4)
    tilted = page.rotate(7, expand=True, fillcolor=(62, 48, 40), resample=Image.Resampling.BICUBIC)
    desk.paste(tilted, ((1280 - tilted.width) // 2, (960 - tilted.height) // 2))
    out = io.BytesIO()
    desk.save(out, "JPEG", quality=85)
    return out.getvalue()


def main() -> None:
    data = frame()
    with open(sys.argv[1], "wb") as f:
        for _ in range(30):
            f.write(data)


if __name__ == "__main__":
    main()
