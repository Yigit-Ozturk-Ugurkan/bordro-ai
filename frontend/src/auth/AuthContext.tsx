import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import * as authApi from "../api/auth";
import { SESSION_EXPIRED_EVENT } from "../api/client";
import type { CurrentUser } from "../api/types";

export interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    authApi
      .restoreSession()
      .then((currentUser) => {
        if (active) setUser(currentUser);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    const expireSession = () => {
      if (active) {
        setUser(null);
        setLoading(false);
      }
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expireSession);

    return () => {
      active = false;
      window.removeEventListener(SESSION_EXPIRED_EVENT, expireSession);
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const currentUser = await authApi.login(email, password);
    setUser(currentUser);
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    void authApi.logout();
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
