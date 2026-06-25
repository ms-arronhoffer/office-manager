import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { AuthPayload } from "../types";

interface AuthContextValue {
  token: string | null;
  payload: AuthPayload | null;
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
  const [token, setTokenState] = useState<string | null>(
    () => localStorage.getItem("admin_token")
  );
  const [payload, setPayload] = useState<AuthPayload | null>(() => {
    const t = localStorage.getItem("admin_token");
    return t ? decodePayload(t) : null;
  });

  const setToken = useCallback((t: string) => {
    localStorage.setItem("admin_token", t);
    setTokenState(t);
    setPayload(decodePayload(t));
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("admin_token");
    setTokenState(null);
    setPayload(null);
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
    () => ({ token, payload, setToken, logout }),
    [token, payload, setToken, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
