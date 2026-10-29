/**
 * Changes made without a connection, sent in order once it returns (FR-PW4 to FR-PW9, FR-PW11).
 *
 * Every item carries a client key, so the server confirms each one and a replay never
 * creates a duplicate (FR-PW5). If the server's copy changed since this device read it, the
 * item stops as a conflict and the user chooses which version to keep (FR-PW6). An item that
 * fails stops the later items about the same record, and only those.
 */
import { api, ApiError } from "../api";
import type { DocumentDetail, Evaluation } from "../types";
import * as store from "./db";

export type ItemStatus = "pending" | "sending" | "conflict" | "failed";

interface Base {
  key: string;
  created: number;
  /** When the user acted on the device (FR-PW11). */
  deviceTime: string;
  status: ItemStatus;
  error?: string;
  label: string;
}

export interface StartItem extends Base {
  kind: "evaluation.start";
  ref: number; // the local (negative) id until the server gives one
  body: { form_id: number; school_id: number; teacher_id: number | null; visit_date: string | null; client_key: string };
}

export interface SaveItem extends Base {
  kind: "evaluation.save";
  ref: number;
  baseVersion: number | null; // the version this device last read; null for a new evaluation
  body: { visit_date: string | null; visit_notes: string | null; sections: Record<string, Record<string, unknown>> };
  server?: Evaluation; // the server's copy, when it conflicts
}

export interface SubmitItem extends Base {
  kind: "evaluation.submit";
  ref: number;
}

export interface Page {
  blob: string; // key in the blobs store
  name: string;
  size: number;
}

export interface DocumentItem extends Base {
  kind: "document.create";
  ref: string;
  pages: Page[];
  body: Record<string, unknown> & { client_key: string };
  submit: boolean;
}

export type Item = StartItem | SaveItem | SubmitItem | DocumentItem;

// FR-PW9: at most 20 queued files or 200 MB on a device.
export const MAX_FILES = 20;
export const MAX_BYTES = 200 * 1024 * 1024;
const CHUNK = 1024 * 1024;

// Subscribers -------------------------------------------------------------------------------

let items: Item[] = [];
let loaded = false;
const listeners = new Set<() => void>();
let afterSync: (() => void) | null = null;

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function snapshot(): Item[] {
  return items;
}

function changed(): void {
  items = [...items].sort((a, b) => a.created - b.created);
  for (const l of listeners) l();
}

export async function load(onSynced?: () => void): Promise<void> {
  if (onSynced) afterSync = onSynced;
  if (loaded) return;
  loaded = true;
  items = await store.all<Item>("queue").catch(() => []);
  // Something was being sent when the app closed: send it again; the key makes that safe.
  items = items.map((i) => (i.status === "sending" ? { ...i, status: "pending" } : i));
  changed();
}

async function save(item: Item): Promise<void> {
  const index = items.findIndex((i) => i.key === item.key);
  if (index >= 0) items[index] = item;
  else items.push(item);
  await store.put("queue", item.key, item);
  changed();
}

async function remove(key: string): Promise<void> {
  items = items.filter((i) => i.key !== key);
  await store.del("queue", key);
  changed();
}

