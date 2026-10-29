import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { applyMessage } from "./realtime";

describe("live updates refetch what changed", () => {
  it("marks only the affected queries stale", () => {
    const client = new QueryClient();
    for (const key of [["documents", {}], ["document", "7"], ["document", "8"], ["evaluations"], ["notifications"]]) {
      client.setQueryData(key, { ok: true });
    }
    applyMessage(client, { type: "changed", entity: "document", id: "7" });
    const stale = (key: unknown[]) => client.getQueryState(key)?.isInvalidated;
    expect(stale(["documents", {}])).toBe(true);
    expect(stale(["document", "7"])).toBe(true);
    expect(stale(["document", "8"])).toBe(false);
    expect(stale(["evaluations"])).toBe(false);
    applyMessage(client, { type: "notification" });
    expect(stale(["notifications"])).toBe(true);
  });
});
