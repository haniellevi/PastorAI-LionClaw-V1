"use client";

/**
 * Estado compartilhado da matriz de permissões (role_permissions — delta-010).
 *
 * role_permissions é a FONTE DE VERDADE do menu/dashboard. A tela #permissoes
 * (admin) edita a matriz e, ao salvar, atualiza este contexto — fazendo o menu
 * (Sidebar) e o gating de rota (AppShell) reagirem em TEMPO REAL, sem reload
 * (delta-010). Enquanto a matriz não é carregada do backend, usamos o default
 * de seed (DEFAULT_PERMISSIONS), mantendo o app funcional para não-admins.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { DEFAULT_PERMISSIONS, type PermissionMatrix } from "./permissions";

interface PermissionsContextValue {
  /** Matriz vigente (default de seed até o backend responder). */
  matrix: PermissionMatrix;
  /** Substitui a matriz vigente (após GET/PUT em /roles/permissions). */
  setMatrix: (matrix: PermissionMatrix) => void;
}

const PermissionsContext = createContext<PermissionsContextValue | null>(null);

export function PermissionsProvider({ children }: { children: ReactNode }) {
  const [matrix, setMatrixState] = useState<PermissionMatrix>(() => ({
    ...DEFAULT_PERMISSIONS,
  }));

  const setMatrix = useCallback((next: PermissionMatrix) => {
    setMatrixState({ ...next });
  }, []);

  const value = useMemo<PermissionsContextValue>(
    () => ({ matrix, setMatrix }),
    [matrix, setMatrix],
  );

  return (
    <PermissionsContext.Provider value={value}>{children}</PermissionsContext.Provider>
  );
}

export function usePermissions(): PermissionsContextValue {
  const ctx = useContext(PermissionsContext);
  if (!ctx) {
    throw new Error("usePermissions deve ser usado dentro de <PermissionsProvider>");
  }
  return ctx;
}
