/**
 * FR-D3: scanned pages are joined into one PDF on the phone. Each page is a JPEG placed
 * whole on a page of the same shape, so building the PDF loses nothing more than the JPEG did.
 */

export interface JpegInfo {
  width: number;
  height: number;
  components: number;
}

/** Size and colour channels from a JPEG's frame header. */
export function jpegInfo(bytes: Uint8Array): JpegInfo {
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) throw new Error("not a jpeg");
  let i = 2;
  while (i + 9 < bytes.length) {
    if (bytes[i] !== 0xff) {
      i += 1;
      continue;
    }
    const marker = bytes[i + 1];
    if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0xff) {
      i += marker === 0xff ? 1 : 2;
      continue;
    }
    const length = (bytes[i + 2] << 8) | bytes[i + 3];
    // Start-of-frame markers, apart from DHT (c4), JPG (c8) and DAC (cc).
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return {
        height: (bytes[i + 5] << 8) | bytes[i + 6],
        width: (bytes[i + 7] << 8) | bytes[i + 8],
        components: bytes[i + 9],
      };
    }
    i += 2 + length;
  }
  throw new Error("no jpeg frame");
}

// A4 in points; each page keeps its photo's shape at A4's width (or height, if landscape).
const A4_SHORT = 595.28;
const A4_LONG = 841.89;

function pageSize({ width, height }: JpegInfo): [number, number] {
  if (width <= height) {
    const w = Math.min(A4_SHORT, (A4_LONG * width) / height);
    return [w, (w * height) / width];
  }
  const h = Math.min(A4_SHORT, (A4_LONG * height) / width);
  return [(h * width) / height, h];
}

const fmt = (n: number) => (Math.round(n * 100) / 100).toString();

export function buildPdf(pages: Uint8Array[]): Uint8Array {
  if (!pages.length) throw new Error("no pages");
  const encoder = new TextEncoder();
  const parts: Uint8Array[] = [];
  const offsets: number[] = [];
  let length = 0;
  const write = (part: string | Uint8Array) => {
    const bytes = typeof part === "string" ? encoder.encode(part) : part;
    parts.push(bytes);
    length += bytes.length;
  };
  const object = (id: number, body: string, stream?: Uint8Array) => {
    offsets[id] = length;
    write(`${id} 0 obj\n${body}\n`);
    if (stream) {
      write("stream\n");
      write(stream);
      write("\nendstream\n");
    }
    write("endobj\n");
  };

  // 1: catalog, 2: page tree, then three objects per page: page, image, drawing.
  const pageId = (i: number) => 3 + i * 3;
  write("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n");
  object(1, "<< /Type /Catalog /Pages 2 0 R >>");
  object(2, `<< /Type /Pages /Count ${pages.length} /Kids [${pages.map((_, i) => `${pageId(i)} 0 R`).join(" ")}] >>`);
  pages.forEach((jpeg, i) => {
    const info = jpegInfo(jpeg);
    const [w, h] = pageSize(info);
    const id = pageId(i);
    const colour = info.components === 1 ? "/DeviceGray" : info.components === 4 ? "/DeviceCMYK" : "/DeviceRGB";
    const draw = encoder.encode(`q ${fmt(w)} 0 0 ${fmt(h)} 0 0 cm /Im0 Do Q`);
    object(
      id,
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${fmt(w)} ${fmt(h)}] /Resources << /XObject << /Im0 ${id + 1} 0 R >> >> /Contents ${id + 2} 0 R >>`,
    );
    object(
      id + 1,
      `<< /Type /XObject /Subtype /Image /Width ${info.width} /Height ${info.height} /ColorSpace ${colour} /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>`,
      jpeg,
    );
    object(id + 2, `<< /Length ${draw.length} >>`, draw);
  });

  const count = 3 + pages.length * 3;
  const xref = length;
  let table = `xref\n0 ${count}\n0000000000 65535 f \n`;
  for (let id = 1; id < count; id += 1) table += `${String(offsets[id]).padStart(10, "0")} 00000 n \n`;
  write(table);
  write(`trailer\n<< /Size ${count} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);

  const out = new Uint8Array(length);
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}
