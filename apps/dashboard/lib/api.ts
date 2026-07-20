const API_URL = process.env.NEXT_PUBLIC_FRONTIER_API_URL ?? "http://localhost:8000";

export class APIRequestError extends Error {
  constructor(public readonly code: string, message: string, public readonly status: number) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  const body = response.status === 204 ? undefined : await response.json();
  if (!response.ok) {
    const detail = body?.error ?? body?.detail;
    const code = typeof detail === "object" && detail && "code" in detail ? String(detail.code) : "request_failed";
    const message =
      typeof detail === "object" && detail && "message" in detail
        ? String(detail.message)
        : typeof detail === "string"
          ? detail
          : "Request failed";
    throw new APIRequestError(code, message, response.status);
  }
  return body as T;
}

export function eventUrl(path: string): string {
  return `${API_URL}${path}`;
}

export function exportUrl(batchId: string): string {
  return `${API_URL}/api/exports/${encodeURIComponent(batchId)}.json`;
}
