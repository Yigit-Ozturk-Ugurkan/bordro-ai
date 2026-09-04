import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest, ApiError } from "../api/client";
import { tokenStore } from "../auth/tokenStore";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("authenticated API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    tokenStore.clear();
  });

  it("refreshes once after 401 and retries with the new access token", async () => {
    tokenStore.set("expired-access");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(
        jsonResponse({
          access_token: "new-access",
          token_type: "bearer",
          expires_in: 900,
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiRequest<{ ok: boolean }>("/api/v1/auth/me"),
    ).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: "POST",
      credentials: "include",
    });
    expect(fetchMock.mock.calls[1][1]).not.toHaveProperty("body");
    const retryHeaders = fetchMock.mock.calls[2][1].headers as Headers;
    expect(retryHeaders.get("Authorization")).toBe("Bearer new-access");
  });

  it("shares one refresh flow across concurrent 401 responses", async () => {
    tokenStore.set("expired-access");
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v1/auth/refresh")) {
        return jsonResponse({
          access_token: "new-access",
          token_type: "bearer",
          expires_in: 900,
        });
      }
      const headers = init?.headers as Headers;
      return headers.get("Authorization") === "Bearer new-access"
        ? jsonResponse({ ok: true })
        : jsonResponse({}, 401);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      Promise.all([
        apiRequest<{ ok: boolean }>("/first"),
        apiRequest<{ ok: boolean }>("/second"),
      ]),
    ).resolves.toEqual([{ ok: true }, { ok: true }]);

    const refreshCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).endsWith("/api/v1/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
  });

  it("clears the in-memory session when refresh fails", async () => {
    tokenStore.set("expired-access");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({}, 401))
        .mockResolvedValueOnce(jsonResponse({}, 401)),
    );

    await expect(apiRequest("/api/v1/auth/me")).rejects.toBeInstanceOf(ApiError);
    expect(tokenStore.get()).toBeNull();
  });

  it("never persists the access token in browser storage", () => {
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    tokenStore.set("memory-only-access");

    expect(storageWrite).not.toHaveBeenCalled();
    expect(tokenStore.get()).toBe("memory-only-access");
  });
});
