"use client";

/**
 * Estado de sessão do painel. A autenticação é feita via api-login (que valida
 * credenciais no Clerk, no backend) e a identidade/papéis vêm de /auth/me.
 *
 * Fluxos (SPEC 5.1 / seção 6):
 *  - sucesso -> #dashboard;
 *  - credencial inválida -> erro genérico;
 *  - igreja suspensa / sem igreja -> bloqueio;
 *  - sessão expirada -> #login preservando a rota de retorno.
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
  fetchMe,
  login as apiLogin,
  LoginError,
  SessionExpiredError,
  type MeResult,
} from "./api";
import { normalizeRoles, type Role } from "./roles";

const TOKEN_KEY = "pastorai:token";
const RETURN_KEY = "pastorai:returnTo";

export interface SessionUser {
  appUserId: string;
  churchId: string;
  email: string;
  nome: string;
  roles: Role[];
}

export type AuthStatus = "loading" | "unauthenticated" | "authenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: SessionUser | null;
  token: string | null;
  /** Autentica via api-login + /auth/me. Lança LoginError em falha. */
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** Sinaliza expiração de sessão preservando a rota atual. */
  expireSession: () => void;
  /** Rota a restaurar após re-login (sessão expirada). */
  consumeReturnTo: () => string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* armazenamento indisponível: sessão fica só em memória */
  }
}

function toSessionUser(me: MeResult): SessionUser {
  return {
    appUserId: me.appUserId,
    churchId: me.churchId,
    email: me.email,
    nome: me.nome,
    roles: normalizeRoles(me.roles),
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<SessionUser | null>(null);
  const tokenRef = useRef<string | null>(null);

  // Bootstrap: restaura sessão de um token persistido.
  useEffect(() => {
    let active = true;
    const token = readToken();
    if (!token) {
      setStatus("unauthenticated");
      return;
    }
    tokenRef.current = token;
    fetchMe(token)
      .then((me) => {
        if (!active) return;
        setUser(toSessionUser(me));
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active) return;
        tokenRef.current = null;
        writeToken(null);
        setUser(null);
        setStatus("unauthenticated");
      });
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { token } = await apiLogin(email, password);
    let me: MeResult;
    try {
      me = await fetchMe(token);
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        // Token recém-emitido recusado em /me: trata como conta sem vínculo.
        throw new LoginError(
          "no_church",
          "Sua conta não está vinculada a nenhuma igreja. Contate o administrador.",
        );
      }
      throw err;
    }
    tokenRef.current = token;
    writeToken(token);
    setUser(toSessionUser(me));
    setStatus("authenticated");
  }, []);

  const logout = useCallback(() => {
    tokenRef.current = null;
    writeToken(null);
    try {
      window.localStorage.removeItem(RETURN_KEY);
    } catch {
      /* ignore */
    }
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const expireSession = useCallback(() => {
    try {
      const current = window.location.hash.replace(/^#/, "");
      if (current && current !== "login") {
        window.localStorage.setItem(RETURN_KEY, current);
      }
    } catch {
      /* ignore */
    }
    tokenRef.current = null;
    writeToken(null);
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const consumeReturnTo = useCallback((): string | null => {
    try {
      const value = window.localStorage.getItem(RETURN_KEY);
      if (value) window.localStorage.removeItem(RETURN_KEY);
      return value;
    } catch {
      return null;
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      token: tokenRef.current,
      login,
      logout,
      expireSession,
      consumeReturnTo,
    }),
    [status, user, login, logout, expireSession, consumeReturnTo],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth deve ser usado dentro de <AuthProvider>");
  }
  return ctx;
}
