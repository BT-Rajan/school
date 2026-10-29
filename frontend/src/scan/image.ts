/**
 * Page scanning on the phone (FR-D3): finding the page's edges, straightening it, and
 * making the writing stand out. Plain arrays of pixels, so it runs anywhere and is testable
 * without a canvas; scan/process.ts moves pixels to and from images.
 */

export interface Pixels {
  data: Uint8ClampedArray; // RGBA
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

/** Corners in order: top-left, top-right, bottom-right, bottom-left. */
export type Quad = [Point, Point, Point, Point];

export type Filter = "original" | "enhanced" | "bw";

export const FULL: Quad = [
  { x: 0, y: 0 },
  { x: 1, y: 0 },
  { x: 1, y: 1 },
  { x: 0, y: 1 },
];

export function luminance(img: Pixels): Uint8Array {
  const out = new Uint8Array(img.width * img.height);
  const d = img.data;
  for (let i = 0, p = 0; i < out.length; i += 1, p += 4) out[i] = (d[p] * 77 + d[p + 1] * 150 + d[p + 2] * 29) >> 8;
  return out;
}

function boxBlur(src: Uint8Array, w: number, h: number, r: number): Uint8Array {
  const tmp = new Uint8Array(src.length);
  const out = new Uint8Array(src.length);
  const pass = (from: Uint8Array, to: Uint8Array, along: number, across: number, step: number, line: number) => {
    for (let a = 0; a < across; a += 1) {
      let sum = 0;
      let n = 0;
      for (let i = -r; i <= r; i += 1) {
        if (i >= 0 && i < along) {
          sum += from[a * line + i * step];
          n += 1;
        }
      }
      for (let i = 0; i < along; i += 1) {
        to[a * line + i * step] = sum / n;
        const leave = i - r;
        const enter = i + r + 1;
        if (leave >= 0) {
          sum -= from[a * line + leave * step];
          n -= 1;
        }
        if (enter < along) {
          sum += from[a * line + enter * step];
          n += 1;
        }
      }
    }
  };
  pass(src, tmp, w, h, 1, w); // rows
  pass(tmp, out, h, w, w, 1); // columns
  return out;
}

export function otsu(gray: Uint8Array): number {
  const hist = new Array<number>(256).fill(0);
  for (const v of gray) hist[v] += 1;
  let total = 0;
  for (let i = 0; i < 256; i += 1) total += i * hist[i];
  let below = 0;
  let belowSum = 0;
  let best = 0;
  let threshold = 127;
  for (let t = 0; t < 256; t += 1) {
    below += hist[t];
    if (!below) continue;
    const above = gray.length - below;
    if (!above) break;
    belowSum += t * hist[t];
    const m1 = belowSum / below;
    const m2 = (total - belowSum) / above;
    const between = below * above * (m1 - m2) * (m1 - m2);
    if (between > best) {
      best = between;
      threshold = t;
    }
  }
  return threshold;
}

/**
 * Where the page is in a photo: the largest bright region, a sheet of paper against a darker
 * table or hand, and its four extreme corners. Returns corners as fractions of the image, or
 * null when no page stands out, and then the whole photo is used and the user can drag corners.
 */
export function detectPage(img: Pixels): Quad | null {
  const { width: w, height: h } = img;
  const gray = boxBlur(luminance(img), w, h, Math.max(1, Math.round(Math.min(w, h) / 100)));
  const t = otsu(gray);
  const label = new Int32Array(w * h).fill(-1);
  const stack = new Int32Array(w * h);
  let bestSize = 0;
  let bestLabel = -1;
  let next = 0;
  for (let start = 0; start < gray.length; start += 1) {
    if (gray[start] <= t || label[start] !== -1) continue;
    let size = 0;
    let top = 0;
    stack[top++] = start;
    label[start] = next;
    while (top) {
      const p = stack[--top];
      size += 1;
      const x = p % w;
      const neighbours = [x > 0 ? p - 1 : -1, x < w - 1 ? p + 1 : -1, p - w, p + w];
      for (const q of neighbours) {
        if (q < 0 || q >= gray.length || label[q] !== -1 || gray[q] <= t) continue;
        label[q] = next;
        stack[top++] = q;
      }
    }
    if (size > bestSize) {
      bestSize = size;
      bestLabel = next;
    }
    next += 1;
  }
  const share = bestSize / (w * h);
  if (bestLabel < 0 || share < 0.15 || share > 0.97) return null;
  // The corners are the region's points furthest along each diagonal.
  let tl = { x: 0, y: 0, v: Infinity };
  let br = { x: 0, y: 0, v: -Infinity };
  let tr = { x: 0, y: 0, v: -Infinity };
  let bl = { x: 0, y: 0, v: Infinity };
  for (let p = 0; p < label.length; p += 1) {
    if (label[p] !== bestLabel) continue;
    const x = p % w;
    const y = (p - x) / w;
    if (x + y < tl.v) tl = { x, y, v: x + y };
    if (x + y > br.v) br = { x, y, v: x + y };
    if (x - y > tr.v) tr = { x, y, v: x - y };
    if (x - y < bl.v) bl = { x, y, v: x - y };
  }
  const quad: Quad = [tl, tr, br, bl].map((c) => ({ x: c.x / (w - 1), y: c.y / (h - 1) })) as Quad;
  return area(quad) > 0.1 ? quad : null;
}

/** Area of a quadrilateral, in the same units squared (shoelace formula). */
export function area(q: Quad): number {
  let s = 0;
  for (let i = 0; i < 4; i += 1) {
    const a = q[i];
    const b = q[(i + 1) % 4];
    s += a.x * b.y - b.x * a.y;
  }
  return Math.abs(s) / 2;
}

const dist = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);

