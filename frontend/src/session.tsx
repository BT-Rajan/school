import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "./api";
import i18next from "./i18n";
import { type Locale, setLocale } from "./i18n";
import * as store from "./offline/db";
import * as queue from "./offline/queue";
import { disablePush } from "./push";
import type { District, Me } from "./types";

interface Session {
  me: Me | null;
  district: District | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
  changeLocale: (locale: Locale) => void;
}

const SessionContext = createContext<Session | null>(null);

async function fetchMe(): Promise<Me | null> {
  try {
    return await api<Me>("/api/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const { i18n } = useTranslation();
  const meQuery = useQuery({ queryKey: ["me"], queryFn: fetchMe, retry: false, staleTime: 60_000 });
  const districtQuery = useQuery({
    queryKey: ["district"],
    queryFn: () => api<District>("/api/district"),
    staleTime: Infinity,
  });
  const me = meQuery.data ?? null;

  // A different person signing in on a shared phone starts with a clean device.
  useEffect(() => {
    if (!me || !meQuery.isSuccess || meQuery.isFetching) return;
    // An admin's support view shows another account on the admin's own device: not a new owner.
    if (me.support_view) return;
    const owner = readOwner();
    if (owner !== null && owner !== String(me.id)) void wipeDevice().then(() => writeOwner(me.id));
    else if (owner === null) writeOwner(me.id);
  }, [me, meQuery.isSuccess, meQuery.isFetching]);

  // On sign-in, the user's saved language wins over the device's. Applied once
  // per user, so a switch made afterwards is not undone while it is being saved.
  const appliedFor = useRef<number | null>(null);
  useEffect(() => {
    if (!me) {
      appliedFor.current = null;
      return;
    }
    if (appliedFor.current !== me.id && !me.support_view) {
      appliedFor.current = me.id;
      if (me.locale !== i18n.language) setLocale(me.locale);
    }
  }, [me, i18n.language]);

  const value: Session = {
    me,
    district: districtQuery.data ?? null,
    loading: meQuery.isLoading,
    refresh: async () => {
      await client.invalidateQueries({ queryKey: ["me"] });
    },
    signOut: async () => {
      // FR-PW12: unsent work is lost with the rest of the device's data, so ask first.
      const waiting = queue.snapshot().length;
      if (waiting > 0 && !window.confirm(i18next.t("offline.confirmSignOut", { count: waiting }))) return;
      await disablePush().catch(() => undefined);
      try {
        await api("/api/auth/logout", { method: "POST" });
      } catch {
        // Offline: finish signing out with the server once the phone is back online.
        markPendingSignOut();
      } finally {
        // Mounted screens keep their query data, so mark the user signed out explicitly
        // and drop everything cached for them, on screen and on the device.
        client.setQueryData(["me"], null);
        client.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" && q.queryKey[0] !== "district" });
        await wipeDevice();
      }
    },
    changeLocale: (locale) => {
      setLocale(locale);
      if (me) {
        api<Me>("/api/auth/me", { method: "PATCH", body: { locale } })
          .then((updated) => client.setQueryData(["me"], updated))
          .catch(() => undefined);
      }
    },
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession outside SessionProvider");
  return session;
}

export function districtName(district: District | null, locale: string): string {
  if (!district) return "";
  return locale === "ar" ? district.name_ar : district.name_en;
}

const OWNER = "sces.owner";
const PENDING_SIGN_OUT = "sces.pendingSignOut";

function readOwner(): string | null {
  try {
    return localStorage.getItem(OWNER);
  } catch {
    return null;
  }
}

function writeOwner(id: number): void {
  try {
    localStorage.setItem(OWNER, String(id));
  } catch {
    // Storage unavailable: nothing is kept on the device either.
  }
}

function markPendingSignOut(): void {
  try {
    localStorage.setItem(PENDING_SIGN_OUT, "1");
  } catch {
    // Without storage the next visit starts signed in; the session still ends at its idle limit.
  }
}

/** Run at start-up: a sign-out made offline is completed with the server. */
export async function finishPendingSignOut(): Promise<void> {
  try {
    if (localStorage.getItem(PENDING_SIGN_OUT) !== "1") return;
    await api("/api/auth/logout", { method: "POST" });
    localStorage.removeItem(PENDING_SIGN_OUT);
  } catch (error) {
    if (error instanceof ApiError && error.status !== 0) localStorage.removeItem(PENDING_SIGN_OUT);
  }
}

/** FR-PW12: IndexedDB, Cache Storage and the queue, all gone. */
export async function wipeDevice(): Promise<void> {
  queue.forget();
  await store.wipe().catch(() => undefined);
  try {
    localStorage.removeItem(OWNER);
    sessionStorage.clear();
  } catch {
    // Nothing to clear.
  }
  if ("caches" in window) {
    for (const name of await caches.keys()) await caches.delete(name);
    // The worker puts back only the app's own files (public/sw.js).
    try {
      (await navigator.serviceWorker?.getRegistration())?.active?.postMessage({ type: "recache" });
    } catch {
      // No worker: nothing to put back.
    }
  }
}
