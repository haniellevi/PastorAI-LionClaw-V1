"use client";

/**
 * Sessão do console Super-Admin (plano de plataforma), isolada do painel da
 * igreja. Usa uma chave de token PRÓPRIA (`pastorai:admin-token`) para que
 * logar no console não interfira na sessão do painel operacional e vice-versa.
 *
 * Login: POST /admin/login (dedicado, isento do gate de billing do tenant — o
 * master entra mesmo com a igreja-casa suspensa) e, na sequência, /admin/me —
 * que só responde 200 para quem está na allowlist platform_admins.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  adminLogin,
  AdminAuthError,
  AdminSessionExpiredError,
  fetchAdminMe,
  type AdminMe,
} from "./admin-api";

const ADMIN_TOKEN_KEY = "pastorai:admin-token";

export type AdminAuthStatus =
  | "loading"
  | "unavailable"
  | "unauthenticated"
  | "authenticated";

interface AdminAuthValue {
  status: AdminAuthStatus;
  admin: AdminMe | null;
  token: string | null;
  /** Motivo terminal devolvido pelo gate da plataforma. */
  accessMessage: string | null;
  /** Autentica via /admin/login + /admin/me. Repassa o erro em caso de falha. */
  login: (email: string, password: string) => Promise<void>;
  /** Repete a validação de um token preservado após falha transitória. */
  retrySession: () => void;
  logout: () => void;
}

const AdminAuthContext = createContext<AdminAuthValue | null>(null);

function readToken(): string | null {
  try {
    return window.localStorage.getItem(ADMIN_TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null) {
  try {
    if (token) window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
    else window.localStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    /* armazenamento indisponível: sessão fica só em memória */
  }
}

function preloadAdminConsole(): void {
  void import("@/components/admin/AdminConsole");
}

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AdminAuthStatus>("loading");
  const [admin, setAdmin] = useState<AdminMe | null>(null);
  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const tokenRef = useRef<string | null>(null);

  // Bootstrap: restaura a sessão do console a partir do token persistido.
  useEffect(() => {
    let active = true;
    const token = readToken();
    if (!token) {
      setStatus("unauthenticated");
      return;
    }
    tokenRef.current = token;
    preloadAdminConsole();
    fetchAdminMe(token)
      .then((me) => {
        if (!active) return;
        setAdmin(me);
        setAccessMessage(null);
        setStatus("authenticated");
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (
          error instanceof AdminSessionExpiredError ||
          (error instanceof AdminAuthError && error.kind === "forbidden")
        ) {
          tokenRef.current = null;
          writeToken(null);
          setAccessMessage(
            error instanceof AdminAuthError ? error.message : null,
          );
          setStatus("unauthenticated");
        } else {
          setAccessMessage(null);
          setStatus("unavailable");
        }
        setAdmin(null);
      });
    return () => {
      active = false;
    };
  }, [bootstrapAttempt]);

  const retrySession = useCallback(() => {
    setStatus("loading");
    setBootstrapAttempt((attempt) => attempt + 1);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { token } = await adminLogin(email, password);
    preloadAdminConsole();
    const me = await fetchAdminMe(token);
    tokenRef.current = token;
    writeToken(token);
    setAdmin(me);
    setAccessMessage(null);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(() => {
    tokenRef.current = null;
    writeToken(null);
    setAdmin(null);
    setAccessMessage(null);
    setStatus("unauthenticated");
  }, []);

  const value = useMemo<AdminAuthValue>(
    () => ({
      status,
      admin,
      token: tokenRef.current,
      accessMessage,
      login,
      retrySession,
      logout,
    }),
    [status, admin, accessMessage, login, retrySession, logout],
  );

  return <AdminAuthContext.Provider value={value}>{children}</AdminAuthContext.Provider>;
}

export function useAdminAuth(): AdminAuthValue {
  const ctx = useContext(AdminAuthContext);
  if (!ctx) {
    throw new Error("useAdminAuth deve ser usado dentro de <AdminAuthProvider>");
  }
  return ctx;
}
