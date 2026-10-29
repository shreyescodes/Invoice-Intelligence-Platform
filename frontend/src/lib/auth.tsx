import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { login as loginRequest, setAccessToken, setUnauthorizedHandler, type User } from "./api";
import { AuthContext, type AuthContextValue, type SignOutReason } from "./auth-context";

const STORAGE_KEY = "iip-session";

interface Session {
  token: string;
  user: User;
  expiresAt: number;
}

function readSession(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as Session;
    return session.expiresAt > Date.now() ? session : null;
  } catch {
    return null;
  }
}

function writeSession(session: Session | null) {
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode); the session then lasts for this tab only.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<Session | null>(() => {
    const restored = readSession();
    setAccessToken(restored?.token ?? null);
    return restored;
  });
  const [lastSignOut, setLastSignOut] = useState<SignOutReason | null>(null);

  const signOut = useCallback((reason: SignOutReason = "user") => {
    setLastSignOut(reason);
    setAccessToken(null);
    writeSession(null);
    setSession(null);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    setUnauthorizedHandler(() => signOut("expired"));
    return () => setUnauthorizedHandler(null);
  }, [signOut]);

  useEffect(() => {
    if (!session) return;
    const timer = window.setTimeout(() => signOut("expired"), Math.max(0, session.expiresAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [session, signOut]);

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await loginRequest(email, password);
    const next: Session = {
      token: result.access_token,
      user: result.user,
      expiresAt: Date.now() + result.expires_in * 1000,
    };
    setAccessToken(next.token);
    writeSession(next);
    setSession(next);
    return result.user;
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user: session?.user ?? null,
      signIn,
      signOut,
      lastSignOut,
      hasRole: (...roles) => (session ? roles.includes(session.user.role) : false),
    }),
    [session, signIn, signOut, lastSignOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
