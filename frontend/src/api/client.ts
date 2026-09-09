import { tokenStore } from "../auth/tokenStore";
import type { AccessTokenResponse } from "./types";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8001"
).replace(/[/]$/, "");

export const SESSION_EXPIRED_EVENT = "bordro-ai:session-expired";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail?: string,
    public readonly code?: string,
  ) {
    super(`API request failed with status ${status}`);
    this.name = "ApiError";
  }
}

let refreshRequest: Promise<boolean> | null = null;

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: string | undefined;
    let code: string | undefined;
    try {
      const body = (await response.json()) as unknown;
      if (body && typeof body === "object") {
        const payload = body as Record<string, unknown>;
        if (typeof payload.detail === "string") detail = payload.detail;
        if (typeof payload.code === "string") code = payload.code;
      }
    } catch {
      // Non-JSON server failures intentionally fall back to a status-only error.
    }
    throw new ApiError(response.status, detail, code);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function notifySessionExpired(): void {
  tokenStore.clear();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
}

export async function refreshAccessToken(): Promise<boolean> {
  if (refreshRequest) return refreshRequest;

  refreshRequest = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      const tokens = await parseResponse<AccessTokenResponse>(response);
      tokenStore.set(tokens.access_token);
      return true;
    } catch {
      notifySessionExpired();
      return false;
    } finally {
      refreshRequest = null;
    }
  })();

  return refreshRequest;
}

async function request<T>(
  path: string,
  init: RequestInit,
  authenticated: boolean,
  retryAfterRefresh: boolean,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (
    init.body &&
    !(typeof FormData !== "undefined" && init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  const accessToken = authenticated ? tokenStore.get() : null;
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (authenticated && response.status === 401 && retryAfterRefresh) {
    const refreshed = await refreshAccessToken();
    if (refreshed) return request<T>(path, init, true, false);
  }

  if (authenticated && response.status === 401) notifySessionExpired();
  return parseResponse<T>(response);
}

export function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  return request<T>(path, init, true, true);
}

export function publicRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  return request<T>(path, init, false, false);
}
