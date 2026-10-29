import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getAccessToken } from "../api/client";
import { type Actor, fetchMe, login as apiLogin, logout as apiLogout } from "../api/auth";

interface AuthState {
  actor: Actor | null;
  // True while an existing token's session is still being restored on load. RequireAuth
  // waits for this so a valid session is not mistaken for logged-out.
  bootstrapping: boolean;
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
  // While a token exists but the actor has not been resolved yet, auth is still being
  // established — we must not treat the user as logged out (which would bounce a deep link,
  // e.g. the Excel "Download Resume" URL, to the login page even though the session is valid).
  const [bootstrapping, setBootstrapping] = useState<boolean>(() => getAccessToken() !== null);

  // Restore the signed-in actor on mount when an access token is already present (e.g. the
  // SPA is reloaded, or a deep link is opened within a live session). Without this, actor
  // starts null and RequireAuth would redirect to login even though the token is valid.
  useEffect(() => {
    if (getAccessToken() === null) return;
    let cancelled = false;
    fetchMe()
      .then((me) => {
        if (!cancelled) setActor(me);
      })
      .catch(() => {
        /* token invalid/expired — remain logged out; RequireAuth sends the user to login */
      })
      .finally(() => {
        if (!cancelled) setBootstrapping(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    () => ({
      actor,
      bootstrapping,
      signIn,
      signOut,
      hasPermission,
      canAccessCampaign,
      refreshActor,
      token,
    }),
    [actor, bootstrapping, signIn, signOut, hasPermission, canAccessCampaign, refreshActor, token],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
