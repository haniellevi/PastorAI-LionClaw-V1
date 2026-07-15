"use client";

/**
 * EVT-8 PR3 — modal de confirmação de evento com configuração de notificação.
 *
 * Ao confirmar um evento 'a_confirmar' (importado do Google, EVT-6), o
 * pastor/admin pode configurar a notificação do PRÓPRIO evento: quando notificar
 * (antecedência ou data/hora específica), qual público coletivo e quais contatos
 * individuais (vindos das conversas do WhatsApp — sem digitação livre de
 * telefone). Submete via `confirmEvent(token, id, body)` (ConfirmEventRequest,
 * EVT-8 PR1); o backend só PERSISTE a intenção — o disparo real é EVT-9.
 *
 * Sem notificação (toggle desligado) → confirma sem body, mantendo o fluxo antigo.
 * NÃO há preview de destinatários resolvidos: o resolver (EVT-8 PR2) é interno e
 * não expõe endpoint ainda — o resumo aqui é só da configuração escolhida.
 *
 * Wave Visual W3: migração mecânica para o DsDialog (Esc/trap/backdrop/retorno
 * de foco do primitive; fechar bloqueado em busy) — mesmos campos, callbacks e
 * textos de antes.
 */

import { useEffect, useMemo, useState } from "react";

import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/dashboard-api";
import { fetchConversations, type Conversation } from "@/lib/conversations-api";
import {
  PUBLICO_ALVO_LABEL,
  type ConfirmEventInput,
  type EventItem,
  type IndividualTarget,
  type PublicoAlvo,
} from "@/lib/events-api";

const PUBLICOS: PublicoAlvo[] = ["toda_igreja", "pastores", "g12_pastoral", "lideres_celula"];

type QuandoOpt = "no_dia" | "1d" | "3d" | "7d" | "custom";

const ANTECEDENCIAS: { id: Exclude<QuandoOpt, "custom">; label: string; horas: number }[] = [
  { id: "no_dia", label: "No dia do evento", horas: 0 },
  { id: "1d", label: "1 dia antes", horas: 24 },
  { id: "3d", label: "3 dias antes", horas: 72 },
  { id: "7d", label: "7 dias antes", horas: 168 },
];

