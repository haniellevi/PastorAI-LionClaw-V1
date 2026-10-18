"use client";

import { useCallback, useState } from "react";
import { PaginatedLookup } from "../lookups/PaginatedLookup";
import { DsButton } from "../ds/Button";
import { fetchCellLookupPage, fetchContactLookupPage, type CellLookup, type ContactLookup } from "@/lib/lookup-api";
import { createRequest, resubmitRequest, type CellRequest } from "@/lib/cell-requests-api";
import { ApiError } from "@/lib/dashboard-api";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

/** A solicitação nunca aplica a liderança; a Central decide pela web. */
export function NomeacaoForm({ token, cellId, request, onCreated }: {
  token: string; cellId?: string; request?: CellRequest; onCreated?: () => void;
}) {
  const { expireSession } = useAuth();
  const [cell, setCell] = useState<CellLookup | null>(null);
  const [candidate, setCandidate] = useState<ContactLookup | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const loadCells = useCallback((q: string, page: number, signal: AbortSignal) =>
    fetchCellLookupPage(token, { q, page, pageSize: 25, signal }), [token]);
  const loadPeople = useCallback((q: string, page: number, signal: AbortSignal) =>
    fetchContactLookupPage(token, { q, page, pageSize: 25, signal }), [token]);
  const target = cellId ?? request?.celula_id ?? cell?.id;
  return <form aria-label="Solicitar nomeação de líder" onSubmit={async e => {
    e.preventDefault();
    if (!target || !candidate || busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const payload = { novo_lider_id: candidate.id };
      if (request) await resubmitRequest(token, request.id, payload);
      else await createRequest(token, { celula_id: target, tipo: "nomear_lider", payload_proposto: payload });
      setMessage("Solicitação enviada para aprovação pela Central.");
      setCandidate(null); onCreated?.();
    } catch (err) {
      if (err instanceof SessionExpiredError) expireSession();
      else setError(err instanceof ApiError ? err.message : "Não foi possível enviar. Tente novamente.");
    } finally { setBusy(false); }
  }}>
    <h3>{request ? "Ajustar nomeação" : "Solicitar nomeação de líder"}</h3>
    <p>A Central aprova a versão apresentada e executa a nomeação imediatamente após confirmação. Autor e candidato não podem decidir.</p>
    {!cellId && !request ? <PaginatedLookup label="Célula alvo" inputId="nomeacao-celula" loadPage={loadCells}
      selected={cell} onSelect={setCell} getLabel={c => c.nome} onSessionExpired={expireSession} /> : null}
    <PaginatedLookup label="Candidato à liderança" inputId={`nomeacao-candidato-${request?.id ?? cellId ?? "enviar"}`} loadPage={loadPeople}
      selected={candidate} onSelect={setCandidate} getLabel={p => p.nome} onSessionExpired={expireSession} />
    <p>Aptidão vigente, acesso e conflitos serão revalidados na aprovação.</p>
    {error ? <p role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    <DsButton type="submit" disabled={!target || !candidate || busy} loading={busy}>{request ? "Reenviar nomeação" : "Enviar para aprovação"}</DsButton>
  </form>;
}
