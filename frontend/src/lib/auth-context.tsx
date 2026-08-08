"use client";

/**
 * Estado de sessão do painel. A autenticação é feita via api-login (que valida
 * credenciais no Clerk, no backend) e já devolve a identidade/papéis. /auth/me
 * fica reservado à restauração de uma sessão persistida.
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
  SessionAccessDeniedError,
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

export type AuthStatus =
  | "loading"
  | "unavailable"
  | "unauthenticated"
  | "authenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: SessionUser | null;
  token: string | null;
  /** Motivo terminal devolvido pelo backend ao recusar a sessão restaurada. */
  accessMessage: string | null;
  /** Autentica e hidrata a sessão com a resposta do api-login. */
  login: (email: string, password: string) => Promise<void>;
  /** Repete a validação de um token preservado após falha transitória. */
  retrySession: () => void;
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

  // During an explicit login the hash still points at the login flow. Peek at
  // the saved destination without consuming it; LoginScreen remains the owner
  // that clears RETURN_KEY after authentication succeeds.
  try {
    const saved = routeBase(window.localStorage.getItem(RETURN_KEY) ?? "");
    if (!isLoggedOutRoute(saved)) return saved;
  } catch {
    /* localStorage unavailable: use the surface default */
  }
  return fallback;
}

function preloadRoute(route: string): void {
  // Keep this deliberately small: only the most common/default deep-links are
  // warmed, and exactly one screen chunk is requested. Other routes still load
  // normally through ScreenView instead of making every authenticated visitor
  // download the whole application.
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

function preloadAuthenticatedSurface(): void {
  // Start the shell and the requested screen while /auth/me is in flight, so
  // auth -> shell -> screen does not become a serial JS waterfall. Logged-out
  // visitors do not pay for any of these chunks.
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
  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
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
        setAccessMessage(null);
        setStatus("authenticated");
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (
          error instanceof SessionExpiredError ||
          error instanceof SessionAccessDeniedError
        ) {
          tokenRef.current = null;
          writeToken(null);
          setAccessMessage(
            error instanceof SessionAccessDeniedError ? error.message : null,
          );
          setStatus("unauthenticated");
        } else {
          setAccessMessage(null);
          setStatus("unavailable");
        }
        setUser(null);
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
    const { token, ...me } = await apiLogin(email, password);
    preloadAuthenticatedSurface();
    tokenRef.current = token;
    writeToken(token);
    setUser(toSessionUser(me));
    setAccessMessage(null);
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
    setAccessMessage(null);
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
    setAccessMessage(null);
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
      accessMessage,
      login,
      retrySession,
      logout,
      updateNome,
      updateChatNome,
      expireSession,
      consumeReturnTo,
    }),
    [
      status,
      user,
      accessMessage,
      login,
      retrySession,
      logout,
      updateNome,
      updateChatNome,
      expireSession,
      consumeReturnTo,
    ],
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
