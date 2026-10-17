"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { SessionExpiredError } from "@/lib/api";
import { Dialog } from "@/components/ds/Dialog";
import { confirmVisitCell, readVisitSuggestions, type VisitCellPage, type VisitCellSuggestion } from "@/lib/visit-cell-api";

export function VisitCellSuggestions({ personId, onConfirmed }: { personId?: string; onConfirmed?: () => void }) {
  const { token, user, expireSession } = useAuth();
  const allowed = user?.roles.some(r => r === "admin" || r === "pastor");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<VisitCellPage | null>(null);
  const [selected, setSelected] = useState<VisitCellSuggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setResult(null); setSelected(null); setError(null); setSuccess(false);
    if (!token || !allowed) return;
    void readVisitSuggestions(token, personId, page).then(data => { if (active) setResult(data); }).catch(err => {
      if (!active) return;
      if (err instanceof SessionExpiredError) expireSession();
      else setError(err instanceof Error ? err.message : "Não foi possível carregar as sugestões.");
    });
    return () => { active = false; };
  }, [token, allowed, personId, page, reload, expireSession]);
  if (!allowed || !token) return null;
  async function confirm() {
    if (!selected || !token || busy) return;
    setBusy(true); setError(null);
    try {
      await confirmVisitCell(token, selected);
      setResult(prev => prev ? {...prev, items: prev.items.map(item => item.pessoa_id === selected.pessoa_id ? {...item, already_linked: true} : item)} : prev);
      setSelected(null); setSuccess(true); onConfirmed?.();
    } catch (err) {
      if (err instanceof SessionExpiredError) expireSession();
      else setError(err instanceof Error ? err.message : "Não foi possível confirmar o vínculo.");
    } finally { setBusy(false); }
  }
  return <section className="card card-pad" aria-label="Sugestões de vínculo por visita">
    <h3>Sugestões de vínculo por visita</h3>
    {error ? <div role="alert"><p>{error}</p><button type="button" disabled={busy} onClick={() => setReload(n => n + 1)}>Atualizar sugestões</button></div> : null}
    {success ? <p role="status">Vínculo confirmado. Pendências de conexão encerradas.</p> : null}
    {!result && !error ? <p role="status">Carregando sugestões…</p> : null}
    {result?.items.length === 0 ? <p>Nenhuma visita comprovada para sugerir vínculo.</p> : null}
    {result?.items.map(item => <article key={item.pessoa_id}>
      <p><strong>{item.pessoa_nome}</strong> · {item.celula_nome ?? "Célula indisponível"}</p>
      <p>Primeira visita comprovada: {new Date(item.data_ocorrencia).toLocaleDateString("pt-BR")}. {item.already_linked ? "Vínculo já confirmado." : "Sugestão pendente de confirmação."}</p>
      {item.blocked_reason ? <p>{item.blocked_reason}</p> : null}
      <button type="button" className="btn" disabled={busy || !!item.blocked_reason || item.already_linked} onClick={() => {setSelected(item); setError(null); setSuccess(false);}}>Revisar vínculo</button>
    </article>)}
    {!personId && result ? <nav aria-label="Páginas das sugestões"><button type="button" disabled={busy || page <= 1} onClick={() => setPage(p => p - 1)}>Anterior</button><span> Página {page} </span><button type="button" disabled={busy || page * result.page_size >= result.total} onClick={() => setPage(p => p + 1)}>Próxima</button></nav> : null}
    {selected ? <Dialog open title="Confirmar vínculo" onClose={() => {if (!busy) setSelected(null);}}>
      <p>Vincular {selected.pessoa_nome} à célula {selected.celula_nome}, conforme a primeira visita comprovada?</p>
      <p>Ao confirmar, o acompanhamento será marcado como consolidado.</p>
      {error ? <p role="alert">{error}</p> : null}
      <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void confirm()}>Confirmar vínculo</button>
      <button type="button" className="btn" disabled={busy} onClick={() => setSelected(null)}>Cancelar</button>
    </Dialog> : null}
  </section>;
}
