'use client';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { SessionExpiredError } from '@/lib/api';
import { getAvaliacao, postAvaliacao, type AvaliacaoPessoa, type DecisaoInput } from '@/lib/enviar-api';

export function AvaliacaoPanel({ pessoaId, token, onExpired, onSaved }: {
  pessoaId: string; token: string; onExpired: () => void; onSaved?: () => void | Promise<void>;
}) {
  const prefix = useId();
  const [data, setData] = useState<AvaliacaoPessoa | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [decisao, setDecisao] = useState<'apto' | 'nao_apto'>('nao_apto');
  const [motivo, setMotivo] = useState('');
  const [legado, setLegado] = useState(false);
  const [success, setSuccess] = useState(false);
  // Keep the exact id/content after uncertain transport; editing starts a new decision.
  const pending = useRef<DecisaoInput | null>(null);
  const reload = useCallback(async () => setData(await getAvaliacao(token, pessoaId)), [token, pessoaId]);
  useEffect(() => {
    let active = true;
    getAvaliacao(token, pessoaId).then(value => { if (active) setData(value); }).catch(err => {
      if (!active) return;
      if (err instanceof SessionExpiredError) onExpired();
      else setError(err instanceof Error ? err.message : 'Não foi possível carregar a avaliação.');
    });
    return () => { active = false; };
  }, [token, pessoaId, onExpired]);
  const blocked = data?.pendencias.situacao === 'bloqueado';
  const legacyNeeded = decisao === 'apto' && data?.pendencias.situacao !== 'apto_para_avaliacao';
  const canRecognize = data?.origem === 'legado' && data.apto_lider;
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || blocked || !motivo.trim() || (legacyNeeded && (!legado || !canRecognize))) return;
    const input: DecisaoInput = { id: '', decisao, motivo: motivo.trim(), origem: legacyNeeded ? 'legado' : 'avaliacao' };
    if (!pending.current || pending.current.decisao !== input.decisao || pending.current.motivo !== input.motivo || pending.current.origem !== input.origem) {
      pending.current = { ...input, id: crypto.randomUUID() };
    }
    setBusy(true); setError(null); setSuccess(false);
    try {
      await postAvaliacao(token, pessoaId, pending.current);
      pending.current = null; setMotivo(''); setLegado(false); setSuccess(true);
      await reload();
      await onSaved?.();
    } catch (err) {
      if (err instanceof SessionExpiredError) onExpired();
      else setError(err instanceof Error ? err.message : 'Não foi possível registrar a avaliação.');
    } finally { setBusy(false); }
  }
  return <section className="card card-pad" aria-label="Avaliação de aptidão à liderança">
    <h3>Avaliação de aptidão à liderança</h3>
    {error ? <p role="alert">{error}</p> : null}
    {success ? <p role="status">Decisão registrada. A liderança atual foi preservada.</p> : null}
    {!data && !error ? <p role="status">Carregando avaliação…</p> : null}
    {data ? <>
      <p>{blocked ? 'Aptidão para novas nomeações: bloqueada.' : data.apto_lider ? 'Aptidão registrada: apto.' : 'Aptidão registrada: não apto.'} {data.pendencias.aviso_legado}</p>
      {data.revisao_pastoral_pendente ? <p role="note">Revisão pastoral pendente: há decisão negativa ou evidência revogada. A liderança atual permanece até decisão pastoral; novas nomeações estão bloqueadas.</p> : null}
      <p>Regras: {data.pendencias.status_regras}. Aptidão não nomeia líder.</p>
      <ul>{data.pendencias.pendencias.map(p => <li key={p.criterio}>{p.descricao}</li>)}</ul>
      {blocked ? <p>Avaliação bloqueada: confira os impedimentos e as evidências revogadas acima.</p> : <form onSubmit={event => void submit(event)}>
        <fieldset disabled={busy}>
          <legend>Decisão da coordenação</legend>
          <div className="field"><label htmlFor={`${prefix}-decisao`}>Decisão</label>
            <select id={`${prefix}-decisao`} value={decisao} onChange={e => setDecisao(e.target.value as typeof decisao)}>
              <option value="nao_apto">Não apto</option>
              <option value="apto" disabled={data.pendencias.situacao !== 'apto_para_avaliacao' && !canRecognize}>Apto</option>
            </select></div>
          {legacyNeeded && canRecognize ? <label className="check-row"><input type="checkbox" required checked={legado} onChange={e => setLegado(e.target.checked)} /> Reconheço explicitamente a aptidão legada; descrevi o fundamento no motivo.</label> : null}
          <div className="field"><label htmlFor={`${prefix}-motivo`}>Motivo obrigatório</label>
            <textarea id={`${prefix}-motivo`} required maxLength={300} value={motivo} onChange={e => setMotivo(e.target.value)} /></div>
          <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Registrando…' : 'Registrar decisão'}</button>
        </fieldset>
      </form>}
      <details><summary>Histórico de decisões ({data.avaliacoes.length})</summary>
        {data.avaliacoes.length === 0 ? <p>Nenhuma avaliação registrada. O legado não comprova formação.</p> : <ol>{data.avaliacoes.map(row => <li key={row.id}>
          <p><strong>{row.decisao === 'apto' ? 'Apto' : 'Não apto'}</strong> · {row.origem} · {new Date(row.criada_em).toLocaleString('pt-BR')}</p>
          <p>{row.motivo}</p><p>Responsável: {row.autor_id} · Regras: {row.versao_regras}</p>
          <ul>{Object.entries(row.evidencias).map(([criterion, evidence]) => <li key={criterion}>{criterion.toUpperCase()}: {evidence.estado}{evidence.referencia ? ` · ${evidence.referencia}` : ''}</li>)}</ul>
        </li>)}</ol>}
      </details>
    </> : null}
  </section>;
}
