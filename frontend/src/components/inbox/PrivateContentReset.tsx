"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Dialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import { SessionExpiredError } from "@/lib/api";
import { authedFetch, clearAuthedResponseCache } from "@/lib/dashboard-api";
import { readDeletionReceipt, type PrivateDeletionReceipt } from "@/lib/conversations-api";

const CONFIRMATION = "EXCLUIR CONTEUDO PRIVADO";

/** Keep mounted/keyed by person and session so an ambiguous retry retains its operation. */
export function PrivateContentReset({ open, token, personId, personName, onClose, onErased, expireSession }: {
  open: boolean; token: string; personId: string; personName: string;
  onClose: () => void; onErased: () => void; expireSession: () => void;
}) {
  const inputId = useId();
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [operationId] = useState(() => crypto.randomUUID());
  const [confirmation, setConfirmation] = useState("");
  const [receipt, setReceipt] = useState<PrivateDeletionReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (inFlight.current || (!receipt && confirmation !== CONFIRMATION)) return;
    inFlight.current = true; setBusy(true); setError(null);
    try {
      const response = await authedFetch(token, receipt
        ? `/igreja/private-deletions/${receipt.id}` : `/contacts/${personId}/private-content`, receipt
        ? { cache: "no-store" }
        : { method: "DELETE", body: JSON.stringify({ operation_id: operationId, confirmacao: confirmation }) });
      if (!mounted.current) return;
      if (!response.ok) throw new Error("request_failed");
      const result = readDeletionReceipt(await response.json());
      if (!mounted.current) return;
      setReceipt(result);
      if (!receipt) { clearAuthedResponseCache(); onErased(); }
    } catch (cause) {
      if (!mounted.current) return;
      if (cause instanceof SessionExpiredError) expireSession();
      else setError(receipt
        ? "Não foi possível atualizar o recibo. Tente novamente."
        : "Não foi possível confirmar o resultado. Tente novamente com esta mesma operação; a repetição é segura.");
    } finally { inFlight.current = false; setBusy(false); }
  }

  return <Dialog open={open} onClose={() => { if (!inFlight.current) onClose(); }} title="Excluir conteúdo privado da pessoa"
    footer={<>
      <Button disabled={busy} onClick={onClose}>{receipt ? "Fechar" : "Cancelar"}</Button>
      <Button variant={receipt ? "default" : "danger"} loading={busy}
        disabled={busy || (!receipt && confirmation !== CONFIRMATION)} onClick={() => void submit()}>
        {receipt ? "Atualizar recibo" : "Confirmar exclusão"}
      </Button>
    </>}>
    <p>Pessoa: <strong>{personName}</strong>.</p>
    {receipt ? <section aria-label="Recibo de exclusão privada">
      <div role="status">
        <p>{receipt.estado === "concluido" ? "Exclusão concluída no alcance operacional."
          : receipt.estado === "pendente_envio" ? "Envio em andamento: exclusão pendente." : "Limpeza externa pendente."}</p>
        <p>Recibo: {receipt.id}</p>
      </div>
      <ul>{Object.entries(receipt.camadas).map(([layer, counts]) => <li key={layer}>
        {layer}: {counts.apagadas} apagadas; {counts.pendentes} pendentes; {counts.falhas} falhas.
      </li>)}</ul>
    </section> : <>
      <p>Apaga todas as conversas, mídias, transcrições, resumos e demais derivados privados desta pessoa nesta igreja. Esta ação não pode ser desfeita.</p>
      <label htmlFor={inputId}>Digite {CONFIRMATION} para confirmar</label>
      <input id={inputId} value={confirmation} disabled={busy} autoComplete="off" onChange={event => setConfirmation(event.target.value)} />
    </>}
    <p>Cadastro, vínculos oficiais, opt-out e prova de consentimento sem conteúdo são preservados.</p>
    <p>Fora do alcance: backups, cópias do provedor e texto já enviado ao provedor.</p>
    {!receipt ? <p>Operação: {operationId}. Em caso de falha, mantenha esta tela para repetir a mesma operação.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
  </Dialog>;
}
