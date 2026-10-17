"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { upsertConsolidation } from "@/lib/consolidacao-store";
import { useAuth } from "@/lib/auth-context";
import { SessionExpiredError } from "@/lib/api";
import { ApiError, fetchTeamLookup, type TeamLookupMember } from "@/lib/dashboard-api";
import { answerInvitation, assignConsolidador, canConsolidate, fetchAssignments, type AssignmentTrack } from "@/lib/consolidacao-api";

const labels = { atribuida: "Aguardando aceite", aceita: "Aceito", recusada: "Recusado — coordenação", expirada: "Expirado — coordenação", substituida: "Substituído" };

/** Live state survives reload; deadlines and recipient authority are decided by the server. */
type AssignmentPanelProps = { team?: TeamLookupMember[]; onChanged?: () => void };

export function AssignmentPanel(props: AssignmentPanelProps = {}) {
  const { token, user } = useAuth();
  // Remount private state on identity/session change; an old request cannot populate a new session.
  return <AssignmentPanelContent key={`${token ?? ""}:${user?.appUserId ?? ""}`} {...props} />;
}

function AssignmentPanelContent({ team, onChanged }: AssignmentPanelProps) {
  const { token, user, expireSession } = useAuth();
  const generation = useRef(0);
  const [rows, setRows] = useState<AssignmentTrack[]>([]);
  const [members, setMembers] = useState<TeamLookupMember[]>([]);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const coordinator = canConsolidate(user?.roles ?? []);
  const handleError = useCallback((err: unknown) => {
    if (err instanceof SessionExpiredError) expireSession();
    else setError(err instanceof ApiError ? err.message : "Não foi possível atualizar os convites.");
  }, [expireSession]);
  const load = useCallback(async (offset = 0) => {
    if (!token) return;
    const request = ++generation.current;
    setBusy(true);
    setError(null);
    try {
      const page = await fetchAssignments(token, offset);
      if (request !== generation.current) return;
      for (const track of page) upsertConsolidation({
        pessoaId: track.pessoaId, consolidacaoId: track.id, responsavelId: track.responsavelId,
        prazoConexao: track.prazoConexao, vinculo: track.prazoConexao ? "visitante" : "celula",
        confirmedStages: track.etapasConfirmadas, concluida: false,
      });
      setRows(current => offset ? [...current, ...page] : page);
      setHasMore(page.length === 50);
    } catch (err) { if (request === generation.current) handleError(err); }
    finally { if (request === generation.current) setBusy(false); }
  }, [token, handleError]);
  useEffect(() => { void load(); return () => { generation.current += 1; }; }, [load]);
  useEffect(() => {
    let active = true;
    if (token && coordinator && team === undefined) void fetchTeamLookup(token).then(page => {
      if (active) setMembers(page.items.filter(member => member.pessoaId && member.tiposFila.includes("fonovisita")));
    }).catch(err => { if (active) handleError(err); });
    return () => { active = false; };
  }, [token, coordinator, handleError, team]);
  async function act(row: AssignmentTrack, accept?: boolean) {
    if (!token || busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      if (accept !== undefined && row.convite) {
        const result = await answerInvitation(token, row.convite, accept);
        setNotice(result.status === "expirada" ? "O prazo de aceite expirou. A coordenação deve indicar um responsável." : accept ? "Convite aceito. Você é o responsável efetivo." : "Convite recusado. A coordenação foi sinalizada no painel.");
      } else {
        const targetId = selected[row.id];
        if (!targetId) return;
        await assignConsolidador(token, row.id, targetId);
        setNotice("Convite registrado por 24 horas. O responsável efetivo só muda após o aceite.");
      }
      await load();
      onChanged?.();
    } catch (err) { handleError(err); }
    finally { setBusy(false); }
  }
  const eligibleMembers = (team ?? members).filter(member => member.pessoaId && member.tiposFila.includes("fonovisita"));
  const name = (id: string | null) => (team ?? members).find(member => member.usuarioId === id)?.nome ?? (id === user?.appUserId ? "Você" : id ? "Responsável atual" : "Sem responsável efetivo");
  return <section className="card" aria-label="Aceite da fonovisita">
    <div className="panel-title"><span>Aceite da fonovisita</span><button type="button" className="btn btn-sm" disabled={busy} onClick={() => void load()}>Atualizar convites</button></div>
    <p className="people-meta">O convite vale por 24 horas corridas. O prazo da fonovisita continua o mesmo. Recusa ou expiração volta à coordenação.</p>
    {error ? <p role="alert">{error}</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    {busy && rows.length === 0 ? <p role="status">Carregando convites…</p> : null}
    {!busy && !error && rows.length === 0 ? <p>Nenhuma consolidação disponível para aceite.</p> : null}
    <div className="queue">{rows.map(row => <div className="qitem" key={row.id}>
      <div className="qbody">
        <strong>{row.pessoaNome}</strong>
        <p>{name(row.responsavelId)}</p>
        {row.convite ? <p>{labels[row.convite.status]} · Candidato: {name(row.convite.responsavelId)} · Prazo de aceite: {new Date(row.convite.prazoAceite).toLocaleString("pt-BR")}</p> : <p>Sem convite novo · atribuição anterior preservada</p>}
        {row.convite?.status === "atribuida" && row.convite.responsavelId === user?.appUserId ? <div className="actions">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void act(row, true)}>Aceitar fonovisita de {row.pessoaNome}</button>
          <button type="button" className="btn" disabled={busy} onClick={() => void act(row, false)}>Recusar convite</button>
        </div> : null}
        {coordinator && eligibleMembers.length > 0 ? <div className="actions">
          <label>Convidar responsável para {row.pessoaNome}<select value={selected[row.id] ?? ""} disabled={busy} onChange={event => setSelected(current => ({ ...current, [row.id]: event.target.value }))}>
            <option value="">Selecione uma pessoa da equipe</option>
            {eligibleMembers.map(member => <option key={member.usuarioId} value={member.usuarioId}>{member.nome}</option>)}
          </select></label>
          <button type="button" className="btn btn-sm" disabled={busy || !selected[row.id]} onClick={() => void act(row)}>Registrar convite no painel</button>
        </div> : null}
      </div>
    </div>)}</div>
    {hasMore ? <button type="button" className="btn" disabled={busy} onClick={() => void load(rows.length)}>Carregar mais convites</button> : null}
  </section>;
}