export function newKey(): string {
  return typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function base(label: string): Pick<Base, "key" | "created" | "deviceTime" | "status" | "label"> {
  return { key: newKey(), created: Date.now(), deviceTime: new Date().toISOString(), status: "pending", label };
}

// Local evaluations ------------------------------------------------------------------------

/** The server's id for a local one, once it has been created. */
export async function serverId(ref: number): Promise<number | null> {
  if (ref > 0) return ref;
  return (await store.get<number>("kv", `map:${ref}`)) ?? null;
}

export async function localEvaluation(ref: number): Promise<Evaluation | undefined> {
  return store.get<Evaluation>("kv", `local:${ref}`);
}

export async function saveLocalEvaluation(e: Evaluation): Promise<void> {
  await store.put("kv", `local:${e.id}`, e);
}

// Enqueueing ------------------------------------------------------------------------------------

async function askForStorage(): Promise<void> {
  // FR-PW8: ask the browser not to clear queued work when space runs low.
  try {
    if (navigator.storage?.persist && !(await navigator.storage.persisted())) await navigator.storage.persist();
  } catch {
    // Not available: the warning on the outbox screen covers it.
  }
}

export async function enqueueStart(ref: number, body: StartItem["body"], label: string): Promise<void> {
  await askForStorage();
  await save({ ...base(label), kind: "evaluation.start", ref, body });
  void sync();
}

export async function enqueueSave(ref: number, baseVersion: number | null, body: SaveItem["body"], label: string): Promise<void> {
  await askForStorage();
  // One pending save per evaluation is enough: the latest answers replace the earlier ones,
  // but the version first read is kept, so a conflict is still noticed.
  const pending = items.find((i): i is SaveItem => i.kind === "evaluation.save" && i.ref === ref && i.status === "pending");
  if (pending) await save({ ...pending, body, deviceTime: new Date().toISOString() });
  else await save({ ...base(label), kind: "evaluation.save", ref, baseVersion, body });
  void sync();
}

export async function enqueueSubmit(ref: number, label: string): Promise<void> {
  await save({ ...base(label), kind: "evaluation.submit", ref });
  void sync();
}

export class QueueFullError extends Error {}

export async function enqueueDocument(files: File[], body: Record<string, unknown>, submit: boolean, label: string): Promise<void> {
  const queued = items.filter((i): i is DocumentItem => i.kind === "document.create").flatMap((i) => i.pages);
  const size = queued.reduce((n, p) => n + p.size, 0) + files.reduce((n, f) => n + f.size, 0);
  if (queued.length + files.length > MAX_FILES || size > MAX_BYTES) throw new QueueFullError();
  await askForStorage();
  const pages: Page[] = [];
  for (const file of files) {
    const blob = newKey();
    await store.put("blobs", blob, file);
    pages.push({ blob, name: file.name, size: file.size });
  }
  const clientKey = newKey();
  await save({ ...base(label), kind: "document.create", ref: clientKey, pages, body: { ...body, client_key: clientKey }, submit });
  void sync();
}

// Sending ---------------------------------------------------------------------------------------

let running: Promise<void> | null = null;

/** No connection, or signed out meanwhile: keep the item and try again later. */
function isOffline(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 0 || error.status === 401);
}

const latestVersion = new Map<number, number>();

async function evaluationId(ref: number): Promise<number> {
  const id = await serverId(ref);
  if (id === null) throw new Error("waiting for the evaluation to be created");
  return id;
}

async function currentVersion(id: number): Promise<number> {
  return latestVersion.get(id) ?? (await api<Evaluation>(`/api/evaluations/${id}`)).version;
}

async function uploadPage(page: Page, clientKey: string): Promise<number> {
  const blob = await store.get<Blob>("blobs", page.blob);
  if (!blob) throw new ApiError(422, "page_missing");
  const upload = await api<{ id: number; received: number; file_id: number | null }>("/api/uploads", {
    method: "POST",
    body: { client_key: clientKey, name: page.name, size: blob.size },
  });
  if (upload.file_id) return upload.file_id;
  let offset = upload.received;
  while (offset < blob.size) {
    const piece = blob.slice(offset, offset + CHUNK);
    try {
      const result = await api<{ received: number }>(`/api/uploads/${upload.id}/chunks?offset=${offset}`, {
        method: "PUT",
        raw: piece,
      });
      offset = result.received;
    } catch (error) {
      // The server already has more (or less) than we thought: carry on from where it is.
      if (error instanceof ApiError && error.code === "upload_offset_mismatch") {
        offset = (error.detail as { received: number }).received;
        continue;
      }
      throw error;
    }
  }
  const file = await api<{ id: number }>(`/api/uploads/${upload.id}/complete`, { method: "POST" });
  return file.id;
}

