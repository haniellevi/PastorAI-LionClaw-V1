"use client";

/**
 * Tela #permissoes — matriz papel × tela (role_permissions / delta-010).
 * Consome api-role-perms (GET/PUT /roles/permissions).
 *
 * role_permissions é a FONTE DE VERDADE do menu/dashboard. Ao salvar, a matriz
 * é publicada no PermissionsContext e o menu (Sidebar) + o gating de rota
 * (AppShell) reagem em TEMPO REAL, sem reload.
 *
 * Regras refletidas na UI (garantidas no backend):
 *  - `admin` tem acesso total e não participa da matriz (não é linha editável);
 *  - `dashboard` é garantido a TODO papel — a coluna é travada (não editável).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import { MENU_SCREENS, type PermissionMatrix } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { fetchPermissions, savePermissions } from "@/lib/roles-api";
import { ROLE_DEFS, ROLE_ORDER, type Role } from "@/lib/roles";

/** Papéis editáveis (admin tem acesso total, fora da matriz). */
const EDITABLE_ROLES: Array<Exclude<Role, "admin">> = ROLE_ORDER.filter(
  (r): r is Exclude<Role, "admin"> => r !== "admin",
);

/** Rótulos compactos das colunas (portados do artifact travado). */
const SCREEN_LABEL: Record<string, string> = {
  dashboard: "Dashboard",
  inbox: "Conversas",
  ganhar: "Ganhar",
  consolidar: "Consolidar",
  "consol-individual": "Consol. Individual",
  "universidade-vida": "UV",
  capacitacao: "Capacitação",
  g12: "G12",
  "central-celula": "Central Célula",
  enviar: "Enviar",
  calendario: "Agenda",
  comunicados: "Comunicação",
  contatos: "Pessoas",
};

interface Toast {
  kind: "ok" | "err";
  text: string;
}

/** Clona a matriz em estrutura mutável (sets) para edição local. */
function toDraft(matrix: PermissionMatrix): Record<string, Set<string>> {
  const draft: Record<string, Set<string>> = {};
  for (const role of EDITABLE_ROLES) {
    draft[role] = new Set(matrix[role] ?? []);
  }
  return draft;
}

/** Converte o draft de volta para PermissionMatrix (arrays). */
function fromDraft(draft: Record<string, Set<string>>): PermissionMatrix {
  const matrix: PermissionMatrix = {};
  for (const role of EDITABLE_ROLES) {
    matrix[role] = Array.from(draft[role] ?? []);
  }
  return matrix;
}

/** Compara duas matrizes (igualdade de conjuntos por papel). */
function sameMatrix(a: PermissionMatrix, b: PermissionMatrix): boolean {
  for (const role of EDITABLE_ROLES) {
    const sa = new Set(a[role] ?? []);
    const sb = new Set(b[role] ?? []);
    if (sa.size !== sb.size) return false;
    for (const s of sa) if (!sb.has(s)) return false;
  }
  return true;
}

export function PermissoesScreen() {
  const { token, expireSession } = useAuth();
  const { setMatrix } = usePermissions();

  const [draft, setDraft] = useState<Record<string, Set<string>>>(() => toDraft({}));
  const [saved, setSaved] = useState<PermissionMatrix>({});
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [toast, setToast] = useState<Toast | null>(null);
  const toastTimer = useRef<number | null>(null);
  const flashToast = useCallback((t: Toast) => {
    setToast(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3600);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  const handleSessionError = useCallback(
    (err: unknown): boolean => {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return true;
      }
      return false;
    },
    [expireSession],
  );

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (!token) return;
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const matrix = await fetchPermissions(token);
        setSaved(matrix);
        setDraft(toDraft(matrix));
        setMatrix(matrix); // publica a fonte de verdade no menu/dashboard
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar as permissões.",
        );
      } finally {
        setLoading(false);
      }
    },
    [token, handleSessionError, setMatrix],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const toggle = useCallback((role: string, screen: string, on: boolean) => {
    setDraft((prev) => {
      const next: Record<string, Set<string>> = {};
      for (const r of EDITABLE_ROLES) next[r] = new Set(prev[r] ?? []);
      if (on) next[role]?.add(screen);
      else next[role]?.delete(screen);
      return next;
    });
  }, []);

  const draftMatrix = useMemo(() => fromDraft(draft), [draft]);
  const dirty = useMemo(() => !sameMatrix(draftMatrix, saved), [draftMatrix, saved]);

  const save = useCallback(async () => {
    if (!token || !dirty || saving) return;
    setSaving(true);
    setError(null);
    try {
      const persisted = await savePermissions(token, draftMatrix);
      setSaved(persisted);
      setDraft(toDraft(persisted));
      setMatrix(persisted); // menu/dashboard refletem em tempo real após salvar
      flashToast({ kind: "ok", text: "Permissões salvas — menu atualizado." });
    } catch (err) {
      if (handleSessionError(err)) return;
      flashToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível salvar as permissões.",
      });
    } finally {
      setSaving(false);
    }
  }, [token, dirty, saving, draftMatrix, setMatrix, flashToast, handleSessionError]);

  const discard = useCallback(() => {
    setDraft(toDraft(saved));
  }, [saved]);

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="permissoes">
      <div className="screen-head">
        <div className="actions">
          <button type="button" className="btn" onClick={discard} disabled={!dirty || saving}>
            Descartar
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void save()}
            disabled={!dirty || saving}
            aria-busy={saving || undefined}
          >
            {saving ? "Salvando…" : "Salvar permissões"}
          </button>
        </div>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load("retry")}
            disabled={loading}
          >
            Tentar novamente
          </button>
        </div>
      ) : null}

      <div className="card card-pad">
        <p className="perm-cap">
          Marque as telas liberadas para cada papel. As mudanças valem no menu
          assim que você salvar. <strong>Administrador</strong> tem acesso total
          e não é editável.
        </p>

        {showSkeleton ? (
          <div className="queue">
            {Array.from({ length: 6 }).map((_, i) => (
              <div className="qitem skeleton" key={i}>
                <div className="qbody">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="perm-wrap">
            <table className="perm-table">
              <thead>
                <tr>
                  <th>Papel</th>
                  {MENU_SCREENS.map((screen) => (
                    <th key={screen}>{SCREEN_LABEL[screen] ?? screen}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {EDITABLE_ROLES.map((role) => (
                  <tr key={role}>
                    <th scope="row">{ROLE_DEFS[role].label}</th>
                    {MENU_SCREENS.map((screen) => {
                      if (screen === "dashboard") {
                        return (
                          <td
                            key={screen}
                            className="locked"
                            title="Dashboard é garantido a todos"
                          >
                            ●
                          </td>
                        );
                      }
                      const on = draft[role]?.has(screen) ?? false;
                      const label = SCREEN_LABEL[screen] ?? screen;
                      return (
                        <td key={screen}>
                          <input
                            type="checkbox"
                            checked={on}
                            disabled={saving}
                            aria-label={`${ROLE_DEFS[role].label} vê ${label}`}
                            onChange={(e) => toggle(role, screen, e.target.checked)}
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
