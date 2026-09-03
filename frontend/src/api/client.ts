import { tokenStore } from "../auth/tokenStore";
import type { TokenPair } from "./types";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001"
).replace(/[/]$/, "");

export const SESSION_EXPIRED_EVENT = "bordro-ai:session-expired";

export class ApiError extends Error {
  constructor(public readonly status: number) {
    super(`API request failed with status ${status}`);
    this.name = "ApiError";
  }
}

let refreshRequest: Promise<boolean> | null = null;

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) throw new ApiError(response.status);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function notifySessionExpired(): void {
  tokenStore.clear();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
}

async function refreshTokens(): Promise<boolean> {
  if (refreshRequest) return refreshRequest;

  refreshRequest = (async () => {
    const refreshToken = tokenStore.get()?.refreshToken;
    if (!refreshToken) return false;

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      const tokens = await parseResponse<TokenPair>(response);
      tokenStore.set(tokens);
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
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const accessToken = authenticated ? tokenStore.get()?.accessToken : null;
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (authenticated && response.status === 401 && retryAfterRefresh) {
    const refreshed = await refreshTokens();
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
