"use client";

import '@/components/config/administration-ux-v2.css';
import './responsabilidades.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { SessionExpiredError } from '@/lib/api';
import { ApiError } from '@/lib/dashboard-api';
import { fetchContactDetail } from '@/lib/contacts-api';
import { fetchContactLookupPage, type ContactLookup } from '@/lib/lookup-api';
import { PaginatedLookup } from '@/components/lookups/PaginatedLookup';
import { atribuirResponsabilidade, encerrarResponsabilidade, hojeSaoPaulo, listarResponsabilidades, PAGE_SIZE, SETORES, vigencia, type Responsabilidade, type Setor } from '@/lib/responsabilidades-api';

const dateLabel = (date: string) => date.split('-').reverse().join('/');
function PessoaNome({ token, id, onExpired }: { token: string; id: string; onExpired: () => void }) {
  const [nome, setNome] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setNome(null);
    void fetchContactDetail(token, id).then(pessoa => { if (current) setNome(pessoa.nome); }).catch(error => {
      if (current && error instanceof SessionExpiredError) onExpired();
    });
    return () => { current = false; };
  }, [token, id, onExpired]);
  return <p>{nome ?? `Pessoa: ${id}`}</p>;
}

export function ResponsabilidadesScreen() {
  const { token, user, expireSession } = useAuth();
  const allowed = user?.roles.some(role => role === 'admin' || role === 'pastor') ?? false;
  const [denied, setDenied] = useState(false);
  const [setor, setSetor] = useState<Setor | ''>('');
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [rows, setRows] = useState<Responsabilidade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState<'atribuir' | Responsabilidade | null>(null);
  const [pessoa, setPessoa] = useState<ContactLookup | null>(null);
  const [novoSetor, setNovoSetor] = useState<Setor>('atendimento');
  const [inicio, setInicio] = useState('');
  const [fim, setFim] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const formHeading = useRef<HTMLHeadingElement>(null);
  const newButton = useRef<HTMLButtonElement>(null);
  const hoje = hojeSaoPaulo();
  const loadPessoas = useCallback((q: string, page: number, signal: AbortSignal) =>
    fetchContactLookupPage(token!, { q, page, pageSize: 25, signal }), [token]);

  useEffect(() => {
    if (!token || !allowed) return;
    const controller = new AbortController();
    setLoading(true); setError(''); setRows([]);
    void listarResponsabilidades(token, { setor, offset }, controller.signal).then(result => {
      if (!controller.signal.aborted) setRows(result);
    }).catch(err => {
      if (controller.signal.aborted) return;
      if (err instanceof SessionExpiredError) { expireSession(); return; }
      if (err instanceof ApiError && err.status === 403) { setDenied(true); setForm(null); }
      setError(err instanceof Error ? err.message : 'Não foi possível carregar responsabilidades.');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, allowed, setor, offset, reload, expireSession]);
  useEffect(() => { if (form) formHeading.current?.focus(); }, [form]);

  function open(value: 'atribuir' | Responsabilidade) {
    setForm(value); setFormError(''); setNotice(''); setPessoa(null);
    setInicio(hoje); setFim(''); setNovoSetor(setor || 'atendimento');
  }
  function close() { setForm(null); newButton.current?.focus(); }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token || !form || saving) return;
    if (form === 'atribuir' && (!pessoa || pessoa.arquivada)) { setFormError('Selecione uma Pessoa ativa.'); return; }
    setSaving(true); setFormError('');
    try {
      if (form === 'atribuir') {
        await atribuirResponsabilidade(token, { pessoa_id: pessoa!.id, setor: novoSetor, inicio, fim: fim || null });
        setNotice('Atribuição registrada.');
      } else {
        await encerrarResponsabilidade(token, form.id, fim);
        setNotice('Encerramento registrado. O histórico foi preservado.');
      }
      close(); setOffset(0); setReload(value => value + 1);
    } catch (err) {
      if (err instanceof SessionExpiredError) { expireSession(); return; }
      if (err instanceof ApiError && err.status === 403) { setDenied(true); setForm(null); }
      setFormError(err instanceof Error ? err.message : 'Não foi possível salvar.');
    } finally { setSaving(false); }
  }
  if (!allowed || denied) return <div className="screen"><h1>Responsabilidades</h1><p role="alert">Acesso restrito a admin ou pastor.</p></div>;
  const ending = form && form !== 'atribuir' ? form : null;
  const minEnd = ending ? [hoje, nextDay(ending.inicio)].sort().at(-1) : inicio ? nextDay(inicio) : undefined;
  return <div className="screen administration-ux responsabilidades">
    <div className="screen-head"><div className="titles"><h1>Responsabilidades</h1><p>Responsáveis por setor, com vigência e histórico. A atribuição não concede acesso nem altera papéis.</p></div>
      <button ref={newButton} className="btn btn-primary" disabled={saving} onClick={() => open('atribuir')}>Nova atribuição</button></div>
    <p id="vigencia-ajuda">O fim é o primeiro dia sem responsabilidade. As datas seguem America/Sao_Paulo.</p>
    {notice && <p role="status">{notice}</p>}
    {form && <section className="card card-pad" aria-labelledby="responsabilidade-form-title">
      <h2 id="responsabilidade-form-title" ref={formHeading} tabIndex={-1}>{ending ? `Encerrar · ${SETORES[ending.setor]}` : 'Atribuir responsabilidade'}</h2>
      <form onSubmit={submit} aria-busy={saving} aria-describedby="responsabilidade-form-error vigencia-ajuda">
        <fieldset disabled={saving}>
          <legend className="sr-only">{ending ? 'Confirmar encerramento' : 'Dados da atribuição'}</legend>
          {!ending && <>
            <PaginatedLookup loadPage={loadPessoas} selected={pessoa} onSelect={setPessoa} label="Pessoa ativa (obrigatório)" inputId="responsabilidade-pessoa" getLabel={p => p.nome} isDisabled={p => !!p.arquivada} onSessionExpired={expireSession} />
            <div className="field"><label htmlFor="atribuir-setor">Setor</label><select id="atribuir-setor" value={novoSetor} onChange={e => setNovoSetor(e.target.value as Setor)}>{Object.entries(SETORES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
            <div className="field"><label htmlFor="atribuir-inicio">Início</label><input id="atribuir-inicio" type="date" required value={inicio} onChange={e => setInicio(e.target.value)} /></div>
          </>}
          {ending && <p>Confirme o fim de {dateLabel(ending.inicio)}{ending.fim ? ` até ${dateLabel(ending.fim)} (exclusivo)` : ' em diante'}. O registro será mantido no histórico.</p>}
          <div className="field"><label htmlFor={ending ? 'encerrar-fim' : 'atribuir-fim'}>Fim {ending ? '(confirmar encerramento)' : '(opcional)'}</label><input id={ending ? 'encerrar-fim' : 'atribuir-fim'} type="date" required={!!ending} min={minEnd} max={ending?.fim ?? undefined} value={fim} onChange={e => setFim(e.target.value)} aria-describedby="vigencia-ajuda responsabilidade-form-error" /></div>
          <p id="responsabilidade-form-error" role={formError ? 'alert' : undefined}>{formError}</p>
          <div className="responsabilidades-actions"><button className="btn btn-primary" type="submit">{saving ? 'Salvando…' : ending ? 'Confirmar encerramento' : 'Atribuir'}</button><button className="btn" type="button" onClick={close}>Cancelar</button></div>
        </fieldset>
      </form>
    </section>}
    <section aria-labelledby="historico-title" aria-busy={loading}>
      <h2 id="historico-title">Vigência e histórico</h2>
      <div className="field"><label htmlFor="filtro-setor">Filtrar por setor</label><select id="filtro-setor" value={setor} disabled={saving} onChange={e => { setSetor(e.target.value as Setor | ''); setOffset(0); }}>{<option value="">Todos os setores</option>}{Object.entries(SETORES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
      {loading ? <p role="status">Carregando responsabilidades…</p> : error ? <div role="alert">{error} <button className="btn" onClick={() => setReload(v => v + 1)}>Tentar novamente</button></div> : <>
        {rows.length === 0 && <p>Nenhuma responsabilidade encontrada neste filtro.</p>}
        {rows.slice(0, PAGE_SIZE).map(row => <article className="card card-pad" key={row.id}>
          <h3>{SETORES[row.setor]}</h3>
          <PessoaNome token={token!} id={row.pessoa_id} onExpired={expireSession} />
          <p>{dateLabel(row.inicio)} → {row.fim ? `${dateLabel(row.fim)} (exclusivo)` : 'Sem fim definido'} · <strong>{vigencia(row, hoje)}</strong></p>
          {row.encerrada_em && <p>Encerramento registrado.</p>}
          {!row.encerrada_em && (!row.fim || row.fim >= hoje) && <button className="btn" disabled={saving} onClick={() => open(row)}>Encerrar</button>}
        </article>)}
        <nav className="responsabilidades-actions" aria-label="Paginação do histórico"><button className="btn" disabled={offset === 0 || saving} onClick={() => setOffset(v => Math.max(0, v - PAGE_SIZE))}>Anterior</button><span>Página {offset / PAGE_SIZE + 1}</span><button className="btn" disabled={rows.length <= PAGE_SIZE || saving} onClick={() => setOffset(v => v + PAGE_SIZE)}>Próxima</button></nav>
      </>}
    </section>
  </div>;
}
function nextDay(date: string): string {
  const value = new Date(`${date}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}
