"use client";

/**
 * US-15 — Painel de decisão da solicitação (detalhe do master-detail). A Central
 * decide SEM editar o payload proposto (leitura apenas):
 *   • Aprovar — aguarda o servidor (loading no botão); multiplicação envia
 *     idempotency_key (reprocessar não duplica);
 *   • Rejeitar / Pedir ajuste — exigem `observacao_central` (validado no campo
 *     antes de enviar; 422 do servidor vira mensagem no campo).
 * Cada ação recarrega a fila via onDecided. Copy pt-BR (E17).
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import {
  approveRequest,
  rejectRequest,
  requestAdjustment,
  type CellRequest,
} from "@/lib/cell-requests-api";
import { formatPublishedAt } from "@/components/minha-celula/format";
import type { FlashToast } from "./types";

const TYPE_LABELS: Record<string, string> = {
  alterar_dia: "Alterar dia",
  alterar_horario: "Alterar horário",
  alterar_endereco: "Alterar endereço",
  alterar_anfitriao: "Alterar anfitrião",
  alterar_auxiliar: "Alterar auxiliar",
  transferir_membro: "Transferir membro",
  remover_membro: "Remover membro",
  multiplicacao: "Multiplicação",
};

const STATUS_META: Record<string, { label: string; tone: PillTone }> = {
  aguardando: { label: "Aguardando", tone: "warn" },
  ajuste_solicitado: { label: "Ajuste solicitado", tone: "accent" },
  aprovada: { label: "Aprovada", tone: "ok" },
  rejeitada: { label: "Rejeitada", tone: "danger" },
  cancelada: { label: "Cancelada", tone: "muted" },
};

const PAYLOAD_LABELS: Record<string, string> = {
  dia_reuniao: "Dia",
  horario: "Horário",
  endereco: "Endereço",
  anfitriao_id: "Anfitrião",
  auxiliar_id: "Auxiliar",
  membro_id: "Membro",
  celula_destino_id: "Célula destino",
  novo_lider_id: "Novo líder",
  membros_transferidos_ids: "Membros transferidos",
  nome_nova_celula: "Nome da nova célula",
};

function typeLabel(tipo: string): string {
  return TYPE_LABELS[tipo] ?? tipo;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

type Mode = null | "reject" | "adjust";

export function RequestDecisionPanel({
  token,
  request,
  onDecided,
  onToast,
  onClose,
}: {
  token: string;
  request: CellRequest;
  onDecided: (updated: CellRequest) => void;
  onToast: FlashToast;
  /** Fechar o detalhe (útil no mobile empilhado). */
  onClose?: () => void;
}) {
  const [mode, setMode] = useState<Mode>(null);
  const [observacao, setObservacao] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [busy, setBusy] = useState<null | "approve" | "reject" | "adjust">(null);

  const status = STATUS_META[request.status] ?? { label: request.status, tone: "muted" as PillTone };
  const isMultiplicacao = request.tipo === "multiplicacao";
  const payloadEntries = Object.entries(request.payload_proposto ?? {});

  async function approve() {
    if (busy) return;
    setBusy("approve");
    setFieldError(null);
    try {
      const key = isMultiplicacao
        ? (globalThis.crypto?.randomUUID?.() ?? `mult-${request.id}-${Date.now()}`)
        : undefined;
      const updated = await approveRequest(token, request.id, key);
      onToast({ kind: "ok", text: "Solicitação aprovada." });
      onDecided(updated);
    } catch (err) {
      onToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível aprovar a solicitação.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function submitObservacao() {
    if (busy) return;
    const text = observacao.trim();
    if (!text) {
      setFieldError("Escreva uma observação para o líder.");
      return;
    }
    const action = mode === "reject" ? "reject" : "adjust";
    setBusy(action);
    setFieldError(null);
    try {
      const updated =
        action === "reject"
          ? await rejectRequest(token, request.id, text)
          : await requestAdjustment(token, request.id, text);
      onToast({
        kind: "ok",
        text: action === "reject" ? "Solicitação rejeitada." : "Ajuste solicitado ao líder.",
      });
      onDecided(updated);
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Não foi possível concluir a decisão.";
      // 422 (observação ausente/ inválida) vira mensagem no campo.
      if (err instanceof ApiError && err.status === 422) {
        setFieldError(message);
      } else {
        onToast({ kind: "err", text: message });
      }
    } finally {
      setBusy(null);
    }
  }

  const anyBusy = busy !== null;

  return (
    <section className="card" aria-label="Decisão da solicitação">
      <div className="panel-title">
        <Icon name="document" /> {typeLabel(request.tipo)}
        <div className="right">
          <StatusPill tone={status.tone}>{status.label}</StatusPill>
          {onClose ? (
            <button
              type="button"
              className="btn btn-sm"
              onClick={onClose}
              aria-label="Fechar detalhe"
              style={{ marginLeft: "var(--s2)" }}
            >
              <Icon name="close" />
            </button>
          ) : null}
        </div>
      </div>

      <div className="section-body">
        {request.created_at ? (
          <div className="req-time" style={{ color: "var(--muted)", fontSize: 12 }}>
            Recebida em {formatPublishedAt(request.created_at)}
          </div>
        ) : null}

        {request.motivo ? (
          <p className="muted-note" style={{ marginTop: "var(--s2)" }}>
            <strong>Motivo do líder:</strong> {request.motivo}
          </p>
        ) : null}

        {/* Payload proposto — LEITURA apenas (Central não edita). */}
        <dl className="payload-view">
          {payloadEntries.length === 0 ? (
            <dd>Sem dados adicionais.</dd>
          ) : (
            payloadEntries.map(([k, v]) => (
              <div key={k}>
                <dt>{PAYLOAD_LABELS[k] ?? k}</dt>
                <dd>{renderValue(v)}</dd>
              </div>
            ))
          )}
        </dl>

        {request.observacao_central ? (
          <div className="notice-item origem-central" style={{ borderRadius: "var(--r-sm)" }}>
            <div className="notice-head">
              <Icon name="info" />
              <span className="notice-title">Observação da Central</span>
            </div>
            <p className="notice-body">{request.observacao_central}</p>
          </div>
        ) : null}

        {mode ? (
          <div className="field" style={{ marginTop: "var(--s3)" }}>
            <label htmlFor="obs-central">
              {mode === "reject" ? "Motivo da rejeição" : "O que ajustar"} (obrigatório)
            </label>
            <textarea
              id="obs-central"
              value={observacao}
              onChange={(e) => {
                setObservacao(e.target.value);
                if (fieldError) setFieldError(null);
              }}
              rows={3}
              maxLength={2000}
              aria-invalid={fieldError ? true : undefined}
              placeholder="Explique para o líder o que precisa ser revisto."
            />
            {fieldError ? (
              <div className="err" role="alert">
                {fieldError}
              </div>
            ) : null}
            <div className="chip-actions" style={{ marginTop: "var(--s3)" }}>
              <Button
                variant={mode === "reject" ? "danger" : "primary"}
                size="sm"
                onClick={() => void submitObservacao()}
                loading={busy === "reject" || busy === "adjust"}
                loadingText="Enviando…"
              >
                {mode === "reject" ? "Confirmar rejeição" : "Enviar ajuste"}
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={() => {
                  setMode(null);
                  setObservacao("");
                  setFieldError(null);
                }}
                disabled={anyBusy}
              >
                Voltar
              </Button>
            </div>
          </div>
        ) : (
          <div className="chip-actions" style={{ marginTop: "var(--s3)" }}>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void approve()}
              loading={busy === "approve"}
              loadingText="Aprovando…"
              disabled={anyBusy}
            >
              <Icon name="check" />
              <span>Aprovar</span>
            </Button>
            <Button
              variant="default"
              size="sm"
              onClick={() => setMode("adjust")}
              disabled={anyBusy}
            >
              <Icon name="refresh" />
              <span>Pedir ajuste</span>
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => setMode("reject")}
              disabled={anyBusy}
            >
              <Icon name="close" />
              <span>Rejeitar</span>
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}
