import { describe, expect, it } from "vitest";

import { applyFilter, detectPage, outputSize, type Pixels, type Quad, rotate, squareToQuad, warp } from "./image";
import { buildPdf, jpegInfo } from "./pdf";

/** A dark table with a light sheet whose corners are given, in pixels. */
function photo(w: number, h: number, corners: Quad): Pixels {
  const data = new Uint8ClampedArray(w * h * 4);
  const inside = (x: number, y: number) => {
    // Inside a convex polygon: on the same side of every edge.
    let sign = 0;
    for (let i = 0; i < 4; i += 1) {
      const a = corners[i];
      const b = corners[(i + 1) % 4];
      const cross = (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x);
      if (cross === 0) continue;
      if (sign === 0) sign = Math.sign(cross);
      else if (Math.sign(cross) !== sign) return false;
    }
    return true;
  };
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const v = inside(x, y) ? 230 : 40;
      // A line of "writing" across the page must not split it.
      const ink = inside(x, y) && y === Math.round(h / 2) ? 20 : v;
      data.set([ink, ink, ink, 255], (y * w + x) * 4);
    }
  }
  return { data, width: w, height: h };
}

describe("finding the page", () => {
  it("finds the corners of a tilted sheet", () => {
    const corners: Quad = [
      { x: 60, y: 30 },
      { x: 250, y: 50 },
      { x: 235, y: 300 },
      { x: 40, y: 285 },
    ];
    const quad = detectPage(photo(300, 340, corners));
    expect(quad).not.toBeNull();
    quad!.forEach((c, i) => {
      expect(Math.abs(c.x * 299 - corners[i].x)).toBeLessThan(6);
      expect(Math.abs(c.y * 339 - corners[i].y)).toBeLessThan(6);
    });
  });

  it("gives up when nothing stands out, so the whole photo is kept", () => {
    const flat: Pixels = { data: new Uint8ClampedArray(100 * 100 * 4).fill(180), width: 100, height: 100 };
    expect(detectPage(flat)).toBeNull();
  });
});

describe("straightening", () => {
  it("maps the unit square's corners onto the page's", () => {
    const q: Quad = [
      { x: 10, y: 5 },
      { x: 90, y: 15 },
      { x: 80, y: 95 },
      { x: 5, y: 85 },
    ];
    const m = squareToQuad(q);
    const at = (u: number, v: number) => {
      const z = m[6] * u + m[7] * v + m[8];
      return { x: (m[0] * u + m[1] * v + m[2]) / z, y: (m[3] * u + m[4] * v + m[5]) / z };
    };
    [at(0, 0), at(1, 0), at(1, 1), at(0, 1)].forEach((p, i) => {
      expect(p.x).toBeCloseTo(q[i].x, 6);
      expect(p.y).toBeCloseTo(q[i].y, 6);
    });
  });

  it("crops the sheet out of the photo, leaving no table", () => {
    const corners: Quad = [
      { x: 60, y: 30 },
      { x: 250, y: 50 },
      { x: 235, y: 300 },
      { x: 40, y: 285 },
    ];
    const img = photo(300, 340, corners);
    const size = outputSize(corners, 2200);
    const flat = warp(img, corners, size.width, size.height);
    let dark = 0;
    for (let p = 0; p < flat.data.length; p += 4) if (flat.data[p] < 100) dark += 1;
    // Only the line of writing (and a little at the edges) is dark: none of the table remains.
    expect(dark / (flat.width * flat.height)).toBeLessThan(0.05);
    expect(outputSize(corners, 100)).toEqual({ width: 76, height: 100 });
  });

  it("turns pages a quarter at a time", () => {
    const img: Pixels = { data: new Uint8ClampedArray([1, 0, 0, 255, 2, 0, 0, 255]), width: 2, height: 1 };
    const turned = rotate(img, 1);
    expect([turned.width, turned.height]).toEqual([1, 2]);
    expect(turned.data[0]).toBe(1);
    expect(rotate(img, 2).data[0]).toBe(2);
    expect(rotate(img, 4)).toBe(img);
  });

  it("makes black and white from writing under a shadow", () => {
    const w = 120;
    const h = 40;
    const data = new Uint8ClampedArray(w * h * 4);
    for (let y = 0; y < h; y += 1) {
      for (let x = 0; x < w; x += 1) {
        const paper = x < w / 2 ? 220 : 120; // half the page in shadow
        const v = x % 20 === 10 ? paper - 80 : paper; // strokes of ink on both halves
        data.set([v, v, v, 255], (y * w + x) * 4);
      }
    }
    const bw = applyFilter({ data, width: w, height: h }, "bw");
    const at = (x: number) => bw.data[(20 * w + x) * 4];
    expect([at(5), at(10), at(95), at(90)]).toEqual([255, 0, 255, 0]);
  });
});

/** The smallest JPEG header the PDF needs: start of image, then a frame header. */
function jpeg(width: number, height: number, components = 3): Uint8Array {
  return new Uint8Array([
    0xff, 0xd8,
    0xff, 0xe0, 0x00, 0x04, 0x00, 0x00, // an APP0 segment to skip
    0xff, 0xc0, 0x00, 0x11, 0x08, height >> 8, height & 0xff, width >> 8, width & 0xff, components,
    0xff, 0xd9,
  ]);
}

describe("joining pages into a PDF", () => {
  it("reads a JPEG's size", () => {
    expect(jpegInfo(jpeg(1654, 2339))).toEqual({ width: 1654, height: 2339, components: 3 });
  });

  it("writes one page per scan, with a table that points at every object", () => {
    const pdf = buildPdf([jpeg(1000, 1414), jpeg(1414, 1000, 1)]);
    const text = new TextDecoder("latin1").decode(pdf);
    expect(text.startsWith("%PDF-1.4")).toBe(true);
    expect(text).toContain("/Count 2");
    expect(text).toContain("/ColorSpace /DeviceGray");
    // Portrait page at A4 width, landscape at A4 height.
    expect(text).toContain("/MediaBox [0 0 595.28 841.73]");
    expect(text).toContain("/MediaBox [0 0 841.73 595.28]");
    const start = Number(text.match(/startxref\n(\d+)/)![1]);
    expect(text.slice(start, start + 4)).toBe("xref");
    const offsets = [...text.slice(start).matchAll(/^(\d{10}) 00000 n $/gm)].map((m) => Number(m[1]));
    expect(offsets).toHaveLength(8);
    offsets.forEach((at, i) => expect(text.slice(at).startsWith(`${i + 1} 0 obj\n`)).toBe(true));
  });
});
