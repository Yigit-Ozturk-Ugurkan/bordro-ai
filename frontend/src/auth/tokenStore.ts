import type { TokenPair } from "../api/types";

const STORAGE_KEY = "bordro-ai.auth-session";

interface StoredTokens {
  accessToken: string;
  refreshToken: string;
}

function storageAvailable(): boolean {
  return typeof window !== "undefined" && Boolean(window.sessionStorage);
}

export const tokenStore = {
  get(): StoredTokens | null {
    if (!storageAvailable()) return null;
    const stored = window.sessionStorage.getItem(STORAGE_KEY);
    if (!stored) return null;

    try {
      const parsed = JSON.parse(stored) as Partial<StoredTokens>;
      if (!parsed.accessToken || !parsed.refreshToken) return null;
      return {
        accessToken: parsed.accessToken,
        refreshToken: parsed.refreshToken,
      };
    } catch {
      window.sessionStorage.removeItem(STORAGE_KEY);
      return null;
    }
  },

  set(tokens: TokenPair): void {
    if (!storageAvailable()) return;
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
      }),
    );
  },

  clear(): void {
    if (storageAvailable()) window.sessionStorage.removeItem(STORAGE_KEY);
  },
};
