import { tokenStore } from "../auth/tokenStore";
import { apiRequest, publicRequest, refreshAccessToken } from "./client";
import type { AccessTokenResponse, CurrentUser } from "./types";

export async function login(email: string, password: string): Promise<CurrentUser> {
  const tokens = await publicRequest<AccessTokenResponse>("/api/v1/auth/login", {
    method: "POST",
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  tokenStore.set(tokens.access_token);

  try {
    return await getCurrentUser();
  } catch (error) {
    tokenStore.clear();
    throw error;
  }
}

export function getCurrentUser(): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/api/v1/auth/me");
}

export async function restoreSession(): Promise<CurrentUser> {
  if (!(await refreshAccessToken())) throw new Error("Session unavailable");
  return getCurrentUser();
}

export async function logout(): Promise<void> {
  tokenStore.clear();
  try {
    await publicRequest<void>("/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // Logout is locally final even if the server is temporarily unreachable.
  }
}
