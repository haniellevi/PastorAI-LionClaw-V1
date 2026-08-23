"use client";

import { useMemo, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  removeCellMember,
  transferCellMember,
  type CellSummary,
} from "@/lib/cells-api";
import type { Contact } from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";

interface Props {
  /** Célula de origem (de onde a pessoa sai). */
  origem: CellSummary;
  /** Pessoa a transferir/remover (já vinculada ativa à origem). */
  pessoa: Contact;
  /** Células disponíveis como destino (transferência). Exclui a origem. */
  cells: CellSummary[];
  /** Modo do modal. */
  mode: "transferir" | "remover";
  onClose: () => void;
  onDone: () => void;
}

/**
 * Modal da Central para transferir ou remover um membro de uma célula
 * (Células pós-V1). Execução direta — sem fluxo de solicitação.
 *
 * - ``transferir``: escolhe a célula de destino (ativa, com líder, ≠ origem) e
 *   um motivo opcional. Chama ``transferCellMember``.
 * - ``remover``: confirma a remoção com um motivo opcional. Chama
 *   ``removeCellMember``. A pessoa NÃO é deletada — só perde o vínculo.
 *
 * Erros do backend (403/404/409) aparecem inline como banner. Sessão expirada
 * dispara ``expireSession`` do ``AuthContext``.
 */
export function TransferRemoveMemberModal({
  origem,
  pessoa,
  cells,
  mode,
  onClose,
  onDone,
}: Props) {
  const { token, expireSession } = useAuth();
  const [destinoId, setDestinoId] = useState<string | null>(null);
  const [motivo, setMotivo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  // Destinos elegíveis: ativos, com líder, ≠ origem. Não filtra por elegibilidade
  // da pessoa no destino (o backend valida e devolve 409 legível).
  const destinos = useMemo(
    () =>
      cells.filter(
        (c) =>
          c.id !== origem.id &&
          c.ativo &&
          c.liderId,
      ),
    [cells, origem.id],
  );

  const selectedDestino = destinos.find((c) => c.id === destinoId) ?? null;

  async function submit() {
    if (!token || sending) return;
    if (mode === "transferir" && !selectedDestino) return;
    setSending(true);
    setError(null);
    try {
      if (mode === "transferir" && selectedDestino) {
        await transferCellMember(
          token,
          origem.id,
          pessoa.id,
          selectedDestino.id,
          motivo.trim() || undefined,
        );
        setSuccess(
          `${pessoa.nome} foi transferida para "${selectedDestino.nome}".`,
        );
      } else {
        await removeCellMember(token, origem.id, pessoa.id, motivo.trim() || undefined);
        setSuccess(`${pessoa.nome} foi removida da célula "${origem.nome}".`);
      }
      onDone();
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setError(
        err instanceof ApiError
          ? err.message
          : mode === "transferir"
            ? "Não foi possível transferir o membro."
            : "Não foi possível remover o membro.",
      );
    } finally {
      setSending(false);
    }
  }

  const title =
    mode === "transferir"
      ? `Transferir membro · ${origem.nome}`
      : `Remover membro · ${origem.nome}`;

  const submitLabel =
    mode === "transferir"
      ? sending
        ? "Transferindo…"
        : "Transferir"
      : sending
        ? "Removendo…"
        : "Remover";

  return (
    <DsDialog
      open
      onClose={() => {
        if (!sending) onClose();
      }}
      title={title}
    >
      {success ? (
        <div className="modal-form">
          <DsBanner kind="info">{success}</DsBanner>
          <div className="modal-foot">
            <DsButton variant="primary" onClick={onClose}>
              Concluir
            </DsButton>
          </div>
        </div>
      ) : (
        <form
          className="modal-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          {error ? (
            <div className="error-banner" role="alert">
              <Icon name="alert" />
              <span>{error}</span>
            </div>
          ) : null}

          <p className="sub" style={{ color: "var(--muted)" }}>
            {mode === "transferir" ? (
              <>
                Transfere <strong>{pessoa.nome}</strong> de{" "}
                <strong>{origem.nome}</strong> para outra célula ativa. A
                operação é direta e auditada.
              </>
            ) : (
              <>
                Remove <strong>{pessoa.nome}</strong> da célula{" "}
                <strong>{origem.nome}</strong>. A pessoa não é deletada — só
                perde o vínculo com a célula. A operação é direta e auditada.
              </>
            )}
          </p>

          {mode === "transferir" ? (
            <div className="field">
              <label htmlFor="transferDestino">Célula de destino</label>
              {destinos.length === 0 ? (
                <p className="sub" style={{ color: "var(--muted)" }}>
                  Nenhuma célula ativa com líder disponível como destino.
                </p>
              ) : (
                <div
                  style={{
                    maxHeight: 220,
                    overflowY: "auto",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--r-md)",
                    marginTop: 6,
                  }}
                >
                  {destinos.map((c) => {
                    const isSelected = destinoId === c.id;
                    return (
                      <button
                        type="button"
                        key={c.id}
                        onClick={() => {
                          setDestinoId(c.id);
                          setError(null);
                        }}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          gap: 8,
                          width: "100%",
                          minHeight: 44,
                          textAlign: "left",
                          padding: "8px 12px",
                          background: isSelected
                            ? "var(--accent-soft)"
                            : "transparent",
                          border: "none",
                          borderBottom: "1px solid var(--border)",
                          cursor: "pointer",
                          font: "inherit",
                          color: "inherit",
                        }}
                      >
                        <span style={{ minWidth: 0 }}>
                          <span className="nm">{c.nome}</span>
                        </span>
                        {isSelected ? (
                          <StatusPill tone="accent">Selecionada</StatusPill>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="memberMotivo">
              Motivo <span className="sub">(opcional)</span>
            </label>
            <textarea
              id="memberMotivo"
              value={motivo}
              onChange={(event) => setMotivo(event.target.value)}
              placeholder={
                mode === "transferir"
                  ? "Ex.: mudou de bairro, pedido do líder…"
                  : "Ex.: pediu para sair, mudou de igreja…"
              }
              maxLength={1000}
              rows={3}
              disabled={sending}
            />
          </div>

          <div className="modal-foot">
            <DsButton
              variant="secondary"
              type="button"
              onClick={onClose}
              disabled={sending}
            >
              Cancelar
            </DsButton>
            <DsButton
              variant="primary"
              type="submit"
              disabled={
                sending || (mode === "transferir" && !selectedDestino)
              }
              aria-busy={sending || undefined}
            >
              {submitLabel}
            </DsButton>
          </div>
        </form>
      )}
    </DsDialog>
  );
}
