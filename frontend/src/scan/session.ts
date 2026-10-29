/**
 * A scan in progress is kept on the device, so closing the app or losing battery partway
 * through a long report doesn't lose the pages already taken. Sign-out wipes it with
 * everything else (FR-PW12).
 */
import * as store from "../offline/db";
import { newKey } from "../offline/queue";
import type { Adjustments } from "./process";

export interface ScanPage extends Adjustments {
  id: string;
  photo: string; // blob key of the photo as taken
  page: string; // blob key of the finished page
}

const KEY = "scan:pages";

export async function loadPages(): Promise<ScanPage[]> {
  return ((await store.get<{ pages: ScanPage[] }>("kv", KEY))?.pages ?? []).filter(Boolean);
}

export async function savePages(pages: ScanPage[]): Promise<void> {
  await store.put("kv", KEY, { pages });
}

export async function putBlob(blob: Blob): Promise<string> {
  const key = `scan:${newKey()}`;
  await store.put("blobs", key, blob);
  return key;
}

export async function getBlob(key: string): Promise<Blob> {
  const blob = await store.get<Blob>("blobs", key);
  if (!blob) throw new Error("scan page missing");
  return blob;
}

export async function dropBlobs(...keys: string[]): Promise<void> {
  for (const key of keys) await store.del("blobs", key);
}

export async function clearScan(pages: ScanPage[]): Promise<void> {
  await dropBlobs(...pages.flatMap((p) => [p.photo, p.page]));
  await store.del("kv", KEY);
}
