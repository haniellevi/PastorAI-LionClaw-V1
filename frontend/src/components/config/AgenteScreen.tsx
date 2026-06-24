"use client";

/**
 * Tela #agente — configuração do Agente de IA (F? / US-27..29). Admin-only
 * (gating de rota no AppShell / seção config adminOnly em navigation.ts).
 *
 * Consome agent-api.ts:
 *  - api-llm-credential (POST /agent/credential): salva a credencial BYO. A chave
 *    NUNCA é reexibida após salvar (RNF-03); chave inválida NÃO ativa a credencial
 *    (status=invalid) e portanto não libera a ativação do agente.
 *  - api-agent-config (PUT /agent/config): salva o comportamento. Ativar o agente
 *    (ativo=true) sem credencial validada+ativa é bloqueado (409 →
 *    AgentCredentialRequiredError) com erro inline.
 *  - api-crons (POST /agent/crons): cria agendamentos. O gatilho de estado é
 *    validado antes de salvar (422 quando inválido) com erro inline.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { Toggle } from "@/components/ui/Toggle";
import { SessionExpiredError } from "@/lib/api";
import {
  createConfigRequest,
  createCron,
  CRON_TRIGGERS,
  fetchAgentConfig,
  fetchConfigRequests,
  fetchCredentialStatus,
  fetchCrons,
  LLM_PROVIDERS,
  saveCredential,
  updateCron,
  type AgentConfigRequestItem,
  type CronResult,
  type LlmProvider,
} from "@/lib/agent-api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";

type Tab = "behavior" | "credential" | "crons";

type CredentialState = "none" | "active" | "invalid";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

const CRON_FREQUENCIES = [
  { code: "diaria", label: "Diária" },
  { code: "semanal", label: "Semanal" },
  { code: "quinzenal", label: "Quinzenal" },
  { code: "mensal", label: "Mensal" },
] as const;

function credentialTone(state: CredentialState): PillTone {
  if (state === "active") return "ok";
  if (state === "invalid") return "danger";
  return "muted";
}
function credentialLabel(state: CredentialState): string {
  if (state === "active") return "Credencial ativa";
  if (state === "invalid") return "Chave inválida";
  return "Sem credencial";
}

const REQUEST_TONE: Record<AgentConfigRequestItem["status"], PillTone> = {
  pendente: "muted",
  atendida: "ok",
  recusada: "danger",
};
const REQUEST_LABEL: Record<AgentConfigRequestItem["status"], string> = {
  pendente: "Pendente",
  atendida: "Atendida",
  recusada: "Recusada",
};

export function AgenteScreen() {
  const { token, expireSession } = useAuth();

  const [tab, setTab] = useState<Tab>("behavior");
  const [loading, setLoading] = useState(true);

  // ── Credencial LLM ──────────────────────────────────────────────────────
  const [provedor, setProvedor] = useState<LlmProvider>("openai");
  const [apiKey, setApiKey] = useState("");
  const [credentialState, setCredentialState] = useState<CredentialState>("none");
  const [savingCred, setSavingCred] = useState(false);
  const [credError, setCredError] = useState<string | null>(null);

  // ── Comportamento (READ-ONLY — configurado pelo master/plataforma) ───────
  const [nome, setNome] = useState("");
  const [tom, setTom] = useState("");
  const [comportamento, setComportamento] = useState("");
  const [ativo, setAtivo] = useState(false);

  // ── Requisições de mudança (admin → master) ──────────────────────────────
  const [requests, setRequests] = useState<AgentConfigRequestItem[]>([]);
  const [reqMensagem, setReqMensagem] = useState("");
  const [sendingReq, setSendingReq] = useState(false);
  const [reqError, setReqError] = useState<string | null>(null);

  // ── Crons ───────────────────────────────────────────────────────────────
  const [cronNome, setCronNome] = useState("");
  const [cronFrequencia, setCronFrequencia] = useState<string>(CRON_FREQUENCIES[0].code);
  const [cronGatilho, setCronGatilho] = useState<string>(CRON_TRIGGERS[0].code);
  const [cronAcao, setCronAcao] = useState("");
  const [cronAtivo, setCronAtivo] = useState(true);
  const [savingCron, setSavingCron] = useState(false);
  const [cronError, setCronError] = useState<string | null>(null);
  const [crons, setCrons] = useState<CronResult[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

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

  // ── Carrega o que já está salvo ao abrir (credencial/config/crons) ───────
  useEffect(() => {
    if (!token) return;
    let alive = true;
    void (async () => {
      try {
        const [cred, cfg, cronList, reqList] = await Promise.all([
          fetchCredentialStatus(token),
          fetchAgentConfig(token),
          fetchCrons(token),
          fetchConfigRequests(token),
        ]);
        if (!alive) return;
        setCredentialState(cred.status);
        if (cred.provedor) setProvedor(cred.provedor as LlmProvider);
        if (cfg.configured) {
          setNome(cfg.nome ?? "");
          setTom(cfg.tom ?? "");
          setComportamento(cfg.comportamento ?? "");
          setAtivo(cfg.ativo);
        }
        setCrons(cronList);
        setRequests(reqList);
      } catch (err) {
        if (handleSessionError(err)) return;
        // Falha de leitura não trava a tela — ainda dá pra salvar.
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [token, handleSessionError]);

  // ── Salvar credencial (a chave nunca volta após salvar) ──────────────────
  const submitCredential = useCallback(async () => {
    if (!token || savingCred || apiKey.trim().length === 0) return;
    setSavingCred(true);
    setCredError(null);
    try {
      const result = await saveCredential(token, { provedor, apiKey: apiKey.trim() });
      // RNF-03: nunca reexibir a chave — limpamos o campo imediatamente.
      setApiKey("");
      if (result.status === "active" && result.validado) {
        setCredentialState("active");
        flashToast({ kind: "ok", text: "Credencial validada e ativada." });
      } else {
        // Chave inválida NÃO ativa a credencial.
        setCredentialState("invalid");
        setCredError("A chave informada é inválida e não foi ativada. Verifique e tente novamente.");
      }
    } catch (err) {
      if (handleSessionError(err)) return;
      setApiKey("");
      setCredentialState("invalid");
      setCredError(err instanceof ApiError ? err.message : "Não foi possível salvar a credencial.");
    } finally {
      setSavingCred(false);
    }
  }, [token, savingCred, apiKey, provedor, flashToast, handleSessionError]);

  // ── Enviar requisição de mudança ao master ───────────────────────────────
  const submitRequest = useCallback(async () => {
    if (!token || sendingReq || reqMensagem.trim().length === 0) return;
    setSendingReq(true);
    setReqError(null);
    try {
      const created = await createConfigRequest(token, reqMensagem.trim());
      setRequests((prev) => [created, ...prev]);
      setReqMensagem("");
      flashToast({ kind: "ok", text: "Requisição enviada ao master." });
    } catch (err) {
      if (handleSessionError(err)) return;
      setReqError(
        err instanceof ApiError ? err.message : "Não foi possível enviar a requisição.",
      );
    } finally {
      setSendingReq(false);
    }
  }, [token, sendingReq, reqMensagem, flashToast, handleSessionError]);

  // ── Resetar o formulário de cron (sai do modo edição) ────────────────────
  const resetCronForm = useCallback(() => {
    setEditingId(null);
    setCronNome("");
    setCronFrequencia(CRON_FREQUENCIES[0].code);
    setCronGatilho(CRON_TRIGGERS[0].code);
    setCronAcao("");
    setCronAtivo(true);
    setCronError(null);
  }, []);

  // ── Carregar um cron no formulário para edição ───────────────────────────
  const startEdit = useCallback((cron: CronResult) => {
    setEditingId(cron.id);
    setCronNome(cron.nome);
    setCronFrequencia(cron.frequencia);
    // Preserva "sem gatilho" (cron só por frequência) ao editar — string vazia
    // vira null no submit. Sem isso, um cron sem gatilho ganharia um gatilho
    // silenciosamente no round-trip de edição (PUT é substituição total).
    setCronGatilho(cron.gatilhoEstado ?? "");
    setCronAcao(cron.acao ?? "");
    setCronAtivo(cron.ativo);
    setCronError(null);
  }, []);

  // ── Criar/editar cron (gatilho de estado validado antes de salvar) ───────
  const submitCron = useCallback(async () => {
    if (!token || savingCron || cronNome.trim().length === 0) return;
    setSavingCron(true);
    setCronError(null);
    const payload = {
      nome: cronNome.trim(),
      frequencia: cronFrequencia,
      gatilhoEstado: cronGatilho || null,
      acao: cronAcao.trim() || null,
      ativo: cronAtivo,
    };
    try {
      if (editingId) {
        const result = await updateCron(token, editingId, payload);
        setCrons((prev) => prev.map((c) => (c.id === result.id ? result : c)));
        resetCronForm();
        flashToast({ kind: "ok", text: `Agendamento “${result.nome}” atualizado.` });
      } else {
        const result = await createCron(token, payload);
        setCrons((prev) => [result, ...prev]);
        setCronNome("");
        setCronAcao("");
        flashToast({ kind: "ok", text: `Agendamento “${result.nome}” criado.` });
      }
    } catch (err) {
      if (handleSessionError(err)) return;
      // 422 → gatilho de estado inválido; 404 → cron de outra igreja.
      setCronError(
        err instanceof ApiError ? err.message : "Não foi possível salvar o agendamento.",
      );
    } finally {
      setSavingCron(false);
    }
  }, [token, savingCron, cronNome, cronFrequencia, cronGatilho, cronAcao, cronAtivo, editingId, resetCronForm, flashToast, handleSessionError]);

  // ── Ativar/desativar um cron (soft-disable via toggle de `ativo`) ────────
  const toggleCron = useCallback(
    async (cron: CronResult) => {
      // Bloqueia se há outro toggle em voo ou se a linha está em edição: editar
      // + alternar a mesma linha causaria um revert silencioso ao salvar.
      if (!token || togglingId || editingId === cron.id) return;
      setTogglingId(cron.id);
      setCronError(null);
      try {
        const result = await updateCron(token, cron.id, {
          nome: cron.nome,
          frequencia: cron.frequencia,
          gatilhoEstado: cron.gatilhoEstado,
          acao: cron.acao,
          ativo: !cron.ativo,
        });
        setCrons((prev) => prev.map((c) => (c.id === result.id ? result : c)));
        flashToast({
          kind: "ok",
          text: result.ativo
            ? `Agendamento “${result.nome}” ativado.`
            : `Agendamento “${result.nome}” desativado.`,
        });
      } catch (err) {
        if (handleSessionError(err)) return;
        setCronError(
          err instanceof ApiError ? err.message : "Não foi possível atualizar o agendamento.",
        );
      } finally {
        setTogglingId(null);
      }
    },
    [token, togglingId, editingId, flashToast, handleSessionError],
  );

  const credReady = apiKey.trim().length > 0;
  const cronReady = cronNome.trim().length > 0;

  return (
    <div className="screen" key="agente">
      <div className="screen-head">
        <div className="actions">
          <StatusPill tone={loading ? "muted" : credentialTone(credentialState)}>
            {loading ? "Carregando…" : credentialLabel(credentialState)}
          </StatusPill>
        </div>
      </div>

      <div className="tabs" style={{ marginBottom: "var(--s4)" }}>
        <button
          type="button"
          className={`tab${tab === "behavior" ? " active" : ""}`}
          onClick={() => setTab("behavior")}
        >
          Comportamento
        </button>
        <button
          type="button"
          className={`tab${tab === "credential" ? " active" : ""}`}
          onClick={() => setTab("credential")}
        >
          Credencial LLM
        </button>
        <button
          type="button"
          className={`tab${tab === "crons" ? " active" : ""}`}
          onClick={() => setTab("crons")}
        >
          Agendamentos
        </button>
      </div>

      {/* ── Tab: Comportamento (read-only — definido pela plataforma) ───── */}
      {tab === "behavior" ? (
        <>
        <div className="card card-pad">
          <div
            className="error-banner"
            role="status"
            style={{
              marginBottom: "var(--s3)",
              background: "var(--accent-soft)",
              color: "var(--accent)",
            }}
          >
            <Icon name="lock" />
            <span>
              O comportamento do agente é definido pela{" "}
              <strong>plataforma PastorAI</strong>. Para ajustes, envie uma
              requisição ao master abaixo.
            </span>
          </div>
          <div className="row" style={{ marginBottom: "var(--s3)" }}>
            <div className="field" style={{ margin: 0 }}>
              <label>Nome do agente</label>
              <div className="val">{nome || "—"}</div>
            </div>
            <div className="field" style={{ margin: 0 }}>
              <label>Tom de voz</label>
              <div className="val">{tom || "—"}</div>
            </div>
          </div>
          <div className="field" style={{ marginBottom: "var(--s3)" }}>
            <label>Comportamento e instruções</label>
            <div className="val" style={{ whiteSpace: "pre-wrap" }}>
              {comportamento || "Ainda não configurado pela plataforma."}
            </div>
          </div>
          <div className="seg-toggle-row">
            <span>Status do agente</span>
            <StatusPill tone={ativo ? "ok" : "muted"}>
              {ativo ? "Ativo" : "Desativado"}
            </StatusPill>
          </div>
        </div>

        {/* ── Requisição de mudança ao master ──────────────────────────── */}
        <form
          className="card card-pad"
          style={{ marginTop: "var(--s4)" }}
          onSubmit={(e) => {
            e.preventDefault();
            void submitRequest();
          }}
        >
          <div className="panel-title">Solicitar mudança ao master</div>
          {reqError ? (
            <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
              <Icon name="alert" />
              <span>{reqError}</span>
            </div>
          ) : null}
          <div className="field" style={{ marginBottom: "var(--s3)" }}>
            <label htmlFor="agReq">O que você gostaria de ajustar?</label>
            <textarea
              id="agReq"
              rows={3}
              value={reqMensagem}
              onChange={(e) => setReqMensagem(e.target.value)}
              placeholder="Ex.: deixar o tom mais formal e citar o nome da igreja na saudação."
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={reqMensagem.trim().length === 0 || sendingReq}
              aria-busy={sendingReq || undefined}
            >
              {sendingReq ? "Enviando…" : "Enviar requisição"}
            </button>
          </div>

          {requests.length > 0 ? (
            <div style={{ marginTop: "var(--s4)" }}>
              <div className="panel-title">Minhas requisições</div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Mensagem</th>
                    <th>Status</th>
                    <th>Resposta do master</th>
                  </tr>
                </thead>
                <tbody>
                  {requests.map((r) => (
                    <tr key={r.id}>
                      <td className="nm" style={{ whiteSpace: "pre-wrap" }}>{r.mensagem}</td>
                      <td>
                        <StatusPill tone={REQUEST_TONE[r.status]}>
                          {REQUEST_LABEL[r.status]}
                        </StatusPill>
                      </td>
                      <td className="sub" style={{ whiteSpace: "pre-wrap" }}>
                        {r.resposta ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </form>
        </>
      ) : null}

      {/* ── Tab: Credencial LLM ────────────────────────────────────────── */}
      {tab === "credential" ? (
        <form
          className="card card-pad"
          onSubmit={(e) => {
            e.preventDefault();
            void submitCredential();
          }}
        >
          {credError ? (
            <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
              <Icon name="alert" />
              <span>{credError}</span>
            </div>
          ) : null}
          <div className="field" style={{ marginBottom: "var(--s3)" }}>
            <label htmlFor="agProvider">Provedor</label>
            <select
              id="agProvider"
              value={provedor}
              onChange={(e) => setProvedor(e.target.value as LlmProvider)}
            >
              {LLM_PROVIDERS.map((p) => (
                <option key={p.code} value={p.code} disabled={!p.enabled}>
                  {p.label}
                  {p.enabled ? "" : " (em breve)"}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ marginBottom: "var(--s3)" }}>
            <label htmlFor="agKey">Chave da API</label>
            <input
              id="agKey"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                credentialState === "none"
                  ? "sk-…"
                  : "•••••••• — deixe em branco para manter"
              }
            />
            {credentialState === "active" ? (
              <p
                className="sub"
                style={{ color: "var(--ok)", marginTop: 6, display: "flex", alignItems: "center", gap: 6 }}
              >
                <Icon name="check" />
                <span>Chave configurada — preencha só se quiser trocá-la.</span>
              </p>
            ) : credentialState === "invalid" ? (
              <p
                className="sub"
                style={{ color: "var(--danger)", marginTop: 6, display: "flex", alignItems: "center", gap: 6 }}
              >
                <Icon name="alert" />
                <span>Há uma chave salva, mas inválida — informe uma nova.</span>
              </p>
            ) : null}
            <p className="sub" style={{ color: "var(--muted)", marginTop: 6 }}>
              A chave é cifrada no servidor e nunca é reexibida após salvar.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!credReady || savingCred}
              aria-busy={savingCred || undefined}
            >
              {savingCred ? "Validando…" : "Salvar credencial"}
            </button>
          </div>
        </form>
      ) : null}

      {/* ── Tab: Agendamentos (crons) ──────────────────────────────────── */}
      {tab === "crons" ? (
        <>
          <form
            className="card card-pad"
            style={{ marginBottom: "var(--s4)" }}
            onSubmit={(e) => {
              e.preventDefault();
              void submitCron();
            }}
          >
            {cronError ? (
              <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
                <Icon name="alert" />
                <span>{cronError}</span>
              </div>
            ) : null}
            <div className="row" style={{ marginBottom: "var(--s3)" }}>
              <div className="field" style={{ margin: 0 }}>
                <label htmlFor="cronName">Nome do agendamento</label>
                <input
                  id="cronName"
                  value={cronNome}
                  onChange={(e) => setCronNome(e.target.value)}
                  placeholder="Ex.: Cobrar relatórios pendentes"
                />
              </div>
              <div className="field" style={{ margin: 0 }}>
                <label htmlFor="cronFreq">Frequência</label>
                <select
                  id="cronFreq"
                  value={cronFrequencia}
                  onChange={(e) => setCronFrequencia(e.target.value)}
                >
                  {CRON_FREQUENCIES.map((f) => (
                    <option key={f.code} value={f.code}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="field" style={{ marginBottom: "var(--s3)" }}>
              <label htmlFor="cronTrigger">Gatilho de estado</label>
              <select
                id="cronTrigger"
                value={cronGatilho}
                onChange={(e) => setCronGatilho(e.target.value)}
              >
                <option value="">Sem gatilho (só frequência)</option>
                {CRON_TRIGGERS.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.label}
                  </option>
                ))}
              </select>
              <p className="sub" style={{ color: "var(--muted)", marginTop: 6 }}>
                O gatilho é validado antes de salvar — gatilhos inválidos são recusados.
              </p>
            </div>
            <div className="field" style={{ marginBottom: "var(--s3)" }}>
              <label htmlFor="cronAcao">Ação (mensagem/automação)</label>
              <textarea
                id="cronAcao"
                rows={3}
                value={cronAcao}
                onChange={(e) => setCronAcao(e.target.value)}
                placeholder="O que o agente deve fazer quando o gatilho ocorrer…"
              />
            </div>
            <div className="seg-toggle-row" style={{ marginBottom: "var(--s3)" }}>
              <span>{cronAtivo ? "Agendamento ativo" : "Agendamento pausado"}</span>
              <Toggle
                checked={cronAtivo}
                onChange={setCronAtivo}
                label="Ativar agendamento"
                disabled={savingCron}
              />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={!cronReady || savingCron}
                aria-busy={savingCron || undefined}
              >
                {savingCron
                  ? "Salvando…"
                  : editingId
                    ? "Salvar alterações"
                    : "Criar agendamento"}
              </button>
              {editingId ? (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={resetCronForm}
                  disabled={savingCron}
                >
                  Cancelar
                </button>
              ) : null}
            </div>
          </form>

          <div className="card">
            <div className="panel-title">Agendamentos configurados</div>
            {crons.length === 0 ? (
              <div className="empty-state" style={{ padding: "var(--s6)" }}>
                <Icon name="clock" />
                <p>
                  <strong>Nenhum agendamento ainda.</strong> Crie o primeiro acima
                  para automatizar tarefas por gatilho.
                </p>
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Nome</th>
                    <th>Frequência</th>
                    <th>Gatilho</th>
                    <th>Status</th>
                    <th>Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {crons.map((c) => (
                    <tr key={c.id}>
                      <td className="nm">{c.nome}</td>
                      <td>
                        {CRON_FREQUENCIES.find((f) => f.code === c.frequencia)?.label ??
                          c.frequencia}
                      </td>
                      <td className="sub">
                        {CRON_TRIGGERS.find((t) => t.code === c.gatilhoEstado)?.label ??
                          c.gatilhoEstado ??
                          "—"}
                      </td>
                      <td>
                        <StatusPill tone={c.ativo ? "ok" : "muted"}>
                          {c.ativo ? "Ativo" : "Pausado"}
                        </StatusPill>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 8 }}>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => startEdit(c)}
                            disabled={togglingId === c.id}
                          >
                            Editar
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => void toggleCron(c)}
                            disabled={togglingId !== null || editingId === c.id}
                            aria-busy={togglingId === c.id || undefined}
                          >
                            {c.ativo ? "Desativar" : "Ativar"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
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
