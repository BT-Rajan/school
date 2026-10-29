import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";

import { api, ApiError, query } from "../api";
import type { Assignment, FormDetail, FormSummary, Page, Teacher } from "../types";
import * as queue from "./queue";

export function useQueue(): queue.Item[] {
  return useSyncExternalStore(queue.subscribe, queue.snapshot);
}

export function isOfflineError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 0;
}

export function useOnline(): boolean {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

/**
 * FR-PW3: while online, load what a supervisor needs in the field, so it is on the device
 * when the connection goes: assigned schools and their teachers, open forms, the catalog.
 */
export function usePrepareOffline(enabled: boolean): void {
  const client = useQueryClient();
  const online = useOnline();
  const assignments = useQuery({
    queryKey: ["my-assignments"],
    queryFn: () => api<Assignment[]>("/api/me/assignments"),
    enabled: enabled && online,
  });
  const forms = useQuery({ queryKey: ["forms"], queryFn: () => api<FormSummary[]>("/api/forms"), enabled: enabled && online });
  useEffect(() => {
    if (!enabled || !online) return;
    void client.prefetchQuery({ queryKey: ["catalog"], queryFn: () => api("/api/catalog") });
    for (const f of (forms.data ?? []).filter((f) => f.status === "active")) {
      void client.prefetchQuery({ queryKey: ["form", String(f.id)], queryFn: () => api<FormDetail>(`/api/forms/${f.id}`) });
    }
    for (const a of (assignments.data ?? []).filter((a) => a.state === "active")) {
      const schoolId = String(a.school.id);
      void client.prefetchQuery({
        queryKey: ["teachers", "school", schoolId],
        queryFn: () => api<Page<Teacher>>(`/api/teachers${query({ school_id: schoolId, status: "active", page_size: 200 })}`),
      });
    }
  }, [enabled, online, forms.data, assignments.data, client]);
}
