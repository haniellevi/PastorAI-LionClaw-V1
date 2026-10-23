"use client";

import { useId, useRef, useState } from "react";
import { Dialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import { SessionExpiredError } from "@/lib/api";
import { authedFetch, clearAuthedResponseCache } from "@/lib/dashboard-api";
import { readDeletionReceipt, type PrivateDeletionReceipt } from "@/lib/conversations-api";

const CONFIRMATION = "EXCLUIR CONTEUDO PRIVADO DA IGREJA";

function newOperationId(): string {
  return crypto.randomUUID();
}

export function PrivateChurchContentReset({ open, token, churchName, onClose, onErased, onSessionError }: {
  open: boolean;
  token: string;
  churchName: string;
  onClose: () => void;
  onErased: () => void;
  onSessionError: (error: unknown) => unknown;
}) {
  const churchNameId = useId();
  const confirmationId = useId();
  const [operationId, setOperationId] = useState(newOperationId);
  const [typedChurchName, setTypedChurchName] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [receipt, setReceipt] = useState<PrivateDeletionReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (inFlight.current || (!receipt && (typedChurchName !== churchName || confirmation !== CONFIRMATION))) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await authedFetch(token, receipt
        ? `/igreja/private-deletions/${receipt.id}`
        : "/igreja/private-content", receipt
        ? { cache: "no-store" }
        : {
            method: "DELETE",
            body: JSON.stringify({ operation_id: operationId, nome_igreja: typedChurchName, confirmacao: confirmation }),
          });
      if (!response.ok) throw new Error("request_failed");
      const result = readDeletionReceipt(await response.json());
      setReceipt(result);
      if (!receipt) {
        clearAuthedResponseCache();
        onErased();
      }
    } catch (cause) {
      if (cause instanceof SessionExpiredError) onSessionError(cause);
      else setError(receipt
        ? "Não foi possível atualizar o recibo. Tente novamente."
        : "Não foi possível confirmar o resultado. Mantenha esta operação e tente novamente; a repetição é segura.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  function startNewOperation() {
    if (busy) return;
    setOperationId(newOperationId());
    setTypedChurchName("");
    setConfirmation("");
    setReceipt(null);
    setError(null);
  }

  return <Dialog open={open} onClose={() => { if (!inFlight.current) onClose(); }} title="Resetar conteúdo privado da igreja"
    footer={<>
      <Button disabled={busy} onClick={onClose}>Fechar</Button>
      {receipt ? <>
        <Button disabled={busy} onClick={() => void submit()}>Atualizar recibo</Button>
        <Button variant="danger" disabled={busy} onClick={startNewOperation}>Iniciar novo reset</Button>
      </> : <Button variant="danger" loading={busy}
        disabled={busy || typedChurchName !== churchName || confirmation !== CONFIRMATION}
        onClick={() => void submit()}>
        Confirmar reset privado
      </Button>}
    </>}>
    {receipt ? <section aria-label="Recibo cumulativo de exclusão privada">
      <div role="status">
        <p>{receipt.estado === "concluido" ? "Exclusão concluída no alcance operacional."
          : receipt.estado === "pendente_envio" ? "Envio em andamento: exclusão pendente." : "Limpeza externa pendente."}</p>
        <p>Recibo cumulativo: {receipt.id}</p>
      </div>
      <ul>{Object.entries(receipt.camadas).map(([layer, counts]) => <li key={layer}>
        {layer}: {counts.apagadas} apagadas; {counts.pendentes} pendentes; {counts.falhas} falhas.
      </li>)}</ul>
    </section> : <>
      <p>Apaga as conversas, mídias, transcrições, resumos e demais derivados privados de toda a igreja. A operação usa a fila de exclusão e gera um recibo cumulativo. Esta ação é irreversível.</p>
      <label htmlFor={churchNameId}>Digite o nome exato da igreja: <strong>{churchName}</strong></label>
      <input id={churchNameId} value={typedChurchName} disabled={busy} autoComplete="off"
        onChange={event => setTypedChurchName(event.target.value)} />
      <label htmlFor={confirmationId}>Digite {CONFIRMATION} para confirmar</label>
      <input id={confirmationId} value={confirmation} disabled={busy} autoComplete="off"
        onChange={event => setConfirmation(event.target.value)} />
      <p>Cadastros, vínculos oficiais, opt-out, consentimentos e ledger de consentimento são preservados.</p>
      <p>Fora do alcance: backups, cópias do provedor e texto já enviado ao provedor.</p>
      <p>Operação: {operationId}. Em caso de falha ambígua, mantenha esta operação para repetir o mesmo identificador.</p>
    </>}
    {error ? <p role="alert">{error}</p> : null}
  </Dialog>;
}
