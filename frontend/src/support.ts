/**
 * An admin's read-only support view of another user's screens (FR-AD3).
 *
 * While one is open, reads carry its id, and the server answers them as that user would see
 * them. Only reads do: anything the admin's own app sends (a queued offline save, a sign-out)
 * goes out as the admin, and the server refuses writes through a support view anyway. Nothing
 * seen in a support view is kept on the device.
 */
export interface SupportView {
  id: number;
  name: string;
  expires_at: string;
}

const KEY = "sces-support";
let current: SupportView | null = read();

function read(): SupportView | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    const view = raw ? (JSON.parse(raw) as SupportView) : null;
    return view && new Date(view.expires_at) > new Date() ? view : null;
  } catch {
    return null;
  }
}

export function supportView(): SupportView | null {
  if (current && new Date(current.expires_at) <= new Date()) current = null;
  return current;
}

export function startSupportView(view: SupportView): void {
  current = view;
  try {
    sessionStorage.setItem(KEY, JSON.stringify(view));
  } catch {
    // The view lasts for this page only.
  }
}

export function endSupportView(): void {
  current = null;
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nothing kept.
  }
}

export const SUPPORT_HEADER = "X-Support-Session";
