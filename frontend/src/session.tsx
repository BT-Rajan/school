import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "./api";
import { type Locale, setLocale } from "./i18n";
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

  // On sign-in, the user's saved language wins over the device's. Applied once
  // per user, so a switch made afterwards is not undone while it is being saved.
  const appliedFor = useRef<number | null>(null);
  useEffect(() => {
    if (!me) {
      appliedFor.current = null;
      return;
    }
    if (appliedFor.current !== me.id) {
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
      try {
        await api("/api/auth/logout", { method: "POST" });
      } finally {
        // Mounted screens keep their query data, so mark the user signed out explicitly
        // and drop everything cached for them.
        client.setQueryData(["me"], null);
        client.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" && q.queryKey[0] !== "district" });
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