export function ConfirmEventModal({
  event,
  token,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  event: EventItem;
  token: string;
  busy: boolean;
  error: string | null;
  /** Sem argumento (ou undefined) = confirmar sem notificação. */
  onSubmit: (input?: ConfirmEventInput) => void;
  onClose: () => void;
}) {
  const [notify, setNotify] = useState(false);
  const [quando, setQuando] = useState<QuandoOpt>("1d");
  const [notificarEm, setNotificarEm] = useState("");
  const [publicos, setPublicos] = useState<Set<PublicoAlvo>>(new Set());
  const [selecionados, setSelecionados] = useState<Map<string, Conversation>>(new Map());
  const [mensagem, setMensagem] = useState("");

  // Picker individual: conversas do WhatsApp (carregadas ao ligar "Notificar").
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [convLoading, setConvLoading] = useState(false);
  const [convLoaded, setConvLoaded] = useState(false);
  const [convError, setConvError] = useState<string | null>(null);
  const [busca, setBusca] = useState("");

  useEffect(() => {
    if (!notify || convLoaded || convLoading) return;
    let alive = true;
    setConvLoading(true);
    setConvError(null);
    fetchConversations(token, 200)
      .then((page) => {
        if (!alive) return;
        setConvs(page.items);
        setConvLoaded(true);
      })
      .catch((err) => {
        if (alive) {
          setConvError(
            err instanceof ApiError ? err.message : "Não foi possível carregar os contatos.",
          );
        }
      })
      .finally(() => {
        if (alive) setConvLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [notify, convLoaded, convLoading, token]);

  const filtradas = useMemo(() => {
    const q = busca.trim().toLowerCase();
    if (!q) return convs;
    return convs.filter(
      (c) => (c.nome ?? "").toLowerCase().includes(q) || c.telefone.includes(q),
    );
  }, [convs, busca]);

  const togglePublico = (p: PublicoAlvo) =>
    setPublicos((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });

  const toggleContato = (c: Conversation) =>
    setSelecionados((prev) => {
      const next = new Map(prev);
      if (next.has(c.id)) next.delete(c.id);
      else next.set(c.id, c);
      return next;
    });

  const semDestino = publicos.size === 0 && selecionados.size === 0;
  // Início do evento como limite do datetime-local (a notificação é anterior).
  const eventoStart = event.data ? `${event.data}T${event.hora ?? "00:00"}` : undefined;
  const quandoInvalido = quando === "custom" && !notificarEm;
  const canSubmit = !busy && (!notify || (!semDestino && !quandoInvalido));

  const submit = () => {
    if (!notify) {
      onSubmit(undefined); // confirma sem notificação — fluxo antigo
      return;
    }
    const input: ConfirmEventInput = { canal: "whatsapp" };
    if (publicos.size) input.publicoAlvo = [...publicos];
    if (selecionados.size) {
      input.contatos = [...selecionados.values()].map<IndividualTarget>((c) =>
        c.pessoaId ? { pessoaId: c.pessoaId } : { telefone: c.telefone },
      );
    }
    if (quando === "custom") {
      if (notificarEm) input.notificarEm = new Date(notificarEm).toISOString();
    } else {
      input.antecedenciaHoras = ANTECEDENCIAS.find((a) => a.id === quando)?.horas ?? 0;
    }
    const msg = mensagem.trim();
    if (msg) input.mensagemConfirmacao = msg;
    onSubmit(input);
  };

  const quandoLabel =
    quando === "custom"
      ? notificarEm
        ? "data/hora específica"
        : "—"
      : (ANTECEDENCIAS.find((a) => a.id === quando)?.label.toLowerCase() ?? "");

  return (
    <DsDialog
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Confirmar evento"
    >
      <form
        className="modal-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) submit();
        }}
      >
        {error ? (
          <div className="error-banner" role="alert">
            <span>{error}</span>
          </div>
        ) : null}

        <div className="sub" style={{ marginBottom: "var(--s3)" }}>
          <strong>{event.titulo}</strong>
          {event.data ? ` · ${event.data}${event.hora ? ` ${event.hora}` : ""}` : ""}
        </div>

        <label
          className="field"
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}
        >
          <input
            type="checkbox"
            checked={notify}
            onChange={(e) => setNotify(e.target.checked)}
          />
          <span>Notificar sobre este evento</span>
        </label>

        {notify ? (
          <>
            <div className="field">
              <label htmlFor="cev-quando">Quando notificar</label>
              <select
                id="cev-quando"
                value={quando}
                onChange={(e) => setQuando(e.target.value as QuandoOpt)}
              >
                {ANTECEDENCIAS.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.label}
                  </option>
                ))}
                <option value="custom">Data/hora personalizada…</option>
              </select>
            </div>

            {quando === "custom" ? (
              <div className="field">
                <label htmlFor="cev-dt">Data e hora da notificação</label>
                <input
                  id="cev-dt"
                  type="datetime-local"
                  value={notificarEm}
                  max={eventoStart}
                  onChange={(e) => setNotificarEm(e.target.value)}
                />
                <span className="helper">Deve ser anterior ao início do evento.</span>
              </div>
            ) : null}

            <div className="field">
              <label>Público</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                {PUBLICOS.map((p) => (
                  <label
                    key={p}
                    style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer" }}
                  >
                    <input
                      type="checkbox"
                      checked={publicos.has(p)}
                      onChange={() => togglePublico(p)}
                    />
                    <span>{PUBLICO_ALVO_LABEL[p]}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="field">
              <label htmlFor="cev-busca">Contatos individuais</label>
              <input
                id="cev-busca"
                type="search"
                placeholder="Buscar contato…"
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
              />
              <div
                style={{
                  maxHeight: 180,
                  overflowY: "auto",
                  marginTop: 8,
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                }}
              >
                {convLoading ? (
                  <div className="sub" style={{ padding: 12 }}>
                    Carregando contatos…
                  </div>
                ) : convError ? (
                  <div className="sub" style={{ padding: 12 }}>
                    {convError}
                  </div>
                ) : filtradas.length === 0 ? (
                  <div className="sub" style={{ padding: 12 }}>
                    Nenhuma conversa encontrada.
                  </div>
                ) : (
                  filtradas.map((c) => (
                    <label
                      key={c.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "6px 10px",
                        cursor: "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={selecionados.has(c.id)}
                        onChange={() => toggleContato(c)}
                      />
                      <span style={{ minWidth: 0 }}>
                        <span
                          style={{
                            display: "block",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {c.nome ?? c.telefone}
                        </span>
                        {c.nome ? (
                          <span className="sub" style={{ display: "block" }}>
                            {c.telefone}
                          </span>
                        ) : null}
                      </span>
                    </label>
                  ))
                )}
              </div>
              <span className="helper">
                Só contatos que já conversaram no WhatsApp da igreja.
              </span>
            </div>

            <div className="field">
              <label htmlFor="cev-msg">Mensagem (opcional)</label>
              <textarea
                id="cev-msg"
                rows={3}
                maxLength={2000}
                value={mensagem}
                onChange={(e) => setMensagem(e.target.value)}
                placeholder="Texto do aviso (opcional)"
              />
              <span className="helper">{mensagem.length}/2000</span>
            </div>

            <div
              className="sub"
              style={{ padding: "8px 10px", background: "var(--surface-2)", borderRadius: 8 }}
            >
              {semDestino
                ? "Escolha ao menos um público ou contato."
                : `Notificar ${publicos.size} público(s) e ${selecionados.size} contato(s) · ${quandoLabel}.`}
              <br />
              <span className="muted">
                O disparo automático ainda não está ativo — isto apenas agenda/configura a
                notificação. Nada é enviado agora.
              </span>
            </div>
          </>
        ) : null}

        <div className="modal-foot">
          <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <Button
            type="submit"
            variant="primary"
            size="sm"
            loading={busy}
            loadingText="Confirmando…"
            disabled={!canSubmit}
          >
            {notify ? "Confirmar e agendar" : "Confirmar evento"}
          </Button>
        </div>
      </form>
    </DsDialog>
  );
}
