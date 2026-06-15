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
  AgentCredentialRequiredError,
  createCron,
  CRON_TRIGGERS,
  LLM_PROVIDERS,
  saveAgentConfig,
  saveCredential,
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

export function AgenteScreen() {
  const { token, expireSession } = useAuth();

  const [tab, setTab] = useState<Tab>("behavior");

  // ── Credencial LLM ──────────────────────────────────────────────────────
  const [provedor, setProvedor] = useState<LlmProvider>("openai");
  const [apiKey, setApiKey] = useState("");
  const [credentialState, setCredentialState] = useState<CredentialState>("none");
  const [savingCred, setSavingCred] = useState(false);
  const [credError, setCredError] = useState<string | null>(null);

  // ── Comportamento ───────────────────────────────────────────────────────
  const [nome, setNome] = useState("");
  const [tom, setTom] = useState("");
  const [comportamento, setComportamento] = useState("");
  const [ativo, setAtivo] = useState(false);
  const [savingBehavior, setSavingBehavior] = useState(false);
  const [behaviorError, setBehaviorError] = useState<string | null>(null);

  // ── Crons ───────────────────────────────────────────────────────────────
  const [cronNome, setCronNome] = useState("");
  const [cronFrequencia, setCronFrequencia] = useState<string>(CRON_FREQUENCIES[0].code);
  const [cronGatilho, setCronGatilho] = useState<string>(CRON_TRIGGERS[0].code);
  const [cronAcao, setCronAcao] = useState("");
  const [cronAtivo, setCronAtivo] = useState(true);
  const [savingCron, setSavingCron] = useState(false);
  const [cronError, setCronError] = useState<string | null>(null);
  const [crons, setCrons] = useState<CronResult[]>([]);

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

  // ── Salvar comportamento (ativar exige credencial validada) ──────────────
  const submitBehavior = useCallback(async () => {
    if (!token || savingBehavior || comportamento.trim().length === 0) return;
    setSavingBehavior(true);
    setBehaviorError(null);
    try {
      const result = await saveAgentConfig(token, {
        comportamento: comportamento.trim(),
        nome: nome.trim() || null,
        tom: tom.trim() || null,
        ativo,
      });
      setAtivo(result.ativo);
      flashToast({
        kind: "ok",
        text: result.ativo ? "Comportamento salvo e agente ativado." : "Comportamento salvo.",
      });
    } catch (err) {
      if (handleSessionError(err)) return;
      if (err instanceof AgentCredentialRequiredError) {
        // Ativação bloqueada: reverte o toggle e mantém a configuração salva manualmente.
        setAtivo(false);
        setBehaviorError(err.message);
      } else {
        setBehaviorError(
          err instanceof ApiError ? err.message : "Não foi possível salvar o comportamento.",
        );
      }
    } finally {
      setSavingBehavior(false);
    }
  }, [token, savingBehavior, comportamento, nome, tom, ativo, flashToast, handleSessionError]);

  // ── Criar cron (gatilho de estado validado antes de salvar) ──────────────
  const submitCron = useCallback(async () => {
    if (!token || savingCron || cronNome.trim().length === 0) return;
    setSavingCron(true);
    setCronError(null);
    try {
      const result = await createCron(token, {
        nome: cronNome.trim(),
        frequencia: cronFrequencia,
        gatilhoEstado: cronGatilho || null,
        acao: cronAcao.trim() || null,
        ativo: cronAtivo,
      });
      setCrons((prev) => [result, ...prev]);
      setCronNome("");
      setCronAcao("");
      flashToast({ kind: "ok", text: `Agendamento “${result.nome}” criado.` });
    } catch (err) {
      if (handleSessionError(err)) return;
      // 422 → gatilho de estado inválido (validado antes de salvar).
      setCronError(
        err instanceof ApiError ? err.message : "Não foi possível salvar o agendamento.",
      );
    } finally {
      setSavingCron(false);
    }
  }, [token, savingCron, cronNome, cronFrequencia, cronGatilho, cronAcao, cronAtivo, flashToast, handleSessionError]);

  const behaviorReady = comportamento.trim().length > 0;
  const credReady = apiKey.trim().length > 0;
  const cronReady = cronNome.trim().length > 0;

  return (
    <div className="screen" key="agente">
      <div className="screen-head">
        <div className="actions">
          <StatusPill tone={credentialTone(credentialState)}>
            {credentialLabel(credentialState)}
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

      {/* ── Tab: Comportamento ─────────────────────────────────────────── */}
      {tab === "behavior" ? (
        <form
          className="card card-pad"
          onSubmit={(e) => {
            e.preventDefault();
            void submitBehavior();
          }}
        >
          {behaviorError ? (
            <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
              <Icon name="alert" />
              <span>{behaviorError}</span>
            </div>
          ) : null}
          <div className="row" style={{ marginBottom: "var(--s3)" }}>
            <div className="field" style={{ margin: 0 }}>
              <label htmlFor="agName">Nome do agente</label>
              <input
                id="agName"
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Ex.: Pastora Ana"
              />
            </div>
            <div className="field" style={{ margin: 0 }}>
              <label htmlFor="agTom">Tom de voz</label>
              <input
                id="agTom"
                value={tom}
                onChange={(e) => setTom(e.target.value)}
                placeholder="Ex.: acolhedor e pastoral"
              />
            </div>
          </div>
          <div className="field" style={{ marginBottom: "var(--s3)" }}>
            <label htmlFor="agBehavior">Comportamento e instruções</label>
            <textarea
              id="agBehavior"
              rows={6}
              value={comportamento}
              onChange={(e) => setComportamento(e.target.value)}
              placeholder="Descreva como o agente deve se comunicar, o que pode e o que não pode fazer…"
            />
          </div>
          <div className="seg-toggle-row" style={{ marginBottom: "var(--s3)" }}>
            <span>{ativo ? "Agente ativo" : "Agente desativado"}</span>
            <Toggle
              checked={ativo}
              onChange={setAtivo}
              label="Ativar agente"
              disabled={savingBehavior}
            />
          </div>
          {credentialState !== "active" ? (
            <p
              className="sub"
              style={{ color: "var(--muted)", display: "flex", alignItems: "center", gap: 6, marginBottom: "var(--s3)" }}
            >
              <Icon name="lock" />
              <span>
                A ativação exige uma credencial validada na aba “Credencial LLM”.
              </span>
            </p>
          ) : null}
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!behaviorReady || savingBehavior}
              aria-busy={savingBehavior || undefined}
            >
              {savingBehavior ? "Salvando…" : "Salvar comportamento"}
            </button>
          </div>
        </form>
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
          <div className="config-row">
            <span style={{ color: "var(--muted)" }}>Status</span>
            <StatusPill tone={credentialTone(credentialState)}>
              {credentialLabel(credentialState)}
            </StatusPill>
          </div>
          <div className="field" style={{ marginTop: "var(--s3)", marginBottom: "var(--s3)" }}>
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
              placeholder="sk-…"
            />
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
                {savingCron ? "Salvando…" : "Criar agendamento"}
              </button>
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
                  </tr>
                </thead>
                <tbody>
                  {crons.map((c) => (
                    <tr key={c.id}>
                      <td className="nm">{c.nome}</td>
                      <td>{c.frequencia}</td>
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
