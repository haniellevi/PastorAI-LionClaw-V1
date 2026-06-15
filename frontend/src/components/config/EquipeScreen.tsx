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
import { fetchContacts, type Contact } from "@/lib/contacts-api";
import { ApiError, fetchTeam, type TeamMember } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import { normalizeRoles, ROLE_ORDER, type Role } from "@/lib/roles";
import {
  deleteMember,
  inviteMember,
  resendInvite,
  TeamConflictError,
  updateRoles,
} from "@/lib/team-api";

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
  const { token, user, expireSession } = useAuth();

  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // convite
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invMode, setInvMode] = useState<"existente" | "nova">("existente");
  const [invPessoaId, setInvPessoaId] = useState<string | null>(null);
  const [invPessoaQuery, setInvPessoaQuery] = useState("");
  const [invNome, setInvNome] = useState("");
  const [invEmail, setInvEmail] = useState("");
  const [invRoles, setInvRoles] = useState<Set<Role>>(new Set());
  const [invError, setInvError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  // base de pessoas cadastradas (para escolher quem recebe acesso ao painel)
  const [pessoas, setPessoas] = useState<Contact[]>([]);
  const [pessoasTotal, setPessoasTotal] = useState(0);
  const [pessoasLoaded, setPessoasLoaded] = useState(false);
  // true quando a pessoa escolhida ainda não tem e-mail (precisa pedir um)
  const [invNeedsEmail, setInvNeedsEmail] = useState(false);

  // edição de papéis
  const [editing, setEditing] = useState<TeamMember | null>(null);
  const [editRoles, setEditRoles] = useState<Set<Role>>(new Set());
  const [editError, setEditError] = useState<string | null>(null);
  const [savingRoles, setSavingRoles] = useState(false);

  // ação por linha (reenviar convite / excluir acesso)
  const [busyId, setBusyId] = useState<string | null>(null);

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

  // Carrega a base de pessoas ao abrir o convite (uma vez), para o seletor.
  useEffect(() => {
    if (!inviteOpen || !token || pessoasLoaded) return;
    let active = true;
    void (async () => {
      try {
        const page = await fetchContacts(token);
        if (active) {
          setPessoas(page.items);
          setPessoasTotal(page.total);
          setPessoasLoaded(true);
        }
      } catch (err) {
        if (handleSessionError(err)) return;
        // silencioso: o modo "cadastrar nova" segue como fallback.
      }
    })();
    return () => {
      active = false;
    };
  }, [inviteOpen, token, pessoasLoaded, handleSessionError]);

  const pessoasFiltradas = useMemo(() => {
    const q = invPessoaQuery.trim().toLowerCase();
    const base = q
      ? pessoas.filter((p) =>
          `${p.nome} ${p.telefone} ${p.email ?? ""}`.toLowerCase().includes(q),
        )
      : pessoas;
    return base.slice(0, 50);
  }, [pessoas, invPessoaQuery]);

  // Pessoas que já têm login no painel — não podem receber acesso de novo.
  const pessoasComAcesso = useMemo(
    () => new Set(members.map((m) => m.pessoaId).filter((id): id is string => !!id)),
    [members],
  );

  const selectPessoa = useCallback((p: Contact) => {
    setInvPessoaId(p.id);
    setInvNome(p.nome);
    setInvEmail(p.email ?? "");
    setInvNeedsEmail(!(p.email ?? "").trim());
    setInvError(null);
  }, []);

  const resetInvite = useCallback(() => {
    setInviteOpen(false);
    setInvMode("existente");
    setInvPessoaId(null);
    setInvPessoaQuery("");
    setInvNome("");
    setInvEmail("");
    setInvNeedsEmail(false);
    setInvRoles(new Set());
    setInvError(null);
    // invalida o cache de pessoas: reabrir o convite recarrega (inclui quem
    // foi criado no meio tempo).
    setPessoas([]);
    setPessoasTotal(0);
    setPessoasLoaded(false);
  }, []);

  const emailValid = (email: string) => /\S+@\S+\.\S+/.test(email.trim());
  const inviteReady =
    invRoles.size > 0 &&
    emailValid(invEmail) &&
    (invMode === "existente" ? invPessoaId !== null : invNome.trim().length > 0);

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
        pessoaId: invMode === "existente" ? (invPessoaId ?? undefined) : undefined,
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
  }, [token, inviteReady, invMode, invPessoaId, invNome, invEmail, invRoles, flashToast, resetInvite, load, handleSessionError]);

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

  const isSelf = useCallback(
    (m: TeamMember) => user != null && m.usuarioId === user.appUserId,
    [user],
  );

  const handleResend = useCallback(
    async (m: TeamMember) => {
      if (!token) return;
      setBusyId(m.usuarioId);
      try {
        const r = await resendInvite(token, m.usuarioId);
        flashToast(
          r.emailEnviado
            ? { kind: "ok", text: `Convite reenviado para ${m.email}.` }
            : {
                kind: "err",
                text: "Não foi possível enviar o e-mail (verifique a configuração de e-mail).",
              },
        );
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível reenviar o convite.",
        });
      } finally {
        setBusyId(null);
      }
    },
    [token, flashToast, handleSessionError],
  );

  const handleDelete = useCallback(
    async (m: TeamMember) => {
      if (!token) return;
      if (!window.confirm(`Remover o acesso de ${m.nome}? Esta ação não pode ser desfeita.`)) {
        return;
      }
      setBusyId(m.usuarioId);
      try {
        await deleteMember(token, m.usuarioId);
        flashToast({ kind: "ok", text: `Acesso de ${m.nome} removido.` });
        await load("retry");
      } catch (err) {
        if (handleSessionError(err)) return;
        if (err instanceof TeamConflictError) {
          flashToast({ kind: "err", text: err.message });
        } else {
          flashToast({
            kind: "err",
            text: err instanceof ApiError ? err.message : "Não foi possível remover o acesso.",
          });
        }
      } finally {
        setBusyId(null);
      }
    },
    [token, flashToast, load, handleSessionError],
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
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-sm" onClick={() => openEdit(m)}>
              Editar papéis
            </button>
            {m.status === "convidado" ? (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => void handleResend(m)}
                disabled={busyId === m.usuarioId}
                aria-busy={busyId === m.usuarioId || undefined}
              >
                {busyId === m.usuarioId ? "Enviando…" : "Reenviar convite"}
              </button>
            ) : null}
            {isSelf(m) ? (
              <StatusPill tone="muted">Você</StatusPill>
            ) : (
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={() => void handleDelete(m)}
                disabled={busyId === m.usuarioId}
                aria-busy={busyId === m.usuarioId || undefined}
              >
                Excluir
              </button>
            )}
          </div>
        ),
      },
    ],
    [openEdit, isSelf, handleResend, handleDelete, busyId],
  );

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="equipe">
      <div className="screen-head">
        <div className="titles">
          <h2>Equipe</h2>
          <p>
            Quem tem acesso ao painel. Cada pessoa acumula os papéis registrados
            aqui — o menu e o dashboard são a união desses papéis (o que cada
            papel enxerga é definido em Permissões).
          </p>
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => (inviteOpen ? resetInvite() : setInviteOpen(true))}
          >
            <Icon name="plus" />
            <span>Dar acesso ao painel</span>
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
          <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s3)" }}>
            Dê acesso ao painel a uma pessoa já cadastrada. Não está na lista?
            Cadastre uma nova.
          </p>

          {invMode === "existente" ? (
            <>
              <div className="field" style={{ marginBottom: "var(--s2)" }}>
                <label htmlFor="invPessoaQuery">Buscar pessoa</label>
                <input
                  id="invPessoaQuery"
                  value={invPessoaQuery}
                  onChange={(e) => setInvPessoaQuery(e.target.value)}
                  placeholder="Nome, telefone ou e-mail…"
                  autoFocus
                />
                <div
                  style={{
                    maxHeight: 220,
                    overflowY: "auto",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--r-md)",
                    marginTop: 6,
                  }}
                >
                  {pessoasFiltradas.length === 0 ? (
                    <p className="sub" style={{ color: "var(--muted)", padding: "var(--s3)" }}>
                      {pessoasLoaded ? "Nenhuma pessoa encontrada." : "Carregando pessoas…"}
                    </p>
                  ) : (
                    pessoasFiltradas.map((p) => {
                      const jaTemAcesso = pessoasComAcesso.has(p.id);
                      const sel = invPessoaId === p.id;
                      return (
                        <button
                          type="button"
                          key={p.id}
                          onClick={() => {
                            if (!jaTemAcesso) selectPessoa(p);
                          }}
                          disabled={jaTemAcesso}
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: 8,
                            width: "100%",
                            textAlign: "left",
                            padding: "8px 12px",
                            background: sel ? "var(--accent-soft)" : "transparent",
                            border: "none",
                            borderBottom: "1px solid var(--border)",
                            cursor: jaTemAcesso ? "not-allowed" : "pointer",
                            opacity: jaTemAcesso ? 0.55 : 1,
                            font: "inherit",
                            color: "inherit",
                          }}
                        >
                          <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                            <span className="nm">{p.nome}</span>
                            <span className="sub mono" style={{ color: "var(--muted)" }}>
                              {p.telefone}
                              {p.email ? ` · ${p.email}` : " · sem e-mail"}
                            </span>
                          </span>
                          {jaTemAcesso ? <StatusPill tone="muted">Já tem acesso</StatusPill> : null}
                        </button>
                      );
                    })
                  )}
                </div>
                {pessoas.length < pessoasTotal ? (
                  <p className="sub" style={{ color: "var(--muted)", marginTop: 6 }}>
                    Mostrando {pessoas.length} de {pessoasTotal}. Refine a busca para
                    encontrar quem não aparece.
                  </p>
                ) : null}
                {invPessoaId && invNeedsEmail ? (
                  <div className="field" style={{ marginTop: "var(--s3)" }}>
                    <label htmlFor="invEmailExist">
                      E-mail para login{" "}
                      <span className="sub" style={{ color: "var(--muted)", fontWeight: 400 }}>
                        — esta pessoa ainda não tem e-mail cadastrado
                      </span>
                    </label>
                    <input
                      id="invEmailExist"
                      type="email"
                      value={invEmail}
                      onChange={(e) => setInvEmail(e.target.value)}
                      placeholder="lider@igreja.com.br"
                    />
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                className="btn btn-sm"
                style={{ marginBottom: "var(--s3)" }}
                onClick={() => {
                  setInvMode("nova");
                  setInvPessoaId(null);
                  setInvPessoaQuery("");
                  setInvNome("");
                  setInvEmail("");
                  setInvNeedsEmail(false);
                  setInvError(null);
                }}
              >
                Não está na lista? Cadastrar nova pessoa
              </button>
            </>
          ) : (
            <>
              <div className="row" style={{ marginBottom: "var(--s2)" }}>
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
              <button
                type="button"
                className="btn btn-sm"
                style={{ marginBottom: "var(--s3)" }}
                onClick={() => {
                  setInvMode("existente");
                  setInvNome("");
                  setInvEmail("");
                  setInvNeedsEmail(false);
                  setInvError(null);
                }}
              >
                ← Voltar à busca de pessoa cadastrada
              </button>
            </>
          )}
          <div className="field" style={{ marginBottom: "var(--s3)" }}>
            <label>
              Papéis{" "}
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
