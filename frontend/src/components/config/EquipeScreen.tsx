"use client";

/**
 * Tela #equipe — convidar pessoas e editar papéis acumulados (F3 / RF-40).
 * Consome api-team (GET /team), api-team-invite (POST /team/invite) e
 * api-team-roles (PUT /team/{id}/roles).
 *
 * Regras refletidas na UI (garantidas no backend):
 *  - e-mail duplicado no tenant é bloqueado (409) com erro inline no formulário;
 *  - remover/rebaixar o ÚLTIMO admin é bloqueado (409) — a igreja nunca fica
 *    sem administrador;
 *  - o menu/dashboard de cada pessoa é a UNIÃO dos papéis (definidos aqui) com
 *    as telas liberadas em #permissoes.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError, fetchTeam, type TeamMember } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import { normalizeRoles, ROLE_ORDER, type Role } from "@/lib/roles";
import { inviteMember, TeamConflictError, updateRoles } from "@/lib/team-api";

import { RolePick, RoleTags } from "./RolePick";

const INVITE_ROLES: Role[] = ROLE_ORDER.filter((r) => r !== "admin");

interface Toast {
  kind: "ok" | "err";
  text: string;
}

function statusTone(status: string | null): PillTone {
  return status === "convidado" ? "warn" : "ok";
}
function statusLabel(status: string | null): string {
  return status === "convidado" ? "Convidado" : "Ativo";
}

export function EquipeScreen() {
  const { token, expireSession } = useAuth();

  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // convite
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invNome, setInvNome] = useState("");
  const [invEmail, setInvEmail] = useState("");
  const [invRoles, setInvRoles] = useState<Set<Role>>(new Set());
  const [invError, setInvError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  // edição de papéis
  const [editing, setEditing] = useState<TeamMember | null>(null);
  const [editRoles, setEditRoles] = useState<Set<Role>>(new Set());
  const [editError, setEditError] = useState<string | null>(null);
  const [savingRoles, setSavingRoles] = useState(false);

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
        const page = await fetchTeam(token);
        setMembers(page.items);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar a equipe.");
      } finally {
        setLoading(false);
      }
    },
    [token, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const resetInvite = useCallback(() => {
    setInviteOpen(false);
    setInvNome("");
    setInvEmail("");
    setInvRoles(new Set());
    setInvError(null);
  }, []);

  const emailValid = (email: string) => /\S+@\S+\.\S+/.test(email.trim());
  const inviteReady = invNome.trim().length > 0 && emailValid(invEmail) && invRoles.size > 0;

  const submitInvite = useCallback(async () => {
    if (!token || !inviteReady) return;
    setInviting(true);
    setInvError(null);
    try {
      const dest = invEmail.trim().toLowerCase();
      const result = await inviteMember(token, {
        nome: invNome.trim(),
        email: dest,
        papeis: Array.from(invRoles),
      });
      flashToast(
        result.emailEnviado
          ? { kind: "ok", text: `Convite enviado para ${dest}.` }
          : {
              kind: "err",
              text: "Pessoa criada, mas o e-mail de convite não saiu (e-mail não configurado no servidor). Configure o envio e reenvie.",
            },
      );
      resetInvite();
      await load("retry");
    } catch (err) {
      if (handleSessionError(err)) return;
      if (err instanceof TeamConflictError) {
        setInvError(err.message);
      } else {
        setInvError(err instanceof ApiError ? err.message : "Não foi possível enviar o convite.");
      }
    } finally {
      setInviting(false);
    }
  }, [token, inviteReady, invNome, invEmail, invRoles, flashToast, resetInvite, load, handleSessionError]);

  const openEdit = useCallback((member: TeamMember) => {
    setEditing(member);
    setEditRoles(new Set(normalizeRoles(member.papeis)));
    setEditError(null);
  }, []);

  const closeEdit = useCallback(() => {
    setEditing(null);
    setEditRoles(new Set());
    setEditError(null);
  }, []);

  const submitRoles = useCallback(async () => {
    if (!token || !editing) return;
    if (editRoles.size === 0) {
      setEditError("Selecione ao menos um papel.");
      return;
    }
    setSavingRoles(true);
    setEditError(null);
    try {
      await updateRoles(token, editing.usuarioId, Array.from(editRoles));
      flashToast({ kind: "ok", text: `Papéis de ${editing.nome} atualizados.` });
      closeEdit();
      await load("retry");
    } catch (err) {
      if (handleSessionError(err)) return;
      if (err instanceof TeamConflictError) {
        setEditError(err.message);
      } else {
        setEditError(err instanceof ApiError ? err.message : "Não foi possível atualizar os papéis.");
      }
    } finally {
      setSavingRoles(false);
    }
  }, [token, editing, editRoles, flashToast, closeEdit, load, handleSessionError]);

  const toggle = useCallback(
    (setFn: React.Dispatch<React.SetStateAction<Set<Role>>>) =>
      (role: Role, on: boolean) => {
        setFn((prev) => {
          const next = new Set(prev);
          if (on) next.add(role);
          else next.delete(role);
          return next;
        });
      },
    [],
  );

  const columns: Array<Column<TeamMember>> = useMemo(
    () => [
      {
        header: "Pessoa",
        cell: (m) => <span className="nm">{m.nome}</span>,
      },
      {
        header: "E-mail",
        cell: (m) => <span className="sub mono">{m.email}</span>,
      },
      {
        header: "Papéis acumulados",
        cell: (m) => <RoleTags roles={normalizeRoles(m.papeis)} />,
      },
      {
        header: "Status",
        cell: (m) => <StatusPill tone={statusTone(m.status)}>{statusLabel(m.status)}</StatusPill>,
      },
      {
        header: "",
        width: "1px",
        cell: (m) => (
          <button type="button" className="btn btn-sm" onClick={() => openEdit(m)}>
            Editar papéis
          </button>
        ),
      },
    ],
    [openEdit],
  );

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="equipe">
      <div className="screen-head">
        <div className="titles">
          <h2>Pessoas</h2>
          <p>
            Pessoas da igreja que acessam o sistema. Cada uma acumula os papéis
            registrados aqui — o menu e o dashboard são montados pela união
            desses papéis (o que cada papel enxerga é definido em Permissões).
          </p>
        </div>
        <div className="actions">
          <button type="button" className="btn btn-primary" onClick={() => setInviteOpen((v) => !v)}>
            <Icon name="plus" />
            <span>Convidar pessoa</span>
          </button>
        </div>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={() => void load("retry")} disabled={loading}>
            Tentar novamente
          </button>
        </div>
      ) : null}

      {inviteOpen ? (
        <form
          className="card card-pad"
          style={{ marginBottom: "var(--s4)" }}
          onSubmit={(e) => {
            e.preventDefault();
            void submitInvite();
          }}
        >
          {invError ? (
            <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
              <Icon name="alert" />
              <span>{invError}</span>
            </div>
          ) : null}
          <div className="row" style={{ marginBottom: "var(--s3)" }}>
            <div className="field" style={{ margin: 0 }}>
              <label htmlFor="invName">Nome</label>
              <input
                id="invName"
                value={invNome}
                onChange={(e) => setInvNome(e.target.value)}
                placeholder="Nome completo"
                autoFocus
              />
            </div>
            <div className="field" style={{ margin: 0 }}>
              <label htmlFor="invEmail">E-mail do convidado</label>
              <input
                id="invEmail"
                type="email"
                value={invEmail}
                onChange={(e) => setInvEmail(e.target.value)}
                placeholder="lider@igreja.com.br"
              />
            </div>
          </div>
          <div className="field" style={{ marginBottom: "var(--s3)" }}>
            <label>
              Papéis ministeriais{" "}
              <span className="sub" style={{ color: "var(--muted)", fontWeight: 400 }}>
                — selecione um ou mais
              </span>
            </label>
            <RolePick options={INVITE_ROLES} selected={invRoles} onToggle={toggle(setInvRoles)} />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" className="btn btn-primary" disabled={!inviteReady || inviting} aria-busy={inviting || undefined}>
              {inviting ? "Enviando…" : "Enviar convite"}
            </button>
            <button type="button" className="btn" onClick={resetInvite} disabled={inviting}>
              Cancelar
            </button>
          </div>
        </form>
      ) : null}

      <div className="card">
        {showSkeleton ? (
          <div className="queue" style={{ padding: "var(--s4)" }}>
            {Array.from({ length: 4 }).map((_, i) => (
              <div className="qitem skeleton" key={i}>
                <div className="qbody">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <DataTable
            columns={columns}
            rows={members}
            rowKey={(m) => m.usuarioId}
            empty={{
              icon: "team",
              title: "Nenhuma pessoa na equipe ainda.",
              hint: "Convide o primeiro líder para começar.",
            }}
          />
        )}
      </div>

      {editing ? (
        <div className="modal-overlay" role="presentation" onClick={closeEdit}>
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={`Editar papéis de ${editing.nome}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-head">
              <strong>Editar papéis · {editing.nome}</strong>
              <button type="button" className="btn btn-sm btn-ghost" onClick={closeEdit}>
                Fechar
              </button>
            </div>
            <form
              className="modal-form"
              onSubmit={(e) => {
                e.preventDefault();
                void submitRoles();
              }}
            >
              {editError ? (
                <div className="error-banner" role="alert">
                  <Icon name="alert" />
                  <span>{editError}</span>
                </div>
              ) : null}
              <p className="sub" style={{ color: "var(--muted)" }}>
                Papéis acumulados (união). Remover o último administrador é bloqueado.
              </p>
              <RolePick options={ROLE_ORDER} selected={editRoles} onToggle={toggle(setEditRoles)} disabled={savingRoles} />
              <div className="modal-foot">
                <button type="button" className="btn btn-sm" onClick={closeEdit} disabled={savingRoles}>
                  Cancelar
                </button>
                <button type="submit" className="btn btn-primary btn-sm" disabled={savingRoles} aria-busy={savingRoles || undefined}>
                  {savingRoles ? "Salvando…" : "Salvar papéis"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