/** The straightened page's size in pixels, from the corners in pixels, kept under maxSide. */
export function outputSize(q: Quad, maxSide: number): { width: number; height: number } {
  const width = Math.max(dist(q[0], q[1]), dist(q[3], q[2]));
  const height = Math.max(dist(q[0], q[3]), dist(q[1], q[2]));
  const scale = Math.min(1, maxSide / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** The projective transform taking the unit square's corners to q's (in order TL, TR, BR, BL). */
export function squareToQuad(q: Quad): number[] {
  const [p0, p1, p2, p3] = q;
  const dx1 = p1.x - p2.x;
  const dx2 = p3.x - p2.x;
  const dy1 = p1.y - p2.y;
  const dy2 = p3.y - p2.y;
  const sx = p0.x - p1.x + p2.x - p3.x;
  const sy = p0.y - p1.y + p2.y - p3.y;
  let g = 0;
  let h = 0;
  if (Math.abs(sx) > 1e-12 || Math.abs(sy) > 1e-12) {
    const det = dx1 * dy2 - dx2 * dy1;
    g = (sx * dy2 - dx2 * sy) / det;
    h = (dx1 * sy - sx * dy1) / det;
  }
  return [
    p1.x - p0.x + g * p1.x, p3.x - p0.x + h * p3.x, p0.x,
    p1.y - p0.y + g * p1.y, p3.y - p0.y + h * p3.y, p0.y,
    g, h, 1,
  ];
}

/** Straighten the page: corners in pixels of img, to a flat rectangle (crop and deskew). */
export function warp(img: Pixels, q: Quad, width: number, height: number): Pixels {
  const m = squareToQuad(q);
  const out = new Uint8ClampedArray(width * height * 4);
  const src = img.data;
  const sw = img.width;
  const sh = img.height;
  for (let y = 0; y < height; y += 1) {
    const v = (y + 0.5) / height;
    for (let x = 0; x < width; x += 1) {
      const u = (x + 0.5) / width;
      const z = m[6] * u + m[7] * v + m[8];
      const fx = Math.min(sw - 1, Math.max(0, (m[0] * u + m[1] * v + m[2]) / z - 0.5));
      const fy = Math.min(sh - 1, Math.max(0, (m[3] * u + m[4] * v + m[5]) / z - 0.5));
      const x0 = Math.floor(fx);
      const y0 = Math.floor(fy);
      const x1 = Math.min(sw - 1, x0 + 1);
      const y1 = Math.min(sh - 1, y0 + 1);
      const ax = fx - x0;
      const ay = fy - y0;
      const i00 = (y0 * sw + x0) * 4;
      const i10 = (y0 * sw + x1) * 4;
      const i01 = (y1 * sw + x0) * 4;
      const i11 = (y1 * sw + x1) * 4;
      const o = (y * width + x) * 4;
      for (let c = 0; c < 3; c += 1) {
        const top = src[i00 + c] + (src[i10 + c] - src[i00 + c]) * ax;
        const bottom = src[i01 + c] + (src[i11 + c] - src[i01 + c]) * ax;
        out[o + c] = top + (bottom - top) * ay;
      }
      out[o + 3] = 255;
    }
  }
  return { data: out, width, height };
}

/** Quarter turns clockwise. */
export function rotate(img: Pixels, turns: number): Pixels {
  const n = ((turns % 4) + 4) % 4;
  if (!n) return img;
  const { width: w, height: h, data } = img;
  const ow = n % 2 ? h : w;
  const oh = n % 2 ? w : h;
  const out = new Uint8ClampedArray(data.length);
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const [nx, ny] = n === 1 ? [h - 1 - y, x] : n === 2 ? [w - 1 - x, h - 1 - y] : [y, w - 1 - x];
      const s = (y * w + x) * 4;
      const o = (ny * ow + nx) * 4;
      out[o] = data[s];
      out[o + 1] = data[s + 1];
      out[o + 2] = data[s + 2];
      out[o + 3] = data[s + 3];
    }
  }
  return { data: out, width: ow, height: oh };
}