async function send(item: Item): Promise<void> {
  switch (item.kind) {
    case "evaluation.start": {
      const created = await api<Evaluation>("/api/evaluations", { method: "POST", body: item.body });
      await store.put("kv", `map:${item.ref}`, created.id);
      latestVersion.set(created.id, created.version);
      return;
    }
    case "evaluation.save": {
      const id = await evaluationId(item.ref);
      const version = item.baseVersion ?? (await currentVersion(id));
      const saved = await api<Evaluation>(`/api/evaluations/${id}`, { method: "PATCH", body: { version, ...item.body } });
      latestVersion.set(id, saved.version);
      return;
    }
    case "evaluation.submit": {
      const id = await evaluationId(item.ref);
      const done = await api<Evaluation>(`/api/evaluations/${id}/submit`, {
        method: "POST",
        body: { version: await currentVersion(id), device_time: item.deviceTime },
      });
      latestVersion.set(id, done.version);
      return;
    }
    case "document.create": {
      const fileIds = [];
      for (const [i, page] of item.pages.entries()) fileIds.push(await uploadPage(page, `${item.body.client_key}-${i}`));
      let doc = await api<DocumentDetail>("/api/documents", {
        method: "POST",
        body: { ...item.body, file_ids: fileIds, device_time: item.deviceTime },
      });
      if (item.submit && ["draft", "withdrawn", "returned"].includes(doc.status)) {
        doc = await api<DocumentDetail>(`/api/documents/${doc.id}/submit`, { method: "POST", body: { version: doc.version } });
      }
      for (const page of item.pages) await store.del("blobs", page.blob);
    }
  }
}

function refOf(item: Item): string {
  return `${item.kind.split(".")[0]}:${item.ref}`;
}

/** Send what is waiting, in order. Safe to call at any time; runs once at a time. */
export function sync(): Promise<void> {
  if (running) return running;
  running = (async () => {
    let sent = 0;
    const blocked = new Set<string>();
    for (const item of [...items]) {
      if (item.status === "conflict" || item.status === "failed") {
        blocked.add(refOf(item));
        continue;
      }
      if (blocked.has(refOf(item))) continue;
      await save({ ...item, status: "sending" });
      try {
        await send(item);
        await remove(item.key);
        sent += 1;
      } catch (error) {
        if (isOffline(error)) {
          await save({ ...item, status: "pending" });
          break;
        }
        blocked.add(refOf(item));
        if (error instanceof ApiError && error.code === "version_conflict" && item.kind === "evaluation.save") {
          const current = (error.detail as { current?: Evaluation })?.current;
          await save({ ...item, status: "conflict", error: error.code, server: current });
        } else {
          const code = error instanceof ApiError ? error.code : "generic";
          await save({ ...item, status: code === "generic" && !(error instanceof ApiError) ? "pending" : "failed", error: code });
        }
      }
    }
    if (sent && afterSync) afterSync();
  })().finally(() => {
    running = null;
  });
  return running;
}

// Resolving -------------------------------------------------------------------------------------

/** FR-PW6: keep this device's answers, on top of the server's latest version. */
export async function keepMine(key: string): Promise<void> {
  const item = items.find((i) => i.key === key);
  if (item?.kind !== "evaluation.save" || !item.server) return;
  await save({ ...item, status: "pending", baseVersion: item.server.version, server: undefined, error: undefined });
  await sync();
}

/** FR-PW6: drop this device's change, and anything queued after it for the same record. */
export async function discard(key: string): Promise<void> {
  const item = items.find((i) => i.key === key);
  if (!item) return;
  const ref = refOf(item);
  for (const other of items.filter((i) => refOf(i) === ref && i.created >= item.created)) {
    if (other.kind === "document.create") for (const page of other.pages) await store.del("blobs", page.blob);
    await remove(other.key);
  }
}

export async function retry(key: string): Promise<void> {
  const item = items.find((i) => i.key === key);
  if (!item) return;
  await save({ ...item, status: "pending", error: undefined });
  await sync();
}

/** For sign-out: forget everything this tab held in memory. */
export function forget(): void {
  items = [];
  latestVersion.clear();
  changed();
}
