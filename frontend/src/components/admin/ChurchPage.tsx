"use client";

/**
 * Página dedicada de uma igreja no console master (tela cheia, não mais modal).
 * Abas: Dashboard (visão + ações), Agente (config do agente da igreja), Admins
 * (owner). A chave de LLM aparece só como STATUS (quem cadastra é a própria
 * igreja, no painel dela). Substitui o antigo IgrejaDetailModal.
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  addIgrejaAdmin,
  AdminSessionExpiredError,
  aprovarIgreja,
  deleteIgreja,
  fetchIgrejaAdmins,
  fetchIgrejaAgente,
  fetchIgrejaAgenteRequests,
  fetchIgrejaDetail,
  fetchOrquestrador,
  removeIgrejaAdmin,
  resendAdminInvite,
  resetIgrejaAgente,
  resolveAgenteRequest,
  saveIgrejaAgente,
  setIgrejaDono,
  updateIgreja,
  type AdminAgente,
  type AdminAgenteRequest,
  type AdminIgreja,
  type AdminIgrejaAdmin,
  type AdminIgrejaDetail,
  type UpdateIgrejaInput,
} from "@/lib/admin-api";

import type { PlanoOption } from "./CreateIgrejaModal";
import { EditIgrejaModal } from "./EditIgrejaModal";

const STATUS_LABEL: Record<string, string> = {
  ativa: "Ativa",
  suspensa: "Suspensa",
  aguardando_aprovacao: "Aguardando aprovação",
  inadimplente: "Inadimplente",
};

const REQUEST_STATUS_LABEL: Record<string, string> = {
  pendente: "Pendente",
  atendida: "Atendida",
  recusada: "Recusada",
};
const PLANO_LABEL: Record<string, string> = {
  ate_100: "Até 100",
  "101_200": "101–200",
  acima_201: "201+",
};
const CRED_LABEL: Record<string, string> = {
  active: "Credencial de IA ativa",
  invalid: "Chave de IA inválida",
  none: "Sem chave de IA",
};

const brl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const num = (v: number) => v.toLocaleString("pt-BR");

type Tab = "dashboard" | "agente" | "admins";

export interface ChurchPageProps {
  igreja: AdminIgreja;
  token: string;
  planos?: PlanoOption[];
  onBack: () => void;
  onExpired: () => void;
  /** Algo mudou (editar/aprovar) — o console recarrega a lista. */
  onChanged: () => void;
  /** A igreja foi excluída — voltar para a lista. */
  onDeleted: () => void;
}

