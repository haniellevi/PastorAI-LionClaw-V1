"use client";

import { useCallback, useState } from "react";
import { PaginatedLookup } from "../lookups/PaginatedLookup";
import { DsButton } from "../ds/Button";
import { fetchContactLookupPage, type ContactLookup } from "@/lib/lookup-api";
import { createRequest, resubmitRequest, type CellRequest } from "@/lib/cell-requests-api";
import { ApiError } from "@/lib/dashboard-api";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export function AberturaForm({ token, request, onCreated }: {
  token: string; request?: CellRequest; onCreated?: () => void;
}) {
  const { expireSession } = useAuth();
  const [nome, setNome] = useState(String(request?.payload_proposto.nome ?? ""));
  const [cobertura, setCobertura] = useState(String(request?.payload_proposto.cobertura_espiritual ?? ""));
  const [candidate, setCandidate] = useState<ContactLookup | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const loadPeople = useCallback((q: string, page: number, signal: AbortSignal) =>
    fetchContactLookupPage(token, { q, page, pageSize: 25, signal }), [token]);
  return <form aria-label="Solicitar abertura de célula" onSubmit={async e => {
    e.preventDefault();
    if (!nome.trim() || !cobertura.trim() || !candidate || busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const payload = { ...request?.payload_proposto, nome: nome.trim(), cobertura_espiritual: cobertura.trim(), novo_lider_id: candidate.id };
      if (request) await resubmitRequest(token, request.id, payload);
      else await createRequest(token, { tipo: "abrir_celula", payload_proposto: payload });
      setMessage("Solicitação de abertura enviada para aprovação pela Central.");
      setCandidate(null); onCreated?.();
    } catch (err) {
      if (err instanceof SessionExpiredError) expireSession();
      else setError(err instanceof ApiError ? err.message : "Não foi possível enviar. Tente novamente.");
    } finally { setBusy(false); }
  }}>
    <h3>{request ? "Ajustar abertura de célula" : "Solicitar abertura de célula"}</h3>
    <p>Abertura sem célula de origem. A Central cria a célula e nomeia o líder imediatamente ao aprovar com confirmação. Autor e candidato não podem decidir.</p>
    <label>Nome da célula<input required maxLength={200} value={nome} onChange={e => setNome(e.target.value)} /></label>
    <label>Cobertura espiritual<input required maxLength={200} value={cobertura} onChange={e => setCobertura(e.target.value)} /></label>
    <PaginatedLookup label="Candidato à liderança" inputId={`abertura-candidato-${request?.id ?? "enviar"}`} loadPage={loadPeople}
      selected={candidate} onSelect={setCandidate} getLabel={p => p.nome} onSessionExpired={expireSession} />
    <p>Aptidão vigente, acesso e conflitos serão revalidados na aprovação.</p>
    {error ? <p role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
    <DsButton type="submit" disabled={!nome.trim() || !cobertura.trim() || !candidate || busy} loading={busy}>{request ? "Reenviar abertura" : "Enviar abertura para aprovação"}</DsButton>
  </form>;
}