function percentile(hist: number[], total: number, fraction: number): number {
  let seen = 0;
  for (let i = 0; i < 256; i += 1) {
    seen += hist[i];
    if (seen >= total * fraction) return i;
  }
  return 255;
}

/**
 * Contrast enhancement. "enhanced" stretches the page's tones so paper is white and ink dark,
 * keeping colour (stamps, signatures). "bw" is black and white against the page's local
 * brightness, so shadows across the sheet don't black out the writing.
 */
export function applyFilter(img: Pixels, filter: Filter): Pixels {
  if (filter === "original") return img;
  const { width: w, height: h } = img;
  const lum = luminance(img);
  const out = new Uint8ClampedArray(img.data.length);
  if (filter === "enhanced") {
    const hist = new Array<number>(256).fill(0);
    for (const v of lum) hist[v] += 1;
    const lo = percentile(hist, lum.length, 0.02);
    const hi = Math.max(lo + 1, percentile(hist, lum.length, 0.9));
    const scale = 255 / (hi - lo);
    for (let p = 0; p < img.data.length; p += 4) {
      for (let c = 0; c < 3; c += 1) out[p + c] = (img.data[p + c] - lo) * scale;
      out[p + 3] = 255;
    }
    return { data: out, width: w, height: h };
  }
  // Local mean by a summed-area table; a pixel darker than its surroundings is ink.
  const r = Math.max(4, Math.round(Math.max(w, h) / 40));
  const sums = new Float64Array((w + 1) * (h + 1));
  for (let y = 0; y < h; y += 1) {
    let row = 0;
    for (let x = 0; x < w; x += 1) {
      row += lum[y * w + x];
      sums[(y + 1) * (w + 1) + x + 1] = sums[y * (w + 1) + x + 1] + row;
    }
  }
  for (let y = 0; y < h; y += 1) {
    const y0 = Math.max(0, y - r);
    const y1 = Math.min(h, y + r + 1);
    for (let x = 0; x < w; x += 1) {
      const x0 = Math.max(0, x - r);
      const x1 = Math.min(w, x + r + 1);
      const total = sums[y1 * (w + 1) + x1] - sums[y0 * (w + 1) + x1] - sums[y1 * (w + 1) + x0] + sums[y0 * (w + 1) + x0];
      const mean = total / ((x1 - x0) * (y1 - y0));
      const v = lum[y * w + x] < mean * 0.88 ? 0 : 255;
      const o = (y * w + x) * 4;
      out[o] = v;
      out[o + 1] = v;
      out[o + 2] = v;
      out[o + 3] = 255;
    }
  }
  return { data: out, width: w, height: h };
}
