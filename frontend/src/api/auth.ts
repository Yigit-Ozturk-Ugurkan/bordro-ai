import { tokenStore } from "../auth/tokenStore";
import { apiRequest, publicRequest } from "./client";
import type { CurrentUser, TokenPair } from "./types";

export async function login(email: string, password: string): Promise<CurrentUser> {
  const tokens = await publicRequest<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  tokenStore.set(tokens);

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

export function logout(): void {
  tokenStore.clear();
}

export function hasSession(): boolean {
  return tokenStore.get() !== null;
}
