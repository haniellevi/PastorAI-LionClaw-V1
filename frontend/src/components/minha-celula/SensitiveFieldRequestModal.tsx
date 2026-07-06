"use client";

/**
 * US-13 — Solicitação de alteração de campo SENSÍVEL (líder → Central). Campos
 * sensíveis (dia, horário, endereço, anfitrião, auxiliar, transferir/remover
 * membro) NUNCA são salvos direto: viram uma Solicitação que nasce 'aguardando'
 * e não altera o dado real (RF-14). O payload por tipo espelha EXATAMENTE o
 * backend (cell_requests.py). 409 (já existe solicitação aberta conflitante) vira
 * toast explicativo. Sucesso: "Solicitação enviada para aprovação.".
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import {
  createRequest,
  CellRequestConflictError,
  type CellRequestType,
} from "@/lib/cell-requests-api";
import type { CellMember } from "@/lib/cells-api";
import type { FlashToast } from "./types";

const HORA_RE = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;

const DAYS = [
  "Domingo",
  "Segunda-feira",
  "Terça-feira",
  "Quarta-feira",
  "Quinta-feira",
  "Sexta-feira",
  "Sábado",
];

const TITLES: Record<CellRequestType, string> = {
  alterar_dia: "Solicitar alteração — dia da reunião",
  alterar_horario: "Solicitar alteração — horário",
  alterar_endereco: "Solicitar alteração — endereço",
  alterar_anfitriao: "Solicitar alteração — anfitrião",
  alterar_auxiliar: "Solicitar alteração — auxiliar",
  transferir_membro: "Solicitar transferência de membro",
  remover_membro: "Solicitar remoção de membro",
  multiplicacao: "Solicitar multiplicação",
};

/** Célula-destino mínima para a transferência de membro. */
export interface CellOption {
  id: string;
  nome: string;
}

