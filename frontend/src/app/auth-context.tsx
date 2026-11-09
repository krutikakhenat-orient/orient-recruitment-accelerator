import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getAccessToken, refreshSession } from "../api/client";
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

// Candidate-facing pages never use a staff session, so they skip session restoration.
function isPublicPath(): boolean {
  const p = window.location.pathname;
  return p.startsWith("/apply") || p.startsWith("/ai-interview");
}

export function AuthProvider({ children }: { children: ReactNode }): ReactNode {
  const [actor, setActor] = useState<Actor | null>(null);
  // While a token exists but the actor has not been resolved yet, auth is still being
  // established — we must not treat the user as logged out (which would bounce a deep link,
  // e.g. the Excel "Download Resume" URL, to the login page even though the session is valid).
  const [bootstrapping, setBootstrapping] = useState<boolean>(() => !isPublicPath());

  // Restore the signed-in actor on mount. The access token is memory-only, so after a hard
  // refresh it is gone; the HttpOnly refresh cookie lets us quietly get a new one. Without
  // this the page reloaded to the login screen every time. Public candidate pages skip it.
  useEffect(() => {
    if (isPublicPath()) return;
    let cancelled = false;
    const restore = async (): Promise<Actor | null> => {
      if (getAccessToken() === null && !(await refreshSession())) return null;
      return fetchMe();
    };
    restore()
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
