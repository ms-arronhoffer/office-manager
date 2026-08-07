import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { AuthPayload } from "../types";
import { getConsoleMe } from "../api";

interface AuthContextValue {
  token: string | null;
  payload: AuthPayload | null;
  loading: boolean;
  setToken: (t: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function decodePayload(token: string): AuthPayload | null {
  try {
    const part = token.split(".")[1];
    return JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [payload, setPayload] = useState<AuthPayload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getConsoleMe()
      .then((me) => {
        setTokenState("cookie");
        setPayload({
          sub: me.id,
          role: me.role,
          org_id: null,
          is_super_admin: me.is_super_admin,
          console_role: me.console_role,
          exp: Math.floor(Date.now() / 1000) + 30 * 60,
        });
      })
      .catch(() => {
        setTokenState(null);
        setPayload(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const setToken = useCallback((t: string) => {
    setTokenState("cookie");
    setPayload(decodePayload(t));
    setLoading(false);
  }, []);

  const logout = useCallback(() => {
    setTokenState(null);
    setPayload(null);
    setLoading(false);
  }, []);

  // Auto-logout on token expiry
  useEffect(() => {
    if (!payload) return;
    const ms = payload.exp * 1000 - Date.now();
    if (ms <= 0) { logout(); return; }
    const id = setTimeout(logout, ms);
    return () => clearTimeout(id);
  }, [payload, logout]);

  const value = useMemo(
    () => ({ token, payload, loading, setToken, logout }),
    [token, payload, loading, setToken, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
