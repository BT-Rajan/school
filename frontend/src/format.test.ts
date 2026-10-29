import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime, parseDate } from "./format";

describe("dates in D/MM/YYYY", () => {
  it("formats ISO dates without shifting the day", () => {
    expect(formatDate("2026-11-05")).toBe("5/11/2026");
    expect(formatDate("2026-01-30")).toBe("30/01/2026");
    expect(formatDate("")).toBe("");
  });

  it("parses typed dates and rejects impossible ones", () => {
    expect(parseDate("5/11/2026")).toBe("2026-11-05");
    expect(parseDate("05/11/2026")).toBe("2026-11-05");
    expect(parseDate("31/02/2026")).toBeNull();
    expect(parseDate("2026-11-05")).toBeNull();
  });

  it("shows server UTC timestamps in the district time zone", () => {
    // 21:30 UTC is 00:30 the next day in Kuwait.
    expect(formatDateTime("2026-11-05T21:30:00", "Asia/Kuwait")).toBe("6/11/2026 00:30");
  });
});
