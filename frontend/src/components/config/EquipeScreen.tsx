"use client";

/**
 * Tela #equipe — dar acesso ao painel (convite) e editar papéis (F3 / RF-40 /
 * delta-049).
 *
 * Convite (Parte A): dá acesso a uma pessoa JÁ cadastrada e a vincula a uma
 * célula. O convidado entra como MEMBRO — convites não escolhem papéis. Papéis
 * são editados depois, aqui mesmo, e só para quem já está cadastrado.
 *
 * Regras refletidas na UI (garantidas no backend):
 *  - e-mail duplicado no tenant é bloqueado (409) com erro inline no formulário;
 *  - uma pessoa só faz parte de UMA célula: quem já tem célula não pode ser
 *    convidado (transferir é ação exclusiva do admin, à parte);
 *  - quem já tem acesso ao painel não pode receber acesso de novo;
 *  - remover/rebaixar o ÚLTIMO admin é bloqueado (409) — a igreja nunca fica
 *    sem administrador.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { fetchCellsFull, type CellSummary } from "@/lib/cells-api";
import { fetchContacts, type Contact } from "@/lib/contacts-api";
import { ApiError, fetchTeam, type TeamMember } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import { normalizeRoles, ROLE_ORDER, type Role } from "@/lib/roles";
import {
  inviteMember,
  resendInvite,
  revokeAccess,
  TeamConflictError,
  updateRoles,
} from "@/lib/team-api";

import { RolePick, RoleTags } from "./RolePick";

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

  // Convite: admin e pastor marcam a célula (um líder de célula convida para a
  // própria célula em outra superfície). Editar papéis / remover é só do admin.
  const isAdminUser = !!user && user.roles.includes("admin");
  const podeConvidar =
    !!user && (user.roles.includes("admin") || user.roles.includes("pastor"));

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
  const [invNeedsEmail, setInvNeedsEmail] = useState(false);
  const [invCelulaId, setInvCelulaId] = useState("");
  const [invError, setInvError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  // base de pessoas cadastradas + células ativas (carregadas ao abrir o convite)
  const [pessoas, setPessoas] = useState<Contact[]>([]);
  const [pessoasTotal, setPessoasTotal] = useState(0);
  const [pessoasLoaded, setPessoasLoaded] = useState(false);
  const [celulas, setCelulas] = useState<CellSummary[]>([]);
  const [celulasLoaded, setCelulasLoaded] = useState(false);

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

  // Ao abrir o convite, carrega (uma vez) a base de pessoas e as células ativas.
  useEffect(() => {
    if (!inviteOpen || !token) return;
    let active = true;
    if (!pessoasLoaded) {
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
          // silencioso: a lista vazia já orienta a cadastrar em Contatos.
        }
      })();
    }
    if (!celulasLoaded) {
      void (async () => {
        try {
          const page = await fetchCellsFull(token);
          if (active) {
            setCelulas(page.items.filter((c) => c.ativo));
            setCelulasLoaded(true);
          }
        } catch (err) {
          if (handleSessionError(err)) return;
        }
      })();
    }
    return () => {
      active = false;
    };
  }, [inviteOpen, token, pessoasLoaded, celulasLoaded, handleSessionError]);

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
    setInvCelulaId("");
    setInvError(null);
    // invalida os caches: reabrir o convite recarrega (inclui quem/o que foi
    // criado no meio tempo).
    setPessoas([]);
    setPessoasTotal(0);
    setPessoasLoaded(false);
    setCelulas([]);
    setCelulasLoaded(false);
  }, []);

  const emailValid = (email: string) => /\S+@\S+\.\S+/.test(email.trim());
  const inviteReady =
    emailValid(invEmail) &&
    invCelulaId !== "" &&
    (invMode === "existente" ? invPessoaId !== null : invNome.trim().length > 0);

  const submitInvite = useCallback(async () => {
    if (!token || !inviteReady) return;
    setInviting(true);
    setInvError(null);
    try {
      const dest = invEmail.trim().toLowerCase();
      const result = await inviteMember(token, {
        email: dest,
        celulaId: invCelulaId,
        ...(invMode === "existente"
          ? { pessoaId: invPessoaId ?? undefined }
          : { nome: invNome.trim() }),
      });
      flashToast(
        result.emailEnviado
          ? { kind: "ok", text: `Convite enviado para ${dest}.` }
          : {
              kind: "err",
              text: "Acesso criado, mas o e-mail de convite não saiu (e-mail não configurado no servidor). Configure o envio e reenvie.",
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
  }, [token, inviteReady, invMode, invPessoaId, invNome, invEmail, invCelulaId, flashToast, resetInvite, load, handleSessionError]);

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

  const handleRevoke = useCallback(
    async (m: TeamMember) => {
      if (!token) return;
      if (
        !window.confirm(
          `Revogar o acesso de ${m.nome}? Ele perde o acesso ao painel imediatamente (o cadastro é preservado para auditoria).`,
        )
      ) {
        return;
      }
      setBusyId(m.usuarioId);
      try {
        await revokeAccess(token, m.usuarioId);
        flashToast({ kind: "ok", text: `Acesso de ${m.nome} revogado.` });
        await load("retry");
      } catch (err) {
        if (handleSessionError(err)) return;
        if (err instanceof TeamConflictError) {
          flashToast({ kind: "err", text: err.message });
        } else {
          flashToast({
            kind: "err",
            text: err instanceof ApiError ? err.message : "Não foi possível revogar o acesso.",
          });
        }
      } finally {
        setBusyId(null);
      }
    },
    [token, flashToast, load, handleSessionError],
  );

  const columns: Array<Column<TeamMember>> = useMemo(() => {
    const base: Array<Column<TeamMember>> = [
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
    ];
    // Gestão de acessos (editar papéis / reenviar / remover) é só do admin.
    if (isAdminUser) {
      base.push({
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
            ) : m.status === "revogado" ? null : (
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={() => void handleRevoke(m)}
                disabled={busyId === m.usuarioId}
                aria-busy={busyId === m.usuarioId || undefined}
              >
                Revogar
              </button>
            )}
          </div>
        ),
      });
    }
    return base;
  }, [openEdit, isSelf, handleResend, handleRevoke, busyId, isAdminUser]);

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="equipe">
      <div className="screen-head">
        <div className="actions">
          {podeConvidar ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => (inviteOpen ? resetInvite() : setInviteOpen(true))}
            >
              <Icon name="plus" />
              <span>Dar acesso ao painel</span>
            </button>
          ) : null}
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
            Dê acesso ao painel e defina a célula. O convidado entra como{" "}
            <strong>membro</strong> — os papéis são definidos depois, aqui na equipe.
            Quem ainda não está cadastrado completa o cadastro (telefone) ao ativar o
            convite.
          </p>

          {invMode === "existente" ? (
            <>
              <div className="field" style={{ marginBottom: "var(--s2)" }}>
                <label htmlFor="invPessoaQuery">Pessoa</label>
                <input
                  id="invPessoaQuery"
                  value={invPessoaQuery}
                  onChange={(e) => setInvPessoaQuery(e.target.value)}
                  placeholder="Buscar por nome, telefone ou e-mail…"
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
                      const jaTemCelula = !!p.celulaId;
                      const bloqueado = jaTemAcesso || jaTemCelula;
                      const sel = invPessoaId === p.id;
                      return (
                        <button
                          type="button"
                          key={p.id}
                          onClick={() => {
                            if (!bloqueado) selectPessoa(p);
                          }}
                          disabled={bloqueado}
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
                            cursor: bloqueado ? "not-allowed" : "pointer",
                            opacity: bloqueado ? 0.55 : 1,
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
                          {jaTemAcesso ? (
                            <StatusPill tone="muted">Já tem acesso</StatusPill>
                          ) : jaTemCelula ? (
                            <StatusPill tone="muted">Já em célula</StatusPill>
                          ) : null}
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
              </div>

              {invPessoaId && invNeedsEmail ? (
                <div className="field" style={{ marginBottom: "var(--s2)" }}>
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
                Não está na lista? Cadastrar pessoa nova
              </button>
            </>
          ) : (
            <>
              <div className="row" style={{ marginBottom: "var(--s2)" }}>
                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="invNovoNome">Nome</label>
                  <input
                    id="invNovoNome"
                    value={invNome}
                    onChange={(e) => setInvNome(e.target.value)}
                    placeholder="Nome completo"
                    autoFocus
                  />
                </div>
                <div className="field" style={{ margin: 0 }}>
                  <label htmlFor="invNovoEmail">E-mail do convidado</label>
                  <input
                    id="invNovoEmail"
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
                  setInvError(null);
                }}
              >
                ← Voltar à busca de pessoa cadastrada
              </button>
            </>
          )}

          <div className="field" style={{ marginBottom: "var(--s3)" }}>
            <label htmlFor="invCelula">Célula do convidado</label>
            {celulasLoaded && celulas.length === 0 ? (
              <p className="sub" style={{ color: "var(--muted)" }}>
                Nenhuma célula ativa. Crie uma célula antes de convidar membros.
              </p>
            ) : (
              <select
                id="invCelula"
                value={invCelulaId}
                onChange={(e) => setInvCelulaId(e.target.value)}
              >
                <option value="">
                  {celulasLoaded ? "Selecione a célula…" : "Carregando células…"}
                </option>
                {celulas.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nome}
                  </option>
                ))}
              </select>
            )}
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
