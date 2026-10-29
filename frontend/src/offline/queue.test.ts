import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as queue from "./queue";

type Call = { method: string; url: string; body: Record<string, unknown> | null };

function server(handler: (call: Call) => { status: number; body?: unknown }) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
    const call = { method: init.method ?? "GET", url, body: init.body ? JSON.parse(String(init.body)) : null };
    calls.push(call);
    const { status, body } = handler(call);
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const offline = () => vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
const evaluation = (id: number, version: number) => ({ id, version, sections: [], visit_date: null, visit_notes: null });
const body = (comment: string) => ({ visit_date: "2026-11-10", visit_notes: comment, sections: { visit: { rating: 3 } } });

beforeEach(() => queue.forget());
afterEach(() => vi.unstubAllGlobals());

describe("offline queue", () => {
  it("keeps work while offline, then sends it in order, once", async () => {
    offline();
    await queue.enqueueStart(-1, { form_id: 1, school_id: 2, teacher_id: null, visit_date: "2026-11-10", client_key: "k-1" }, "x");
    await queue.enqueueSave(-1, null, body("first"), "x");
    await queue.enqueueSave(-1, null, body("second"), "x");
    await queue.enqueueSubmit(-1, "x");
    await queue.sync();
    // Two saves of the same draft became one, with the latest answers.
    expect(queue.snapshot().map((i) => i.kind)).toEqual(["evaluation.start", "evaluation.save", "evaluation.submit"]);
    expect(queue.snapshot().every((i) => i.status === "pending")).toBe(true);

    const calls = server((call) => {
      if (call.url === "/api/evaluations") return { status: 201, body: evaluation(55, 1) };
      if (call.method === "PATCH") return { status: 200, body: evaluation(55, 2) };
      return { status: 200, body: evaluation(55, 3) };
    });
    await queue.sync();
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "POST /api/evaluations",
      "PATCH /api/evaluations/55",
      "POST /api/evaluations/55/submit",
    ]);
    // The client key lets the server confirm a replay rather than create a second evaluation.
    expect(calls[0].body?.client_key).toBe("k-1");
    expect(calls[1].body).toMatchObject({ version: 1, visit_notes: "second" });
    expect(calls[2].body).toMatchObject({ version: 2 });
    expect(typeof calls[2].body?.device_time).toBe("string");
    expect(queue.snapshot()).toEqual([]);
    expect(await queue.serverId(-1)).toBe(55);
  });

  it("stops at a conflict and lets the user keep their answers", async () => {
    let patches = 0;
    const calls = server((call) => {
      if (call.method === "PATCH") {
        patches += 1;
        if (patches === 1) return { status: 409, body: { error: { code: "version_conflict", detail: { current: evaluation(9, 4) } } } };
        return { status: 200, body: evaluation(9, 5) };
      }
      return { status: 200, body: evaluation(9, 6) };
    });
    await queue.enqueueSave(9, 2, body("mine"), "x");
    await queue.enqueueSubmit(9, "x");
    await queue.sync();
    const [save, submit] = queue.snapshot();
    expect(save.status).toBe("conflict");
    // Nothing later about the same evaluation goes ahead of the user's choice.
    expect(submit.status).toBe("pending");
    expect(calls.filter((c) => c.url.endsWith("/submit"))).toEqual([]);
    await queue.keepMine(save.key);
    expect(calls.at(-2)?.body).toMatchObject({ version: 4, visit_notes: "mine" });
    expect(calls.at(-1)?.url).toBe("/api/evaluations/9/submit");
    expect(queue.snapshot()).toEqual([]);
  });

  it("refuses more files than a device should hold", async () => {
    offline();
    const big = new File([new Uint8Array(10)], "a.jpg", { type: "image/jpeg" });
    Object.defineProperty(big, "size", { value: 150 * 1024 * 1024 });
    await queue.enqueueDocument([big], {}, true, "x");
    await expect(queue.enqueueDocument([big], {}, true, "x")).rejects.toBeInstanceOf(queue.QueueFullError);
  });
});
