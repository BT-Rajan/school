/**
 * Between images and pixels for the scanner: decoding photos, finding and straightening the
 * page, and encoding the result as a compressed JPEG for the PDF (FR-D3, FR-PW9).
 */
import { applyFilter, detectPage, type Filter, FULL, outputSize, type Pixels, type Quad, rotate, warp } from "./image";
import { buildPdf } from "./pdf";

// About 200 dots per inch on an A4 page: easy to read, a fraction of a camera photo's size.
const MAX_SIDE = 2200;
// The photo is read a little larger than the page will be, so straightening doesn't blur it.
const READ_SIDE = 2800;
const DETECT_SIDE = 400;

function canvas(width: number, height: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  return c;
}

async function decode(source: Blob, maxSide: number): Promise<Pixels> {
  const bitmap = await createImageBitmap(source);
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const c = canvas(Math.max(1, Math.round(bitmap.width * scale)), Math.max(1, Math.round(bitmap.height * scale)));
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  ctx.drawImage(bitmap, 0, 0, c.width, c.height);
  bitmap.close();
  const { data } = ctx.getImageData(0, 0, c.width, c.height);
  return { data, width: c.width, height: c.height };
}

function encode(img: Pixels, quality: number): Promise<Blob> {
  const c = canvas(img.width, img.height);
  c.getContext("2d")!.putImageData(new ImageData(img.data, img.width, img.height), 0, 0);
  return new Promise((resolve, reject) => c.toBlob((b) => (b ? resolve(b) : reject(new Error("encode"))), "image/jpeg", quality));
}

/** A still from the live camera, at the camera's full size. */
export function captureFrame(video: HTMLVideoElement): Promise<Blob> {
  const c = canvas(video.videoWidth, video.videoHeight);
  c.getContext("2d")!.drawImage(video, 0, 0);
  return new Promise((resolve, reject) => c.toBlob((b) => (b ? resolve(b) : reject(new Error("capture"))), "image/jpeg", 0.92));
}

/** Where the page is in the photo; the whole photo when it can't tell. */
export async function findPage(photo: Blob): Promise<Quad> {
  return detectPage(await decode(photo, DETECT_SIDE)) ?? FULL;
}

export interface Adjustments {
  quad: Quad; // fractions of the photo
  filter: Filter;
  turns: number;
}

/** The finished page: cropped, straightened, turned and cleaned up. */
export async function renderPage(photo: Blob, { quad, filter, turns }: Adjustments): Promise<Blob> {
  const img = await decode(photo, READ_SIDE);
  const corners = quad.map((p) => ({ x: p.x * (img.width - 1), y: p.y * (img.height - 1) })) as Quad;
  const size = outputSize(corners, MAX_SIDE);
  const page = applyFilter(rotate(warp(img, corners, size.width, size.height), turns), filter);
  // Black and white compresses far further without losing the writing.
  return encode(page, filter === "bw" ? 0.6 : 0.72);
}

/** All pages, in order, as one PDF. */
export async function assemble(pages: Blob[], name: string): Promise<File> {
  const bytes = await Promise.all(pages.map(async (p) => new Uint8Array(await p.arrayBuffer())));
  return new File([buildPdf(bytes)], name, { type: "application/pdf" });
}
