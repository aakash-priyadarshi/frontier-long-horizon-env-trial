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
    throw new APIRequestError(body?.error?.code ?? "request_failed", body?.error?.message ?? "Request failed", response.status);
  }
  return body as T;
}

export function eventUrl(path: string): string {
  return `${API_URL}${path}`;
}

export function exportUrl(batchId: string): string {
  return `${API_URL}/api/exports/${encodeURIComponent(batchId)}.json`;
}
