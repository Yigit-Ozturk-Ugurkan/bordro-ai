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
    tokenStore.set({
      access_token: "expired-access",
      refresh_token: "valid-refresh",
      token_type: "bearer",
      expires_in: 900,
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(
        jsonResponse({
          access_token: "new-access",
          refresh_token: "new-refresh",
          token_type: "bearer",
          expires_in: 900,
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest<{ ok: boolean }>("/api/v1/auth/me")).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retryHeaders = fetchMock.mock.calls[2][1].headers as Headers;
    expect(retryHeaders.get("Authorization")).toBe("Bearer new-access");
  });

  it("clears the session when refresh fails", async () => {
    tokenStore.set({
      access_token: "expired-access",
      refresh_token: "invalid-refresh",
      token_type: "bearer",
      expires_in: 900,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse({}, 401)).mockResolvedValueOnce(jsonResponse({}, 401)),
    );

    await expect(apiRequest("/api/v1/auth/me")).rejects.toBeInstanceOf(ApiError);
    expect(tokenStore.get()).toBeNull();
  });
});
