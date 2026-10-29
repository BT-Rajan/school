# Fonts

`SCES-Regular.ttf` and `SCES-Bold.ttf` merge Noto Sans and Noto Naskh Arabic
(both by the Noto Project Authors) into one font, so generated PDFs render
English and Arabic, including mixed lines, with a single font. They are
licensed under the SIL Open Font License 1.1 (`OFL.txt`).

To rebuild them from the upstream Noto releases:

```python
from fontTools.merge import Merger

for style in ("Regular", "Bold"):
    Merger().merge([f"NotoSans-{style}.ttf", f"NotoNaskhArabic-{style}.ttf"]).save(f"SCES-{style}.ttf")
```

The merged fonts are then renamed "SCES Sans" (name IDs 1, 4, 6 and 16), as the
OFL asks for modified versions.