export function SensitiveFieldRequestModal({
  token,
  cellId,
  tipo,
  target,
  members,
  otherCells,
  onClose,
  onToast,
  onCreated,
}: {
  token: string;
  cellId: string;
  tipo: CellRequestType;
  /** Membro alvo (transferir/remover). */
  target?: CellMember | null;
  /** Membros ativos (para anfitrião/auxiliar). */
  members: CellMember[];
  /** Outras células do tenant (destino da transferência). */
  otherCells: CellOption[];
  onClose: () => void;
  onToast: FlashToast;
  onCreated: () => void;
}) {
  const [dia, setDia] = useState("");
  const [horario, setHorario] = useState("");
  const [endereco, setEndereco] = useState("");
  const [pessoaId, setPessoaId] = useState("");
  const [destinoId, setDestinoId] = useState("");
  const [motivo, setMotivo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  const horaError =
    tipo === "alterar_horario" && horario.trim() && !HORA_RE.test(horario.trim())
      ? "Use o formato 24h HH:MM (ex.: 20:00)."
      : undefined;

  function buildPayload(): Record<string, unknown> | null {
    switch (tipo) {
      case "alterar_dia":
        if (!dia) return null;
        return { dia_reuniao: dia };
      case "alterar_horario":
        if (!horario.trim() || !HORA_RE.test(horario.trim())) return null;
        return { horario: horario.trim() };
      case "alterar_endereco":
        if (!endereco.trim()) return null;
        return { endereco: endereco.trim() };
      case "alterar_anfitriao":
        if (!pessoaId) return null;
        return { anfitriao_id: pessoaId };
      case "alterar_auxiliar":
        if (!pessoaId) return null;
        return { auxiliar_id: pessoaId };
      case "transferir_membro": {
        const pid = target?.pessoa_id ?? pessoaId;
        if (!pid || !destinoId) return null;
        return {
          pessoa_id: pid,
          celula_destino_id: destinoId,
          motivo: motivo.trim() || null,
        };
      }
      case "remover_membro": {
        const pid = target?.pessoa_id ?? pessoaId;
        if (!pid) return null;
        return { pessoa_id: pid, motivo: motivo.trim() || null };
      }
      default:
        return null;
    }
  }

  async function submit() {
    setTouched(true);
    if (horaError) return;
    const payload = buildPayload();
    if (!payload) {
      setError("Preencha os campos obrigatórios da solicitação.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createRequest(token, {
        celula_id: cellId,
        tipo,
        payload_proposto: payload,
        motivo: motivo.trim() || null,
      });
      onToast({ kind: "ok", text: "Solicitação enviada para aprovação." });
      onCreated();
      onClose();
    } catch (err) {
      const text =
        err instanceof CellRequestConflictError
          ? err.message
          : err instanceof ApiError
            ? err.message
            : "Não foi possível enviar a solicitação.";
      setError(text);
      onToast({ kind: "err", text });
    } finally {
      setBusy(false);
    }
  }

  const title = TITLES[tipo];
  const showMotivo = tipo !== "transferir_membro" && tipo !== "remover_membro";

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>{title}</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <div className="modal-sub">
          Campos sensíveis <strong>não mudam na hora</strong>. Esta solicitação vai
          para a Central aprovar; o dado só muda após a aprovação.
        </div>

        {error ? (
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
          </div>
        ) : null}

        <form
          className="modal-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {tipo === "alterar_dia" ? (
            <div className="field">
              <label htmlFor="req-dia">Novo dia da reunião</label>
              <select
                id="req-dia"
                value={dia}
                onChange={(e) => setDia(e.target.value)}
                disabled={busy}
              >
                <option value="">Selecione…</option>
                {DAYS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          {tipo === "alterar_horario" ? (
            <Field
              label="Novo horário"
              placeholder="Ex.: 20:00"
              value={horario}
              onChange={(e) => setHorario(e.target.value)}
              error={horaError}
              disabled={busy}
              maxLength={5}
              inputMode="numeric"
              autoFocus
            />
          ) : null}

          {tipo === "alterar_endereco" ? (
            <div className="field">
              <label htmlFor="req-endereco">Novo endereço</label>
              <textarea
                id="req-endereco"
                rows={2}
                value={endereco}
                onChange={(e) => setEndereco(e.target.value)}
                disabled={busy}
                maxLength={300}
                placeholder="Rua, número, bairro, referência…"
              />
            </div>
          ) : null}

          {tipo === "alterar_anfitriao" || tipo === "alterar_auxiliar" ? (
            <div className="field">
              <label htmlFor="req-pessoa">
                {tipo === "alterar_anfitriao" ? "Novo anfitrião" : "Novo auxiliar"}
              </label>
              <select
                id="req-pessoa"
                value={pessoaId}
                onChange={(e) => setPessoaId(e.target.value)}
                disabled={busy}
              >
                <option value="">Selecione…</option>
                {members.map((m) => (
                  <option key={m.pessoa_id} value={m.pessoa_id}>
                    {m.nome}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          {tipo === "transferir_membro" ? (
            <>
              {target ? (
                <div className="field">
                  <label>Membro</label>
                  <div className="static-value">{target.nome}</div>
                </div>
              ) : null}
              <div className="field">
                <label htmlFor="req-destino">Célula de destino</label>
                <select
                  id="req-destino"
                  value={destinoId}
                  onChange={(e) => setDestinoId(e.target.value)}
                  disabled={busy}
                >
                  <option value="">Selecione…</option>
                  {otherCells.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.nome}
                    </option>
                  ))}
                </select>
              </div>
            </>
          ) : null}

          {tipo === "remover_membro" && target ? (
            <div className="field">
              <label>Membro</label>
              <div className="static-value">{target.nome}</div>
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="req-motivo">
              {showMotivo ? "Motivo (opcional)" : "Motivo da solicitação (opcional)"}
            </label>
            <textarea
              id="req-motivo"
              rows={2}
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              disabled={busy}
              maxLength={500}
              placeholder="Explique o motivo para a Central."
            />
          </div>

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={busy}
              loadingText="Enviando…"
              disabled={touched && Boolean(horaError)}
            >
              <Icon name="send" />
              <span>Enviar solicitação</span>
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
