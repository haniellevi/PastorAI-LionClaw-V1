"use client";

/**
 * US — Solicitação de MULTIPLICAÇÃO (líder → Central). A multiplicação nasce como
 * Solicitação (`POST /cell-requests` tipo `multiplicacao`, RF-14): não multiplica
 * na hora, vai para a Central aprovar. Payload espelha `MultiplicacaoPayload`
 * (backend, extra="forbid"): nome_nova_celula + novo_lider_id + N membros
 * transferidos (o novo líder é sempre incluído) + descendência (opcional).
 */
import { useEffect, useMemo, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import {
  createRequest,
  CellRequestConflictError,
} from "@/lib/cell-requests-api";
import { fetchContacts, type Contact } from "@/lib/contacts-api";
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

  // Aptidão por pessoa (regra 2026-07-06): novo líder precisa ter feito o
  // Reencontro, não ser CSIM e não liderar célula ativa. Vem de api-contacts;
  // se a carga falhar, mantém tudo habilitado (o backend valida na aprovação).
  const [contactById, setContactById] = useState<Map<string, Contact> | null>(null);
  useEffect(() => {
    let alive = true;
    fetchContacts(token)
      .then((page) => {
        if (alive) setContactById(new Map(page.items.map((c) => [c.id, c])));
      })
      .catch(() => {
        /* sem dados de aptidão — degrade: backend bloqueia na aprovação */
      });
    return () => {
      alive = false;
    };
  }, [token]);

  function leaderBlockReason(pessoaId: string): string | null {
    const c = contactById?.get(pessoaId);
    if (!c) return null;
    if (c.semInteresse) return "fora da igreja";
    if (!c.aptoLider) return "ainda não fez o Reencontro";
    if (c.liderDeCelula) return "já lidera célula ativa";
    return null;
  }

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
    // Gate 9: shell migrado mecanicamente para o DsDialog (Esc/trap/
    // backdrop/retorno de foco do primitive; fechar bloqueado em busy).
    <DsDialog
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Solicitar multiplicação"
      description="A multiplicação não acontece na hora: esta solicitação vai para a Central aprovar. A nova célula só é criada após a aprovação."
    >
      <>


      {error ? <DsBanner kind="error">{error}</DsBanner> : null}

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
            data-autofocus=""
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
              {members.map((m) => {
                const reason = leaderBlockReason(m.pessoa_id);
                return (
                  <option
                    key={m.pessoa_id}
                    value={m.pessoa_id}
                    disabled={reason !== null}
                  >
                    {m.nome}
                    {reason ? ` — ${reason}` : ""}
                  </option>
                );
              })}
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
            <DsButton variant="tertiary" onClick={onClose} disabled={busy}>
              Cancelar
            </DsButton>
            <DsButton type="submit" loading={busy}>
              <Icon name="send" />
              <span>{busy ? "Enviando…" : "Enviar solicitação"}</span>
            </DsButton>
          </div>
        </form>
      </>
    </DsDialog>
  );
}
