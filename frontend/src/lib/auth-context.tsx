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
  /** Nome de exibição no chat (assinatura). null = usa `nome`. */
  chatNome: string | null;
  roles: Role[];
  /** É o dono (admin principal) da igreja? Só o dono gerencia a Assinatura (#4). */
  isOwner: boolean;
  /** Nome da igreja (Missão 4 branding); null quando o back não envia. */
  igrejaNome: string | null;
  /** URL pública da logo da igreja (Missão 4); null = sem logo customizada. */
  igrejaLogoUrl: string | null;
}

export type AuthStatus = "loading" | "unauthenticated" | "authenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: SessionUser | null;
  token: string | null;
  /** Autentica via api-login + /auth/me. Lança LoginError em falha. */
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** Atualiza localmente o nome de exibição após editar o perfil. */
  updateNome: (nome: string) => void;
  /** Atualiza localmente a assinatura do chat após editar o perfil. */
  updateChatNome: (chatNome: string | null) => void;
  /** Sinaliza expiração de sessão preservando a rota atual. */
  expireSession: () => void;
  /** Rota a restaurar após re-login (sessão expirada). */
  consumeReturnTo: () => string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// O token de sessão também vai para um cookie no domínio-pai (.igreja12.com.br)
// para ser COMPARTILHADO entre as superfícies app./admin. (sessão seamless ao
// trocar de host pelo botão "Admin"). Não é HttpOnly porque o cliente lê o
// token para o header Authorization; a API usa Bearer e ignora cookies.
// localStorage é mantido como fallback e para compatibilidade com sessões já
// abertas antes desta mudança.
const COOKIE_NAME = "pastorai_token";

function cookieAttrs(): string {
  let attrs = "; path=/; SameSite=Lax";
  try {
    const { hostname, protocol } = window.location;
    if (hostname.endsWith("igreja12.com.br")) attrs += "; domain=.igreja12.com.br";
    if (protocol === "https:") attrs += "; Secure";
  } catch {
    /* sem window: usa atributos padrão */
  }
  return attrs;
}

function readToken(): string | null {
  try {
    const match = document.cookie.match(/(?:^|;\s*)pastorai_token=([^;]+)/);
    if (match?.[1]) return decodeURIComponent(match[1]);
  } catch {
    /* cookie indisponível: tenta localStorage */
  }
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null) {
  try {
    if (token) {
      document.cookie = `${COOKIE_NAME}=${encodeURIComponent(token)}; max-age=28800${cookieAttrs()}`;
    } else {
      document.cookie = `${COOKIE_NAME}=; max-age=0${cookieAttrs()}`;
    }
  } catch {
    /* cookie indisponível */
  }
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* armazenamento indisponível: sessão fica só em memória */
  }
}

function routeBase(route: string): string {
  return route.replace(/^#/, "").split("/")[0] ?? "";
}

function isLoggedOutRoute(route: string): boolean {
  return (
    !route ||
    route === "login" ||
    route === "esqueci-senha" ||
    route === "ativar" ||
    route === "redefinir-senha"
  );
}

function requestedAuthenticatedRoute(fallback: string): string {
  const current = routeBase(window.location.hash);
  if (!isLoggedOutRoute(current)) return current;
  try {
    const saved = routeBase(window.localStorage.getItem(RETURN_KEY) ?? "");
    if (!isLoggedOutRoute(saved)) return saved;
  } catch {
    /* localStorage indisponível: usa o destino padrão */
  }
  return fallback;
}

function preloadRoute(route: string): void {
  switch (route) {
    case "dashboard":
      void import("@/components/dashboard/DashboardScreen");
      break;
    case "inbox":
      void import("@/components/inbox/InboxScreen");
      break;
    case "calendario":
      void import("@/components/calendario/CalendarioScreen");
      break;
    case "ganhar":
      void import("@/components/contacts/GanharScreen");
      break;
    case "minha-celula":
      void import("@/components/minha-celula/MinhaCelulaEntry");
      break;
    case "setup":
      void import("@/components/config/SetupChecklistScreen");
      break;
    case "contatos":
      void import("@/components/contacts/ContatosScreen");
      break;
    case "whatsapp":
      void import("@/components/whatsapp/WhatsappScreen");
      break;
  }
}

/** Evita a cascata sessão → shell → tela sem baixar conteúdo de outras rotas. */
function preloadAuthenticatedSurface(): void {
  if (window.location.pathname.startsWith("/gestao")) {
    void import("@/components/shell/AdminAppShell");
    preloadRoute(requestedAuthenticatedRoute("setup"));
    return;
  }
  void import("@/components/shell/AppShell");
  preloadRoute(requestedAuthenticatedRoute("dashboard"));
}

function toSessionUser(me: MeResult): SessionUser {
  return {
    appUserId: me.appUserId,
    churchId: me.churchId,
    email: me.email,
    nome: me.nome,
    chatNome: me.chatNome,
    roles: normalizeRoles(me.roles),
    isOwner: me.isOwner === true,
    igrejaNome: me.igrejaNome ?? null,
    igrejaLogoUrl: me.igrejaLogoUrl ?? null,
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
    preloadAuthenticatedSurface();
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
    preloadAuthenticatedSurface();
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

  const updateNome = useCallback((nome: string) => {
    setUser((u) => (u ? { ...u, nome } : u));
  }, []);

  const updateChatNome = useCallback((chatNome: string | null) => {
    setUser((u) => (u ? { ...u, chatNome } : u));
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
      updateNome,
      updateChatNome,
      expireSession,
      consumeReturnTo,
    }),
    [status, user, login, logout, updateNome, updateChatNome, expireSession, consumeReturnTo],
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
