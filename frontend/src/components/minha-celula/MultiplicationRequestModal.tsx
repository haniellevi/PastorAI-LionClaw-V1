"use client";

/**
 * US — Solicitação de MULTIPLICAÇÃO (líder → Central). A multiplicação nasce como
 * Solicitação (`POST /cell-requests` tipo `multiplicacao`, RF-14): não multiplica
 * na hora, vai para a Central aprovar. Payload espelha `MultiplicacaoPayload`
 * (backend, extra="forbid"): nome_nova_celula + novo_lider_id + N membros
 * transferidos (o novo líder é sempre incluído) + descendência (opcional).
 */
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import {
  createRequest,
  CellRequestConflictError,
} from "@/lib/cell-requests-api";
import type { CellMember } from "@/lib/cells-api";
import type { FlashToast } from "./types";

export function MultiplicationRequestModal({
  token,
  cellId,
  members,
  onClose,
  onToast,
  onCreated,
}: {
  token: string;
  cellId: string;
  /** Membros ativos da célula (candidatos a novo líder / transferidos). */
  members: CellMember[];
  onClose: () => void;
  onToast: FlashToast;
  onCreated: () => void;
}) {
  const [nome, setNome] = useState("");
  const [novoLiderId, setNovoLiderId] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [descendencia, setDescendencia] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // O novo líder é sempre um dos transferidos (invariante do backend).
  const membroIds = useMemo(() => {
    const ids = new Set(selected);
    if (novoLiderId) ids.add(novoLiderId);
    return [...ids];
  }, [selected, novoLiderId]);

  function toggle(pessoaId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(pessoaId)) next.delete(pessoaId);
      else next.add(pessoaId);
      return next;
    });
  }

  async function submit() {
    if (!nome.trim()) {
      setError("Informe o nome da nova célula.");
      return;
    }
    if (!novoLiderId) {
      setError("Escolha o novo líder.");
      return;
    }
    if (membroIds.length === 0) {
      setError("Selecione ao menos um membro para a nova célula.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createRequest(token, {
        celula_id: cellId,
        tipo: "multiplicacao",
        payload_proposto: {
          nome_nova_celula: nome.trim(),
          novo_lider_id: novoLiderId,
          membros_transferidos_ids: membroIds,
          ...(descendencia.trim() ? { descendencia: descendencia.trim() } : {}),
        },
      });
      onToast({ kind: "ok", text: "Solicitação de multiplicação enviada para aprovação." });
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

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Solicitar multiplicação"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Solicitar multiplicação</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>
        <div className="modal-sub">
          A multiplicação <strong>não acontece na hora</strong>: esta solicitação vai
          para a Central aprovar. A nova célula só é criada após a aprovação.
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
          <Field
            label="Nome da nova célula"
            placeholder="Ex.: Célula Filha"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            disabled={busy}
            maxLength={120}
            autoFocus
          />

          <div className="field">
            <label htmlFor="mult-lider">Novo líder</label>
            <select
              id="mult-lider"
              value={novoLiderId}
              onChange={(e) => setNovoLiderId(e.target.value)}
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

          <div className="field">
            <label>Membros que vão para a nova célula</label>
            <div className="check-list">
              {members.map((m) => {
                const isLeader = m.pessoa_id === novoLiderId;
                const checked = isLeader || selected.has(m.pessoa_id);
                return (
                  <label key={m.pessoa_id} className="check-row">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={busy || isLeader}
                      onChange={() => toggle(m.pessoa_id)}
                    />
                    <span>
                      {m.nome}
                      {isLeader ? " (novo líder)" : ""}
                    </span>
                  </label>
                );
              })}
              {members.length === 0 ? (
                <p className="muted-note">Nenhum membro ativo para transferir.</p>
              ) : null}
            </div>
          </div>

          <div className="field">
            <label htmlFor="mult-desc">Descendência (opcional)</label>
            <input
              id="mult-desc"
              type="text"
              value={descendencia}
              onChange={(e) => setDescendencia(e.target.value)}
              disabled={busy}
              maxLength={120}
              placeholder="Ex.: G12 Norte"
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
