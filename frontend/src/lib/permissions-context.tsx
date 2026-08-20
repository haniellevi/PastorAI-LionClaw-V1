"use client";

/**
 * Estado compartilhado da matriz de permissões (role_permissions — delta-010).
 *
 * role_permissions é a FONTE DE VERDADE do menu/dashboard. A tela #permissoes
 * (admin) edita a matriz e, ao salvar, atualiza este contexto — fazendo o menu
 * (Sidebar) e o gating de rota (AppShell) reagirem em TEMPO REAL, sem reload
 * (delta-010). Após autenticar, o shell espera a matriz efetiva do backend. Se
 * a leitura falhar, mantém apenas um snapshot remoto já verificado para o mesmo
 * token ou fecha a navegação no mínimo seguro (dashboard).
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

import { SessionExpiredError } from "./api";
import { useOptionalAuth } from "./auth-context";
import { DEFAULT_PERMISSIONS, type PermissionMatrix } from "./permissions";
import { fetchPermissions } from "./roles-api";

export type PermissionsSource = "default" | "remote" | "cached" | "fail-closed";

interface PermissionsContextValue {
  /** Matriz efetiva da sessão. */
  matrix: PermissionMatrix;
  /** true enquanto a sessão autenticada ainda não resolveu sua matriz. */
  loading: boolean;
  /** Origem da matriz efetiva, útil para diagnóstico sem bloquear a UI. */
  source: PermissionsSource;
  /** Substitui a matriz vigente (após GET/PUT em /roles/permissions). */
  setMatrix: (matrix: PermissionMatrix) => void;
}

const PermissionsContext = createContext<PermissionsContextValue | null>(null);

const PERMISSIONS_RETRY_BASE_MS = 5_000;
const PERMISSIONS_RETRY_MAX_MS = 60_000;

function retryDelayMs(attempt: number): number {
  return Math.min(
    PERMISSIONS_RETRY_BASE_MS * 2 ** attempt,
    PERMISSIONS_RETRY_MAX_MS,
  );
}

function defaultMatrix(): PermissionMatrix {
  return { ...DEFAULT_PERMISSIONS };
}

/**
 * Fallback autenticado mínimo. `allowedScreens` garante dashboard por papel,
 * mas mantemos cada entrada explicitamente para diagnóstico e para não perder
 * papéis como `operador` quando a matriz remota estiver indisponível.
 */
function failClosedMatrix(): PermissionMatrix {
  const matrix: PermissionMatrix = {};
  for (const role of Object.keys(DEFAULT_PERMISSIONS) as Array<
    keyof typeof DEFAULT_PERMISSIONS
  >) {
    matrix[role] = ["dashboard"];
  }
  return matrix;
}

export function PermissionsProvider({ children }: { children: ReactNode }) {
  const auth = useOptionalAuth();
  const authStatus = auth?.status ?? "unauthenticated";
  const token = auth?.token ?? null;
  const expireSession = auth?.expireSession;
  const [snapshot, setSnapshot] = useState<{
    token: string | null;
    matrix: PermissionMatrix;
    source: PermissionsSource;
  }>(() => ({ token: null, matrix: defaultMatrix(), source: "default" }));
  const requestId = useRef(0);

  const loading =
    authStatus === "authenticated" && Boolean(token) && snapshot.token !== token;

  useEffect(() => {
    const currentRequest = ++requestId.current;

    if (authStatus !== "authenticated" || !token) {
      setSnapshot({ token: null, matrix: defaultMatrix(), source: "default" });
      return;
    }

    let active = true;
    let retryAttempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const loadPermissions = async () => {
      try {
        const matrix = await fetchPermissions(token);
        if (!active || requestId.current !== currentRequest) return;
        setSnapshot({ token, matrix: { ...matrix }, source: "remote" });
      } catch (error: unknown) {
        if (!active || requestId.current !== currentRequest) return;
        if (error instanceof SessionExpiredError) {
          expireSession?.();
          return;
        }
        setSnapshot((current) => {
          // Uma falha de atualização não deve reabrir permissões revogadas. Só
          // um snapshot remoto já verificado para ESTE token pode sobreviver.
          if (
            current.token === token &&
            (current.source === "remote" || current.source === "cached")
          ) {
            return { ...current, source: "cached" };
          }

          // Nunca reutilize matriz de outro token. Na primeira leitura falha,
          // libera apenas o dashboard até a autoridade remota voltar.
          return { token, matrix: failClosedMatrix(), source: "fail-closed" };
        });

        // Um único timer encadeia as tentativas. O atraso cresce até o teto,
        // mantendo o dashboard disponível sem criar rajadas concorrentes.
        if (retryTimer === null) {
          const delay = retryDelayMs(retryAttempt);
          retryAttempt += 1;
          retryTimer = setTimeout(() => {
            retryTimer = null;
            if (!active || requestId.current !== currentRequest) return;
            void loadPermissions();
          }, delay);
        }
      }
    };

    void loadPermissions();

    return () => {
      active = false;
      if (retryTimer !== null) clearTimeout(retryTimer);
    };
  }, [authStatus, token, expireSession]);

  const setMatrix = useCallback((next: PermissionMatrix) => {
    setSnapshot((current) => ({
      token: token ?? current.token,
      matrix: { ...next },
      source: "remote",
    }));
  }, [token]);

  const value = useMemo<PermissionsContextValue>(
    () => ({ matrix: snapshot.matrix, loading, source: snapshot.source, setMatrix }),
    [snapshot.matrix, snapshot.source, loading, setMatrix],
  );

  return (
    <PermissionsContext.Provider value={value}>
      {loading ? (
        <div className="full-loader" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <span className="sr-only">Carregando permissões…</span>
        </div>
      ) : (
        children
      )}
    </PermissionsContext.Provider>
  );
}

export function usePermissions(): PermissionsContextValue {
  const ctx = useContext(PermissionsContext);
  if (!ctx) {
    throw new Error("usePermissions deve ser usado dentro de <PermissionsProvider>");
  }
  return ctx;
}
