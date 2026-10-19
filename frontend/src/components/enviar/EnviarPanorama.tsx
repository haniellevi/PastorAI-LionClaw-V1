'use client';
import { useEffect, useState } from 'react';
import { SessionExpiredError } from '@/lib/api';
import { getEnviarPessoas, getEnviarHistorico, type EnviarPessoa, type EnviarHistorico, type EnviarPage } from '@/lib/enviar-api';

type View = 'pendentes' | 'aptos' | 'historico';
const operation = { nomear_lider: 'Nomeação', abrir_celula: 'Abertura', multiplicacao: 'Multiplicação' };
const situation = { apto_para_avaliacao: 'Apto para avaliação', pendente: 'Formação pendente', bloqueado: 'Bloqueado para nova nomeação' };
const status: Record<string, string> = { aguardando: 'Aguardando decisão', ajuste_solicitado: 'Ajuste solicitado', aprovada: 'Aprovada', rejeitada: 'Rejeitada', cancelada: 'Cancelada' };
function date(value: string) { return new Date(value).toLocaleDateString('pt-BR', { timeZone: 'UTC' }); }

export function EnviarPanorama({ token, onExpired, canDecide, reloadToken = 0 }: { token: string; onExpired: () => void; canDecide: boolean; reloadToken?: number }) {
  const [view, setView] = useState<View>('pendentes');
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [data, setData] = useState<EnviarPage<EnviarPessoa> | EnviarPage<EnviarHistorico> | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setData(null);
    const request = view === 'historico' ? getEnviarHistorico(token, { q, page }) : getEnviarPessoas(token, { q, page, grupo: view });
    request.then(value => { if (active) setData(value); }).catch(err => {
      if (!active) return;
      if (err instanceof SessionExpiredError) onExpired();
      else setError(err instanceof Error ? err.message : 'Não foi possível consultar Enviar.');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token, q, page, view, reload, reloadToken, onExpired]);
  return <section className="card card-pad" aria-label="Pessoas e histórico de Enviar">
    <h3>Pessoas e histórico</h3>
    <p>A avaliação de aptidão não nomeia líderes. Legados preservam sua situação; formação pendente exige conferência pastoral.</p>
    <div className="actions" role="group" aria-label="Visualização de Enviar">
      {([['pendentes', 'Pendências de formação'], ['aptos', 'Aptos'], ['historico', 'Histórico']] as const).map(([key, label]) =>
        <button type="button" className="btn" key={key} aria-pressed={view === key} onClick={() => { setView(key); setPage(1); }}>{label}</button>)}
    </div>
    <form role="search" aria-label="Busca de Enviar" onSubmit={event => { event.preventDefault(); setQ(search.trim()); setPage(1); setReload(n => n + 1); }}>
      <label htmlFor="enviar-busca">{view === 'historico' ? 'Buscar por operação ou célula' : 'Buscar pessoa'}</label>
      <input id="enviar-busca" type="search" maxLength={100} value={search} onChange={event => setSearch(event.target.value)} />
      <button className="btn" type="submit">Buscar</button>
    </form>
    <nav aria-label="Ações de Enviar" className="actions">
      <a href="#enviar" onClick={event => { event.preventDefault(); const target = document.getElementById("enviar-pedidos"); target?.scrollIntoView({ block: "start" }); target?.focus({ preventScroll: true }); }}>Iniciar nomeação ou abertura</a>
      <a href="#minha-celula">Solicitar multiplicação em Minha Célula</a>
      {canDecide ? <a href="#central-celula">Decidir na Central de Célula</a> : null}
    </nav>
    {loading ? <p role="status">Carregando Enviar…</p> : error ? <div role="alert"><p>{error}</p><button type="button" className="btn" onClick={() => setReload(n => n + 1)}>Repetir consulta</button></div> : data ? <>
      <p role="status">{data.total} {view === 'historico' ? 'registros' : 'pessoas'} · Página {page}</p>
      {data.items.length === 0 ? <p>{view === 'historico' ? 'Nenhum registro neste filtro.' : 'Nenhuma pessoa neste filtro.'}</p> : <ul className="queue">
        {view === 'historico' ? (data.items as EnviarHistorico[]).map(item => <li className="qitem" key={item.id}><div className="qbody">
          <strong>{operation[item.tipo]}</strong><p>{status[item.status] ?? item.status} · Pedido em {date(item.criada_em)}{item.decidido_em ? ` · Decisão em ${date(item.decidido_em)}` : ''}</p>
          {canDecide ? <a href="#central-celula">Consultar pedido na Central</a> : <a href="#enviar" onClick={event => { event.preventDefault(); const target = document.getElementById("enviar-pedidos"); target?.scrollIntoView({ block: "start" }); target?.focus({ preventScroll: true }); }}>Consultar meus pedidos</a>}
        </div></li>) : (data.items as EnviarPessoa[]).map(person => <li className="qitem" key={person.id}><div className="qbody">
          <strong>{person.nome}</strong><p>{situation[person.situacao]}{person.apto_lider ? ' · Apto a liderar' : ''}</p>
          {canDecide && person.origem === 'legado' ? <p>origem legada, comprovação pendente</p> : null}
          {person.pendencias.length ? <ul>{person.pendencias.map(p => <li key={p.criterio}>{p.descricao}</li>)}</ul> : null}
          {canDecide ? <p>{person.ultima_avaliacao ? `Última avaliação: ${person.ultima_avaliacao.decisao === 'apto' ? 'apto' : 'não apto'} em ${date(person.ultima_avaliacao.criada_em)} · ${person.ultima_avaliacao.versao_regras}` : 'Sem avaliação registrada.'}</p> : null}
        </div></li>)}
      </ul>}
      <div className="actions" role="group" aria-label="Paginação de Enviar">
        <button type="button" className="btn" disabled={page === 1} onClick={() => setPage(n => n - 1)}>Página anterior</button>
        <button type="button" className="btn" disabled={page * data.page_size >= data.total} onClick={() => setPage(n => n + 1)}>Próxima página</button>
      </div>
    </> : null}
  </section>;
}
