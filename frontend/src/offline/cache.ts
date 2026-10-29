/**
 * Screens' data kept on the device for offline use (FR-PW3): the user's assigned schools
 * and teachers, open forms, the report catalog, their own drafts and documents' details.
 * Saved as each query loads, restored when the app starts. Only these query families are
 * kept, and only for the signed-in user; sign-out wipes them.
 */
import type { QueryClient } from "@tanstack/react-query";

import * as store from "./db";

const KEPT = new Set([
  "me",
  "district",
  "my-assignments",
  "forms",
  "form",
  "catalog",
  "evaluations",
  "evaluation",
  "documents",
  "document",
  "dashboard",
  "teachers",
  "requests",
  "request",
  "notifications",
]);

interface Saved {
  key: unknown[];
  data: unknown;
  at: number;
}

const id = (key: unknown[]) => `q:${JSON.stringify(key)}`;

export function kept(key: readonly unknown[]): boolean {
  return typeof key[0] === "string" && KEPT.has(key[0]);
}

/** Restore saved data, then keep saving whatever loads. */
export async function persist(client: QueryClient): Promise<void> {
  try {
    const saved = (await store.all<Saved>("kv")).filter((s) => s && Array.isArray(s.key));
    for (const s of saved) client.setQueryData(s.key, s.data, { updatedAt: s.at });
  } catch {
    // An unreadable store just means starting without offline data.
  }
  client.getQueryCache().subscribe((event) => {
    if (event.type !== "updated" || event.action.type !== "success") return;
    const key = event.query.queryKey as unknown[];
    if (!kept(key)) return;
    const data = event.query.state.data;
    if (data === undefined) return;
    void store.put("kv", id(key), { key, data, at: Date.now() } satisfies Saved).catch(() => undefined);
  });
}
