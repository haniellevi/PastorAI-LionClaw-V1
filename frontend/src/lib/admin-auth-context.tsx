"use client";

/**
 * Sessão do console Super-Admin (plano de plataforma), isolada do painel da
 * igreja. Usa uma chave de token PRÓPRIA (`pastorai:admin-token`) para que
 * logar no console não interfira na sessão do painel operacional e vice-versa.
 *
 * Login: reutiliza POST /auth/login (o admin é um app_user normal) e, na
 * sequência, /admin/me — que só responde 200 para quem está na allowlist
 * platform_admins; 403 caso contrário (conta sem acesso de plataforma).
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

import { login as apiLogin } from "./api";
import { fetchAdminMe, type AdminMe } from "./admin-api";

const ADMIN_TOKEN_KEY = "pastorai:admin-token";

export type AdminAuthStatus = "loading" | "unauthenticated" | "authenticated";

interface AdminAuthValue {
  status: AdminAuthStatus;
  admin: AdminMe | null;
  token: string | null;
  /** Autentica via /auth/login + /admin/me. Repassa o erro em caso de falha. */
  login: (email: string, password: string) => Promise<void>;
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

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AdminAuthStatus>("loading");
  const [admin, setAdmin] = useState<AdminMe | null>(null);
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
    fetchAdminMe(token)
      .then((me) => {
        if (!active) return;
        setAdmin(me);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active) return;
        tokenRef.current = null;
        writeToken(null);
        setAdmin(null);
        setStatus("unauthenticated");
      });
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { token } = await apiLogin(email, password);
    let me: AdminMe;
    try {
      me = await fetchAdminMe(token);
    } catch (err) {
      // Token emitido, mas a conta não é admin de plataforma (ou expirou):
      // não persiste a sessão do console.
      tokenRef.current = null;
      writeToken(null);
      throw err;
    }
    tokenRef.current = token;
    writeToken(token);
    setAdmin(me);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(() => {
    tokenRef.current = null;
    writeToken(null);
    setAdmin(null);
    setStatus("unauthenticated");
  }, []);

  const value = useMemo<AdminAuthValue>(
    () => ({ status, admin, token: tokenRef.current, login, logout }),
    [status, admin, login, logout],
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
