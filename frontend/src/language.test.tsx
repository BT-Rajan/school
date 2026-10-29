import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "./i18n";
import { LanguageSwitch } from "./components";
import i18n from "./i18n";
import ar from "./locales/ar";
import en from "./locales/en";
import { SessionProvider } from "./session";

function Form() {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  return (
    <label>
      {t("teachers.name")}
      <input aria-label="name" value={name} onChange={(e) => setName(e.target.value)} />
    </label>
  );
}

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" ? keys(v as object, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe("language switching", () => {
  beforeEach(() => {
    // Signed out: /api/auth/me answers 401 and /api/district answers with the district.
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      url.endsWith("/api/auth/me")
        ? new Response(JSON.stringify({ error: { code: "not_authenticated" } }), { status: 401 })
        : new Response(JSON.stringify({ code: "KW", name_en: "D", name_ar: "م", time_zone: "Asia/Kuwait" })),
    ));
    void i18n.changeLanguage("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("switches to Arabic right to left and keeps unsaved input", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SessionProvider>
          <Form />
          <LanguageSwitch />
        </SessionProvider>
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByLabelText("name"), { target: { value: "Fatima" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Language" }));
    });
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.documentElement.lang).toBe("ar");
    expect(screen.getByText("اسم المعلم")).toBeTruthy();
    expect((screen.getByLabelText("name") as HTMLInputElement).value).toBe("Fatima");
    expect(localStorage.getItem("sces.locale")).toBe("ar");
  });

  it("has an Arabic string for every English one", () => {
    expect(keys(ar).sort()).toEqual(keys(en).sort());
  });
});
