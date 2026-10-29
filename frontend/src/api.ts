/** JSON API client. Errors carry the server's stable code, which the UI translates. */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public detail?: unknown,
  ) {
    super(code);
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)sces_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

type Options = { method?: string; body?: unknown; form?: FormData };

async function request(path: string, { method = "GET", body, form }: Options = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (!response.ok) {
    let code = "generic";
    let detail: unknown;
    try {
      const data = await response.json();
      code = data?.error?.code ?? code;
      detail = data?.error?.detail;
    } catch {
      // Not JSON, for example a proxy error page.
    }
    throw new ApiError(response.status, code, detail);
  }
  return response;
}

export async function api<T = unknown>(path: string, options: Options = {}): Promise<T> {
  const response = await request(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function download(path: string, filename: string): Promise<void> {
  const response = await request(path);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Upload one file to the file service (FR-FS2). The server checks, cleans and scans it. */
export async function uploadFile<T>(file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file, file.name);
  return api<T>("/api/files", { method: "POST", form });
}

/**
 * Open a short-lived, session-bound link in a new tab. The tab is opened before the
 * request so browsers treat it as a direct result of the click and do not block it.
 */
export async function openLink(getLink: () => Promise<{ url: string }>): Promise<void> {
  const tab = window.open("", "_blank");
  try {
    const { url } = await getLink();
    if (tab) tab.location.href = url;
    else window.location.assign(url);
  } catch (error) {
    tab?.close();
    throw error;
  }
}
