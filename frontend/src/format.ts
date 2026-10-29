/** Dates are shown as D/MM/YYYY and numbers use Western digits in both languages (FR-I5). */

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** "2026-11-05" -> "5/11/2026". Calendar dates have no time zone, so no conversion is applied. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return "";
  return `${day}/${pad(month)}/${year}`;
}

/** "5/11/2026" -> "2026-11-05", or null if it is not a real date. */
export function parseDate(text: string): string | null {
  const match = text.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (!match) return null;
  const [day, month, year] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return `${year}-${pad(month)}-${pad(day)}`;
}

/** Server timestamps are naive UTC. Shows D/MM/YYYY HH:MM in the district's time zone. */
export function formatDateTime(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return "";
  const instant = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  if (Number.isNaN(instant.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(instant);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${Number(get("day"))}/${get("month")}/${get("year")} ${get("hour")}:${get("minute")}`;
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}
