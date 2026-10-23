import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { getAccessToken } from "../api/client";
import { type Actor, fetchMe, login as apiLogin, logout as apiLogout } from "../api/auth";

interface AuthState {
  actor: Actor | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  hasPermission: (permission: string) => boolean;
  canAccessCampaign: (campaignId: string) => boolean;
  refreshActor: () => Promise<void>;
  token: () => string | null;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }): ReactNode {
  const [actor, setActor] = useState<Actor | null>(null);

  const signIn = useCallback(async (email: string, password: string) => {
    await apiLogin(email, password);
    setActor(await fetchMe());
  }, []);

  const signOut = useCallback(() => {
    apiLogout();
    setActor(null);
  }, []);

  const hasPermission = useCallback(
    (permission: string) => actor?.permissions.includes(permission) ?? false,
    [actor],
  );

  const canAccessCampaign = useCallback(
    (campaignId: string) => actor?.assigned_campaign_ids.includes(campaignId) ?? false,
    [actor],
  );

  const refreshActor = useCallback(async () => {
    setActor(await fetchMe());
  }, []);

  const token = useCallback(() => getAccessToken(), []);

  const value = useMemo(
    () => ({ actor, signIn, signOut, hasPermission, canAccessCampaign, refreshActor, token }),
    [actor, signIn, signOut, hasPermission, canAccessCampaign, refreshActor, token],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
