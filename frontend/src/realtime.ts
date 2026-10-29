/**
 * Live updates (FR-RT1 to FR-RT3). The server sends only "this record changed" for records
 * this user may see; the screen then refetches through the API. After any gap the whole
 * cache is refetched, so nothing missed while disconnected stays stale.
 */
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export type LiveState = "connecting" | "live" | "offline";

type Message = { type: "ready" | "ping" | "notification" } | { type: "changed"; entity: string; id: string };

// Query keys that show each kind of record.
const KEYS: Record<string, (id: string) => unknown[][]> = {
  document: (id) => [["documents"], ["document", id], ["document-access", id], ["dashboard"], ["evaluation-documents"]],
  evaluation: (id) => [["evaluations"], ["evaluation", id], ["amendments", id]],
  request: (id) => [["requests"], ["request", id], ["request-history", id], ["evaluation"]],
  assignment: () => [["board"], ["my-assignments"], ["assignment-history"], ["dashboard"]],
  form: (id) => [["forms"], ["form", id], ["form-comments", id], ["catalog"]],
  school: () => [["schools"], ["board"]],
  teacher: () => [["teachers"], ["teacher-onboarding"]],
  cluster: () => [["clusters"], ["board"]],
  supervisor: () => [["supervisors"], ["board"]],
  user: () => [["staff"], ["teachers"], ["supervisors"], ["teacher-onboarding"]],
};

export function applyMessage(client: QueryClient, message: Message): void {
  if (message.type === "notification") {
    void client.invalidateQueries({ queryKey: ["notifications"] });
  } else if (message.type === "changed") {
    for (const key of KEYS[message.entity]?.(message.id) ?? []) void client.invalidateQueries({ queryKey: key });
  }
}

/** Connects while signed in. WebSocket first; Server-Sent Events if it keeps failing. */
export function useRealtime(userId: number | null): LiveState {
  const client = useQueryClient();
  const [state, setState] = useState<LiveState>("connecting");
  useEffect(() => {
    if (userId === null) return;
    let stopped = false;
    let attempt = 0;
    let wsFailures = 0;
    let timer: number | undefined;
    let waiting = false;
    let close: () => void = () => {};
    let everLive = false;

    const onReady = () => {
      // A reconnect may have missed events: refetch everything on screen.
      if (everLive) void client.invalidateQueries();
      everLive = true;
      attempt = 0;
      setState("live");
    };
    const onMessage = (data: string) => {
      const message = JSON.parse(data) as Message;
      if (message.type === "ready") onReady();
      else applyMessage(client, message);
    };
    const retry = () => {
      if (stopped) return;
      setState(navigator.onLine ? "connecting" : "offline");
      // Backoff with jitter: 1 s, 2 s, 4 s ... up to 30 s.
      const delay = Math.min(30000, 1000 * 2 ** attempt) * (0.75 + Math.random() / 2);
      attempt += 1;
      waiting = true;
      timer = window.setTimeout(connect, delay);
    };
    const connect = () => {
      waiting = false;
      if (stopped) return;
      if (wsFailures >= 3 && "EventSource" in window) {
        const source = new EventSource("/api/realtime/events");
        source.onmessage = (e) => onMessage(e.data);
        source.onerror = () => {
          source.close();
          retry();
        };
        close = () => source.close();
        return;
      }
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${scheme}://${location.host}/api/realtime/ws`);
      let opened = false;
      socket.onmessage = (e) => {
        opened = true;
        onMessage(e.data);
      };
      socket.onclose = (e) => {
        if (stopped) return;
        if (!opened) wsFailures += 1;
        // 4401: the session ended. The next API call shows the sign-in screen.
        if (e.code === 4401) void client.invalidateQueries({ queryKey: ["me"] });
        retry();
      };
      close = () => socket.close();
    };
    // Back online: try at once rather than waiting out the backoff.
    const wake = () => {
      if (!stopped && waiting) {
        window.clearTimeout(timer);
        attempt = 0;
        connect();
      }
    };
    connect();
    window.addEventListener("online", wake);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      window.removeEventListener("online", wake);
      close();
    };
  }, [userId, client]);
  return state;
}
