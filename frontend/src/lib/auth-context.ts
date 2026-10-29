import { createContext, useContext } from "react";

import type { Role, User } from "./api";

export type SignOutReason = "user" | "expired";

export interface AuthContextValue {
  user: User | null;
  signIn: (email: string, password: string) => Promise<User>;
  /** "user" for an explicit sign-out, "expired" when the token ran out or was rejected. */
  signOut: (reason?: SignOutReason) => void;
  lastSignOut: SignOutReason | null;
  hasRole: (...roles: Role[]) => boolean;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