export function ChurchPage({
  igreja: initial,
  token,
  planos,
  onBack,
  onExpired,
  onChanged,
  onDeleted,
}: ChurchPageProps) {
  const [igreja, setIgreja] = useState<AdminIgreja>(initial);
  const [tab, setTab] = useState<Tab>("dashboard");
  const [detail, setDetail] = useState<AdminIgrejaDetail | null>(null);
  const [admins, setAdmins] = useState<AdminIgrejaAdmin[] | null>(null);
  const [agente, setAgente] = useState<AdminAgente | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);

  const handleErr = useCallback(
    (err: unknown, fallback: string): string | null => {
      if (err instanceof AdminSessionExpiredError) {
        onExpired();
        return null;
      }
      return err instanceof Error ? err.message : fallback;
    },
    [onExpired],
  );

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const [d, a, ag] = await Promise.all([
        fetchIgrejaDetail(token, igreja.id),
        fetchIgrejaAdmins(token, igreja.id).catch(() => [] as AdminIgrejaAdmin[]),
        fetchIgrejaAgente(token, igreja.id).catch(() => null),
      ]);
      setDetail(d);
      setAdmins(a);
      setAgente(ag);
    } catch (err) {
      const m = handleErr(err, "Não foi possível carregar a igreja.");
      if (m) setError(m);
    }
  }, [token, igreja.id, handleErr]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const reloadAdmins = useCallback(() => {
    fetchIgrejaAdmins(token, igreja.id)
      .then(setAdmins)
      .catch(() => {
        /* mantém a lista atual */
      });
  }, [token, igreja.id]);

  const pending = igreja.status === "aguardando_aprovacao";

  const submitEdit = async (input: UpdateIgrejaInput) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await updateIgreja(token, igreja.id, input);
      setIgreja(updated);
      setEditOpen(false);
      onChanged();
      await loadAll();
    } catch (err) {
      const m = handleErr(err, "Não foi possível atualizar.");
      if (m) setError(m);
    } finally {
      setBusy(false);
    }
  };

  const submitDelete = async () => {
    setBusy(true);
    setError(null);
    try {
      await deleteIgreja(token, igreja.id);
      onChanged();
      onDeleted();
    } catch (err) {
      const m = handleErr(err, "Não foi possível excluir.");
      if (m) setError(m);
    } finally {
      setBusy(false);
    }
  };

  const submitAprovar = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await aprovarIgreja(token, igreja.id);
      setIgreja(updated);
      onChanged();
      await loadAll();
    } catch (err) {
      const m = handleErr(err, "Não foi possível aprovar.");
      if (m) setError(m);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", padding: "var(--s4)" }}>
      <button type="button" className="btn btn-sm btn-ghost" onClick={onBack}>
        ← Voltar
      </button>

      <header style={{ margin: "var(--s3) 0 var(--s4)" }}>
        <h1 style={{ margin: 0 }}>{igreja.nome}</h1>
        <p className="sub" style={{ margin: 0, color: "var(--muted)" }}>
          {STATUS_LABEL[igreja.status] ?? igreja.status}
          {igreja.plano ? ` · ${PLANO_LABEL[igreja.plano] ?? igreja.plano}` : ""}
        </p>
      </header>

      {error ? (
        <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
          <span>{error}</span>
        </div>
      ) : null}

      <div className="tabs" style={{ marginBottom: "var(--s4)" }}>
        {(["dashboard", "agente", "admins"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            className={`tab${tab === t ? " active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t === "dashboard" ? "Dashboard" : t === "agente" ? "Agente" : "Admins"}
          </button>
        ))}
      </div>

      {tab === "dashboard" ? (
        <DashboardTab
          igreja={igreja}
          detail={detail}
          agente={agente}
          pending={pending}
          busy={busy}
          onEdit={() => setEditOpen(true)}
          onApprove={submitAprovar}
        />
      ) : null}

      {tab === "agente" ? (
        <AgenteTab
          token={token}
          igrejaId={igreja.id}
          agente={agente}
          onExpired={onExpired}
          onSaved={(a) => setAgente(a)}
        />
      ) : null}

      {tab === "admins" ? (
        <AdminsTab
          token={token}
          igrejaId={igreja.id}
          admins={admins}
          onReload={reloadAdmins}
          onExpired={onExpired}
        />
      ) : null}

      {editOpen ? (
        <EditIgrejaModal
          igreja={igreja}
          busy={busy}
          error={null}
          planos={planos}
          onClose={() => setEditOpen(false)}
          onSubmit={submitEdit}
          onDelete={submitDelete}
        />
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card" style={{ padding: "var(--s3)" }}>
      <div className="sub" style={{ color: "var(--muted)" }}>
        {label}
      </div>
      <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{value}</div>
    </div>
  );
}

function DashboardTab({
  igreja,
  detail,
  agente,
  pending,
  busy,
  onEdit,
  onApprove,
}: {
  igreja: AdminIgreja;
  detail: AdminIgrejaDetail | null;
  agente: AdminAgente | null;
  pending: boolean;
  busy: boolean;
  onEdit: () => void;
  onApprove: () => void;
}) {
  return (
    <>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: "var(--s3)",
          marginBottom: "var(--s4)",
        }}
      >
        <Stat label="Membros (painel)" value={detail ? num(detail.membros) : "…"} />
        <Stat label="Pessoas" value={detail ? num(detail.pessoas) : "…"} />
        <Stat label="Células" value={detail ? num(detail.celulas) : "…"} />
        <Stat
          label="Mensalidade"
          value={detail?.mensalidade != null ? brl(detail.mensalidade) : "—"}
        />
        <Stat label="Custo de IA" value={detail ? brl(detail.custoIa) : "…"} />
        <Stat
          label="Chave de IA"
          value={agente ? CRED_LABEL[agente.credencialStatus] ?? "—" : "…"}
        />
      </div>

      {detail?.assinatura ? (
        <div className="card card-pad" style={{ marginBottom: "var(--s4)" }}>
          <div style={{ fontWeight: 600, marginBottom: "var(--s2)" }}>Assinatura</div>
          <div className="sub" style={{ color: "var(--muted)" }}>
            Plano {detail.assinatura.plano ?? "—"} · {detail.assinatura.status ?? "—"} ·
            próxima cobrança {detail.assinatura.proximaCobranca ?? "—"} · setup{" "}
            {detail.assinatura.setupPago ? "pago" : "pendente"}
          </div>
        </div>
      ) : null}

      <div style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap" }}>
        <Button variant="primary" size="sm" onClick={onEdit} disabled={busy}>
          Editar dados
        </Button>
        {pending ? (
          <Button
            variant="primary"
            size="sm"
            onClick={onApprove}
            loading={busy}
            loadingText="Aprovando…"
          >
            Aprovar igreja
          </Button>
        ) : null}
      </div>
      <p className="sub" style={{ color: "var(--muted)", marginTop: "var(--s2)" }}>
        A chave de LLM ({igreja.nome}) é cadastrada pela própria igreja no painel dela.
      </p>
    </>
  );
}

function AgenteTab({
  token,
  igrejaId,
  agente,
  onExpired,
  onSaved,
}: {
  token: string;
  igrejaId: string;
  agente: AdminAgente | null;
  onExpired: () => void;
  onSaved: (a: AdminAgente) => void;
}) {
  const [nome, setNome] = useState(agente?.nome ?? "");
  const [tom, setTom] = useState(agente?.tom ?? "");
  const [comportamento, setComportamento] = useState(agente?.comportamento ?? "");
  const [ativo, setAtivo] = useState(agente?.ativo ?? false);
  const [busy, setBusy] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const credStatus = agente?.credencialStatus ?? "none";

  // ── Fila de requisição admin → master ───────────────────────────────────
  const [requests, setRequests] = useState<AdminAgenteRequest[]>([]);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const list = await fetchIgrejaAgenteRequests(token, igrejaId);
        if (alive) setRequests(list);
      } catch {
        // Falha de leitura não trava a aba de config.
      }
    })();
    return () => {
      alive = false;
    };
  }, [token, igrejaId]);

  const resolver = async (req: AdminAgenteRequest, status: "atendida" | "recusada") => {
    if (resolvingId) return;
    const resposta = window.prompt(
      status === "atendida"
        ? "Resposta ao solicitante (opcional) — descreva o ajuste feito:"
        : "Motivo da recusa (opcional):",
      "",
    );
    if (resposta === null) return; // cancelou
    setResolvingId(req.id);
    setErr(null);
    try {
      const updated = await resolveAgenteRequest(token, req.id, {
        status,
        resposta: resposta.trim() || null,
      });
      // O endpoint não devolve o solicitante; preservamos o da linha original.
      setRequests((prev) =>
        prev.map((r) =>
          r.id === req.id
            ? { ...updated, solicitanteNome: r.solicitanteNome, solicitanteEmail: r.solicitanteEmail }
            : r,
        ),
      );
    } catch (e) {
      if (e instanceof AdminSessionExpiredError) {
        onExpired();
        return;
      }
      setErr(e instanceof Error ? e.message : "Não foi possível resolver a requisição.");
    } finally {
      setResolvingId(null);
    }
  };

  const restaurarPadrao = async () => {
    if (
      !window.confirm(
        "Restaurar o agente desta igreja para o modelo padrão do orquestrador? " +
          "O comportamento atual será substituído (o estado ligado/desligado é mantido).",
      )
    ) {
      return;
    }
    setResetting(true);
    setErr(null);
    try {
      const saved = await resetIgrejaAgente(token, igrejaId);
      setNome(saved.nome ?? "");
      setTom(saved.tom ?? "");
      setComportamento(saved.comportamento ?? "");
      setAtivo(saved.ativo);
      onSaved(saved);
    } catch (e) {
      if (e instanceof AdminSessionExpiredError) {
        onExpired();
        return;
      }
      setErr(e instanceof Error ? e.message : "Não foi possível restaurar o agente.");
    } finally {
      setResetting(false);
    }
  };

  const usarPadrao = async () => {
    try {
      const o = await fetchOrquestrador(token);
      setNome(o.nome ?? "");
      setTom(o.tom ?? "");
      setComportamento(o.comportamento ?? "");
      setErr(null);
    } catch (e) {
      if (e instanceof AdminSessionExpiredError) {
        onExpired();
        return;
      }
      setErr("Não foi possível carregar o modelo padrão.");
    }
  };

  const save = async () => {
    if (!comportamento.trim()) {
      setErr("Descreva o comportamento do agente.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const saved = await saveIgrejaAgente(token, igrejaId, {
        comportamento: comportamento.trim(),
        nome: nome.trim() || null,
        tom: tom.trim() || null,
        ativo,
      });
      onSaved(saved);
    } catch (e) {
      if (e instanceof AdminSessionExpiredError) {
        onExpired();
        return;
      }
      setErr(e instanceof Error ? e.message : "Não foi possível salvar o agente.");
      setAtivo(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
    <form
      className="card card-pad"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      {err ? (
        <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
          <span>{err}</span>
        </div>
      ) : null}
      <div className="field" style={{ marginBottom: "var(--s3)" }}>
        <label htmlFor="cp-nome">Nome do agente</label>
        <input id="cp-nome" value={nome} onChange={(e) => setNome(e.target.value)} placeholder="Ex.: Pastora Ana" />
      </div>
      <div className="field" style={{ marginBottom: "var(--s3)" }}>
        <label htmlFor="cp-tom">Tom de voz</label>
        <input id="cp-tom" value={tom} onChange={(e) => setTom(e.target.value)} placeholder="Ex.: acolhedor e pastoral" />
      </div>
      <div className="field" style={{ marginBottom: "var(--s3)" }}>
        <label htmlFor="cp-comp">Comportamento e instruções</label>
        <textarea
          id="cp-comp"
          rows={7}
          value={comportamento}
          onChange={(e) => setComportamento(e.target.value)}
          placeholder="Como o agente deve se comunicar, o que pode e não pode fazer…"
        />
      </div>
      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--s2)",
          opacity: credStatus === "active" ? 1 : 0.6,
          marginBottom: "var(--s2)",
        }}
      >
        <input
          type="checkbox"
          checked={ativo}
          disabled={credStatus !== "active"}
          onChange={(e) => setAtivo(e.target.checked)}
        />
        <span>Agente ativo</span>
      </label>
      <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s3)" }}>
        {CRED_LABEL[credStatus]}
        {credStatus !== "active" ? " — a igreja precisa cadastrar a chave de LLM para ligar." : ""}
      </p>
      <div style={{ display: "flex", gap: "var(--s2)" }}>
        <Button type="submit" variant="primary" size="sm" loading={busy} loadingText="Salvando…">
          Salvar agente
        </Button>
        <button
          type="button"
          className="btn btn-sm btn-ghost"
          disabled={busy || resetting}
          onClick={() => void usarPadrao()}
          title="Preenche com o modelo padrão do orquestrador (você revisa e salva)"
        >
          Usar o padrão
        </button>
        <button
          type="button"
          className="btn btn-sm btn-ghost"
          disabled={busy || resetting}
          onClick={() => void restaurarPadrao()}
          title="Restaura já a config para o modelo padrão (mantém ligado/desligado)"
        >
          {resetting ? "Restaurando…" : "Restaurar padrão"}
        </button>
      </div>
    </form>

    {/* ── Requisições do admin desta igreja ──────────────────────────── */}
    <div className="card card-pad" style={{ marginTop: "var(--s4)" }}>
      <div className="panel-title">Requisições de mudança do admin</div>
      {requests.length === 0 ? (
        <p className="sub" style={{ color: "var(--muted)" }}>
          Nenhuma requisição desta igreja.
        </p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Solicitante</th>
              <th>Mensagem</th>
              <th>Status</th>
              <th>Ações</th>
            </tr>
          </thead>
          <tbody>
            {requests.map((r) => (
              <tr key={r.id}>
                <td className="sub">{r.solicitanteNome ?? "—"}</td>
                <td style={{ whiteSpace: "pre-wrap" }}>{r.mensagem}</td>
                <td className="sub">
                  {REQUEST_STATUS_LABEL[r.status]}
                  {r.resposta ? ` — “${r.resposta}”` : ""}
                </td>
                <td>
                  {r.status === "pendente" ? (
                    <div style={{ display: "flex", gap: "var(--s2)" }}>
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={resolvingId !== null}
                        onClick={() => void resolver(r, "atendida")}
                      >
                        Atender
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        disabled={resolvingId !== null}
                        onClick={() => void resolver(r, "recusada")}
                      >
                        Recusar
                      </button>
                    </div>
                  ) : (
                    <span className="sub" style={{ color: "var(--muted)" }}>
                      Resolvida
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
    </>
  );
}

function AdminsTab({
  token,
  igrejaId,
  admins,
  onReload,
  onExpired,
}: {
  token: string;
  igrejaId: string;
  admins: AdminIgrejaAdmin[] | null;
  onReload: () => void;
  onExpired: () => void;
}) {
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    setBusy(true);
    setErr(null);
    setNotice(null);
    try {
      await fn();
      setNotice(okMsg);
      onReload();
    } catch (e) {
      if (e instanceof AdminSessionExpiredError) {
        onExpired();
        return;
      }
      setErr(e instanceof Error ? e.message : "Não foi possível concluir.");
    } finally {
      setBusy(false);
    }
  };

  const add = () => {
    if (!nome.trim() || !email.includes("@")) {
      setErr("Informe nome e e-mail válidos.");
      return;
    }
    void run(async () => {
      await addIgrejaAdmin(token, igrejaId, { nome: nome.trim(), email: email.trim() });
      setNome("");
      setEmail("");
    }, "Convite enviado.");
  };

  return (
    <div className="card card-pad">
      <div style={{ fontWeight: 600, marginBottom: "var(--s3)" }}>
        Administradores (owner)
      </div>
      {err ? (
        <div className="error-banner" role="alert" style={{ marginBottom: "var(--s2)" }}>
          <span>{err}</span>
        </div>
      ) : null}
      {notice ? (
        <div
          className="error-banner"
          role="status"
          style={{ background: "var(--accent-soft)", color: "var(--accent)", marginBottom: "var(--s2)" }}
        >
          <span>{notice}</span>
        </div>
      ) : null}

      {admins === null ? (
        <p className="sub" style={{ color: "var(--muted)" }}>
          Carregando…
        </p>
      ) : admins.length === 0 ? (
        <p className="sub" style={{ color: "var(--muted)" }}>
          Nenhum administrador.
        </p>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "var(--s2)",
            marginBottom: "var(--s3)",
          }}
        >
          {admins.map((a) => (
            <div
              key={a.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "var(--s2)",
                borderBottom: "1px solid var(--border)",
                paddingBottom: "var(--s2)",
              }}
            >
              <div>
                <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: "var(--s2)" }}>
                  {a.nome}
                  {a.isDono ? (
                    <span
                      title="Dono (admin principal) — gerencia a Assinatura"
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: "var(--accent)",
                        border: "1px solid var(--accent)",
                        borderRadius: 6,
                        padding: "1px 7px",
                      }}
                    >
                      Dono
                    </span>
                  ) : null}
                </div>
                <div className="sub" style={{ color: "var(--muted)" }}>
                  {a.email} · {a.status === "ativo" ? "ativo" : "convite pendente"}
                </div>
              </div>
              <div style={{ display: "flex", gap: "var(--s2)" }}>
                {a.status !== "ativo" ? (
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () => resendAdminInvite(token, igrejaId, a.id).then(() => undefined),
                        "Convite reenviado.",
                      )
                    }
                  >
                    Reenviar
                  </button>
                ) : null}
                {!a.isDono ? (
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    disabled={busy}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Tornar ${a.nome} o dono (admin principal) da igreja? Só o dono gerencia a Assinatura.`,
                        )
                      ) {
                        void run(
                          () => setIgrejaDono(token, igrejaId, a.id).then(() => undefined),
                          "Dono atualizado.",
                        );
                      }
                    }}
                  >
                    Tornar dono
                  </button>
                ) : null}
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm(`Remover ${a.nome} como administrador?`)) {
                      void run(
                        () => removeIgrejaAdmin(token, igrejaId, a.id),
                        "Administrador removido.",
                      );
                    }
                  }}
                >
                  Remover
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--s3)" }}>
        <div style={{ fontWeight: 600, marginBottom: "var(--s2)" }}>Convidar admin</div>
        <div className="field" style={{ marginBottom: "var(--s2)" }}>
          <label htmlFor="ad-nome">Nome</label>
          <input
            id="ad-nome"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            placeholder="Nome do administrador"
          />
        </div>
        <div className="field" style={{ marginBottom: "var(--s2)" }}>
          <label htmlFor="ad-email">E-mail</label>
          <input
            id="ad-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@igreja.org"
          />
        </div>
        <Button variant="primary" size="sm" onClick={add} loading={busy} loadingText="Enviando…">
          Convidar
        </Button>
      </div>
    </div>
  );
}
