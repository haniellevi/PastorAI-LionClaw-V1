"use client";

/**
 * Tela #comunicados — envio segmentado pelo WhatsApp oficial respeitando
 * consentimento/opt-out (RF-38 / US-31..33). Fluxo em três passos:
 *   compose  → título + mensagem;
 *   segment  → segmentos (toggle-switch) + data-table de destinatários + envio;
 *   review   → confirmação e disparo via api-broadcasts.
 *
 * Regras refletidas na UI (aplicadas no backend):
 *  - opt-out/sem consentimento são removidos; alcance 0 bloqueia o envio
 *    (status=bloqueado) com a contagem de ignorados;
 *  - agendamento no passado é bloqueado;
 *  - WhatsApp offline impede "enviar agora" e sugere agendar;
 *  - segmento sem pessoas avisa no passo segment; histórico vazio usa empty-state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Toggle } from "@/components/ui/Toggle";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  SEGMENTS,
  countSegment,
  createBroadcast,
  fetchBroadcasts,
  repeatLabel,
  resolveRecipients,
  type BroadcastItem,
  type BroadcastRepeat,
  type BroadcastResult,
} from "@/lib/broadcasts-api";
import { fetchContacts, tipoLabel, tipoTone, type Contact } from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import { fetchConnection, type ConnectionStatus } from "@/lib/whatsapp-api";

type Step = "compose" | "segment" | "review";
type ConnState = ConnectionStatus | "unknown";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

const STEP_LABEL: Record<Step, string> = {
  compose: "Mensagem",
  segment: "Segmentos",
  review: "Revisão",
};

function statusTone(status: string | null): PillTone {
  switch (status) {
    case "enviado":
      return "ok";
    case "agendado":
      return "accent";
    case "rascunho":
    case "bloqueado":
      return "danger";
    default:
      return "muted";
  }
}

function statusLabel(b: BroadcastItem): string {
  if (b.status === "enviado") return `Enviado · ${b.alcance ?? 0}`;
  if (b.status === "agendado") return `Agendado · ${repeatLabel(b.repeticao)}`;
  if (b.status === "rascunho") return "Bloqueado · opt-out";
  return b.status ?? "—";
}

export function ComunicadosScreen() {
  const { token, expireSession } = useAuth();

  const [contacts, setContacts] = useState<Contact[]>([]);
  const [history, setHistory] = useState<BroadcastItem[]>([]);
  const [conn, setConn] = useState<ConnState>("unknown");
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [step, setStep] = useState<Step>("compose");
  const [titulo, setTitulo] = useState("");
  const [mensagem, setMensagem] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set(["todos"]));
  const [scheduleOn, setScheduleOn] = useState(false);
  const [data, setData] = useState("");
  const [hora, setHora] = useState("09:00");
  const [repeticao, setRepeticao] = useState<BroadcastRepeat>("once");

  const [submitting, setSubmitting] = useState(false);
  const [blocked, setBlocked] = useState<BroadcastResult | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

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
        const [contactPage, broadcastPage] = await Promise.all([
          fetchContacts(token),
          fetchBroadcasts(token),
        ]);
        setContacts(contactPage.items);
        setHistory(broadcastPage.items);
        setLoaded(true);
        // Status do WhatsApp é admin-only: 403/erro não bloqueia a tela.
        try {
          const info = await fetchConnection(token);
          setConn(info.status);
        } catch {
          setConn("unknown");
        }
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar os comunicados.");
      } finally {
        setLoading(false);
      }
    },
    [token, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

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

  const selectedTokens = useMemo(() => Array.from(selected), [selected]);
  const recipients = useMemo(
    () => resolveRecipients(contacts, selectedTokens),
    [contacts, selectedTokens],
  );

  const toggleSegment = useCallback((tokenName: string, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(tokenName);
      else next.delete(tokenName);
      return next;
    });
  }, []);

  // ---- regras de envio ----------------------------------------------------
  const whatsappOffline = conn === "offline";
  const sendNowBlocked = !scheduleOn && whatsappOffline;

  const schedulePast = useMemo(() => {
    if (!scheduleOn || !data) return false;
    const dt = new Date(`${data}T${hora || "00:00"}`);
    return dt.getTime() < Date.now();
  }, [scheduleOn, data, hora]);

  const composeReady = titulo.trim().length > 0 && mensagem.trim().length > 0;
  const segmentReady =
    selectedTokens.length > 0 &&
    recipients.length > 0 &&
    (!scheduleOn || (Boolean(data) && !schedulePast)) &&
    !sendNowBlocked;

  const resetWizard = useCallback(() => {
    setStep("compose");
    setTitulo("");
    setMensagem("");
    setSelected(new Set(["todos"]));
    setScheduleOn(false);
    setData("");
    setHora("09:00");
    setRepeticao("once");
    setBlocked(null);
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!token) return;
    setSubmitting(true);
    setBlocked(null);
    try {
      const result = await createBroadcast(token, {
        titulo: titulo.trim(),
        mensagem: mensagem.trim(),
        segmentos: selectedTokens,
        modo: scheduleOn ? "agendado" : "agora",
        agendamento: scheduleOn ? { data, hora, repeticao } : null,
      });

      if (result.status === "bloqueado") {
        setBlocked(result);
        return;
      }

      // Recarrega o histórico com o novo comunicado e reinicia o fluxo.
      try {
        const page = await fetchBroadcasts(token);
        setHistory(page.items);
      } catch {
        /* histórico opcional */
      }
      flashToast({
        kind: "ok",
        text:
          result.status === "agendado"
            ? `Comunicado agendado. ${result.ignoradosOptout} ignorado(s) por opt-out.`
            : `Comunicado enviado a ${result.enviados} contato(s). ${result.ignoradosOptout} ignorado(s).`,
      });
      resetWizard();
    } catch (err) {
      if (handleSessionError(err)) return;
      flashToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível enviar o comunicado.",
      });
    } finally {
      setSubmitting(false);
    }
  }, [
    token,
    titulo,
    mensagem,
    selectedTokens,
    scheduleOn,
    data,
    hora,
    repeticao,
    flashToast,
    handleSessionError,
    resetWizard,
  ]);

  const recipientColumns: Array<Column<Contact>> = useMemo(
    () => [
      {
        header: "Destinatário",
        cell: (c) => <span className="nm">{c.nome}</span>,
      },
      {
        header: "Tipo",
        cell: (c) => <StatusPill tone={tipoTone(c.tipo)}>{tipoLabel(c.tipo)}</StatusPill>,
      },
    ],
    [],
  );

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="comunicados">
      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={() => void load("retry")} disabled={loading}>
            Tentar novamente
          </button>
        </div>
      ) : null}

      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="card card-pad">
          {/* steps */}
          <ol className="bc-steps" aria-label="Etapas do comunicado">
            {(["compose", "segment", "review"] as Step[]).map((s, i) => (
              <li
                key={s}
                className={`bc-step${step === s ? " active" : ""}${
                  ["compose", "segment", "review"].indexOf(step) > i ? " done" : ""
                }`}
              >
                <span className="bc-step-n">{i + 1}</span>
                <span>{STEP_LABEL[s]}</span>
              </li>
            ))}
          </ol>

          {showSkeleton ? (
            <div className="queue">
              {Array.from({ length: 3 }).map((_, i) => (
                <div className="qitem skeleton" key={i}>
                  <div className="qbody">
                    <div className="sk-line sk-md" />
                    <div className="sk-line sk-sm" />
                  </div>
                </div>
              ))}
            </div>
          ) : step === "compose" ? (
            <>
              <div className="field">
                <label htmlFor="bcTitle">Título interno</label>
                <input
                  id="bcTitle"
                  value={titulo}
                  onChange={(e) => setTitulo(e.target.value)}
                  placeholder="Ex.: Convite culto de domingo"
                />
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="bcMsg">Mensagem</label>
                <textarea
                  id="bcMsg"
                  rows={4}
                  value={mensagem}
                  onChange={(e) => setMensagem(e.target.value)}
                  placeholder="Escreva a mensagem que será enviada…"
                />
                <div className="helper">
                  Opt-out e contatos sem consentimento são removidos do envio
                  automaticamente.
                </div>
              </div>
              <div className="modal-foot">
                <span />
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!composeReady}
                  onClick={() => setStep("segment")}
                >
                  Avançar
                </button>
              </div>
            </>
          ) : step === "segment" ? (
            <>
              <div className="field">
                <label>Segmentos <span className="helper" style={{ fontWeight: 400 }}>· marque um ou mais</span></label>
                <div className="seg-list">
                  {SEGMENTS.map((seg) => {
                    const count = countSegment(contacts, seg.token);
                    return (
                      <div className="seg-row" key={seg.token}>
                        <div style={{ flex: 1 }}>
                          <div className="nm">{seg.label}</div>
                          <div className="sub">{count} contato(s)</div>
                        </div>
                        <Toggle
                          label={seg.label}
                          checked={selected.has(seg.token)}
                          onChange={(on) => toggleSegment(seg.token, on)}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>

              {selectedTokens.length > 0 && recipients.length === 0 ? (
                <div className="degraded-banner" role="status" style={{ borderRadius: "var(--r-md)" }}>
                  <Icon name="alert" />
                  <span>Nenhuma pessoa nos segmentos selecionados. Escolha outro segmento.</span>
                </div>
              ) : null}

              <div className="field">
                <label>Destinatários estimados <span className="count">· {recipients.length}</span></label>
                <DataTable
                  columns={recipientColumns}
                  rows={recipients.slice(0, 50)}
                  rowKey={(c) => c.id}
                  empty={{
                    icon: "user",
                    title: "Nenhum destinatário no segmento.",
                    hint: "Selecione um segmento com pessoas.",
                  }}
                />
                <div className="helper">
                  Estimativa por segmento. O número final exclui opt-out e contatos
                  sem consentimento (calculado no envio).
                </div>
              </div>

              <div className="field">
                <label>Envio</label>
                <div className="seg-toggle-row">
                  <span>{scheduleOn ? "Agendar envio" : "Enviar agora"}</span>
                  <Toggle
                    label="Agendar envio"
                    checked={scheduleOn}
                    onChange={(on) => setScheduleOn(on)}
                  />
                </div>
                {sendNowBlocked ? (
                  <div className="degraded-banner" role="alert" style={{ borderRadius: "var(--r-md)", marginTop: "var(--s3)" }}>
                    <Icon name="alert" />
                    <span>
                      WhatsApp offline: não é possível enviar agora. Ative
                      &ldquo;Agendar envio&rdquo; ou reconecte o número.
                    </span>
                  </div>
                ) : null}
              </div>

              {scheduleOn ? (
                <>
                  <div className="row">
                    <div className="field">
                      <label htmlFor="bcDate">Data</label>
                      <input id="bcDate" type="date" value={data} onChange={(e) => setData(e.target.value)} />
                    </div>
                    <div className="field">
                      <label htmlFor="bcTime">Hora</label>
                      <input id="bcTime" type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
                    </div>
                  </div>
                  <div className="field">
                    <label htmlFor="bcRepeat">Repetição (cron)</label>
                    <select
                      id="bcRepeat"
                      value={repeticao}
                      onChange={(e) => setRepeticao(e.target.value as BroadcastRepeat)}
                    >
                      <option value="once">Não repetir (uma vez)</option>
                      <option value="daily">Diariamente</option>
                      <option value="weekly">Semanalmente</option>
                      <option value="biweekly">Quinzenalmente</option>
                      <option value="monthly">Mensalmente</option>
                    </select>
                    {schedulePast ? (
                      <div className="err" role="alert">
                        Agendamento no passado. Escolha uma data e hora futuras.
                      </div>
                    ) : null}
                  </div>
                </>
              ) : null}

              <div className="modal-foot">
                <button type="button" className="btn" onClick={() => setStep("compose")}>
                  Voltar
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!segmentReady}
                  onClick={() => setStep("review")}
                >
                  Revisar
                </button>
              </div>
            </>
          ) : (
            <>
              <h4 style={{ marginBottom: "var(--s4)" }}>Revisão do comunicado</h4>
              <dl className="detail-list">
                <div>
                  <dt>Título</dt>
                  <dd>{titulo}</dd>
                </div>
                <div>
                  <dt>Segmentos</dt>
                  <dd>
                    {selectedTokens
                      .map((t) => SEGMENTS.find((s) => s.token === t)?.label ?? t)
                      .join(", ")}
                  </dd>
                </div>
                <div>
                  <dt>Alcance estimado</dt>
                  <dd className="num">{recipients.length}</dd>
                </div>
                <div>
                  <dt>Envio</dt>
                  <dd>
                    {scheduleOn
                      ? `Agendado · ${data} ${hora} · ${repeatLabel(repeticao)}`
                      : "Enviar agora"}
                  </dd>
                </div>
              </dl>

              <div className="field" style={{ marginTop: "var(--s3)" }}>
                <label>Mensagem</label>
                <p className="sub" style={{ color: "var(--muted)" }}>{mensagem}</p>
              </div>

              {blocked ? (
                <div className="degraded-banner" role="alert" style={{ borderRadius: "var(--r-md)" }}>
                  <Icon name="alert" />
                  <span>
                    Envio bloqueado: alcance zero (todos com opt-out ou sem
                    consentimento). {blocked.ignoradosOptout} contato(s) ignorado(s).
                  </span>
                </div>
              ) : null}

              <div className="modal-foot">
                <button type="button" className="btn" onClick={() => setStep("segment")} disabled={submitting}>
                  Voltar
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={submitting}
                  aria-busy={submitting || undefined}
                  onClick={() => void handleSubmit()}
                >
                  {submitting ? "Enviando…" : scheduleOn ? "Agendar comunicado" : "Enviar comunicado"}
                </button>
              </div>
            </>
          )}
        </div>

        <div className="card">
          <div className="panel-title">Comunicados recentes e agendados</div>
          {showSkeleton ? (
            <div className="queue">
              {Array.from({ length: 3 }).map((_, i) => (
                <div className="qitem skeleton" key={i}>
                  <div className="qbody">
                    <div className="sk-line sk-md" />
                    <div className="sk-line sk-sm" />
                  </div>
                </div>
              ))}
            </div>
          ) : history.length === 0 ? (
            <div className="empty-state" style={{ padding: "var(--s6)" }}>
              <Icon name="broadcast" />
              <p>
                <strong>Nenhum comunicado ainda.</strong> Crie o primeiro envio
                segmentado ao lado.
              </p>
            </div>
          ) : (
            <div>
              {history.map((b) => (
                <div className="list-row" key={b.id}>
                  <div style={{ flex: 1 }}>
                    <div className="nm">{b.titulo}</div>
                    <div className="sub">
                      {b.segmentos
                        .map((t) => SEGMENTS.find((s) => s.token === t)?.label ?? t)
                        .join(", ")}
                    </div>
                  </div>
                  <StatusPill tone={statusTone(b.status)}>{statusLabel(b)}</StatusPill>
                </div>
              ))}
            </div>
          )}
        </div>
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
