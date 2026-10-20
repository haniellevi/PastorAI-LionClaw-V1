'use client';

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { useAuth } from '@/lib/auth-context';
import { SessionExpiredError } from '@/lib/api';
import { ApiError } from '@/lib/dashboard-api';
import { conhecimento, appendPainel, ESTADOS, PUBLICOS, publicoTexto, type Documento, type Leitura, type Painel, type Recibo, type Trecho, type Versao } from '@/lib/conhecimento-api';
import './conhecimento.css';

type Editor = { doc?: Documento; versao?: Versao; conteudo: string; origem: string; publicos: string[] };
type Operacao = { path: string; payload: object; criada?: boolean };
const ACTIONS: Record<string, string> = { editar: 'Criar nova versão', 'enviar-revisao': 'Enviar para revisão', revisar: 'Registrar revisão', publicar: 'Aprovar e publicar', revogar: 'Revogar versão', excluir: 'Excluir documento' };
const date = (value: string) => new Date(value).toLocaleString('pt-BR');

export function ConhecimentoScreen() {
  const { token, expireSession } = useAuth();
  return token ? <PainelConhecimento key={token} token={token} onExpired={expireSession} /> : null;
}

export function PainelConhecimento({ token, onExpired }: { token: string; onExpired: () => void }) {
  const [painel, setPainel] = useState<Painel | null>(null);
  const [leitura, setLeitura] = useState<Leitura | null>(null);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [confirmacao, setConfirmacao] = useState<{ doc: Documento; versao: Versao; acao: string } | null>(null);
  const [recibo, setRecibo] = useState<Recibo | null>(null);
  const [resultados, setResultados] = useState<Trecho[] | null>(null);
  const [consulta, setConsulta] = useState('');
  const [erro, setErro] = useState('');
  const [aviso, setAviso] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState<Operacao | null>(null);
  const locked = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const active = useRef(true);
  const detailRef = useRef<HTMLElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  function rememberFocus() { returnFocus.current = document.activeElement as HTMLElement | null; }
  function closeDetail() {
    setLeitura(null); setEditor(null); setConfirmacao(null);
    if (returnFocus.current?.isConnected) returnFocus.current.focus();
    else document.getElementById("conhecimento-busca")?.focus();
  }

  const load = useCallback(async (signal?: AbortSignal) => {
    const result = await conhecimento<Painel>(token, 'documentos', undefined, signal);
    if (active.current && !signal?.aborted) setPainel(result);
  }, [token]);
  const failure = useCallback((e: unknown) => {
    if (!active.current || (e instanceof DOMException && e.name === 'AbortError')) return;
    if (e instanceof SessionExpiredError) { onExpired(); return; }
    if (e instanceof ApiError && [403, 404].includes(e.status)) {
      setLeitura(null); setResultados(null);
      if (e.status === 403) { setPainel(null); setEditor(null); setConfirmacao(null); setRecibo(null); }
    }
    setErro(e instanceof ApiError ? e.message : 'Não foi possível conectar. Tente novamente.');
  }, [onExpired]);
  useEffect(() => {
    active.current = true;
    const abort = new AbortController();
    void load(abort.signal).catch(failure);
    return () => { active.current = false; abort.abort(); controller.current?.abort(); };
  }, [load, failure]);
  const isReading = leitura !== null;
  const isEditing = editor !== null;
  const isConfirming = confirmacao !== null;
  useEffect(() => {
    if (isReading || isEditing || isConfirming) detailRef.current?.focus();
  }, [isReading, isEditing, isConfirming]);

  async function run(task: (signal: AbortSignal) => Promise<void>) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setErro('');
    controller.current?.abort();
    const abort = new AbortController(); controller.current = abort;
    try { await task(abort.signal); } catch (e) { failure(e); }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }
  async function mutate(operation: Operacao) {
    await run(async signal => {
      setRetry(operation);
      try {
        const receipt = await conhecimento<Recibo>(token, operation.path, operation.payload, signal);
        if (!active.current) return;
        setRetry(null); setEditor(null); setConfirmacao(null); setLeitura(null); setResultados(null);
        setRecibo(operation.criada ? receipt : null);
        setAviso(operation.criada ? 'Rascunho criado. Envie para revisão para disponibilizá-lo ao pastor responsável.' : 'Operação concluída. A lista foi atualizada.');
        setPainel(null);
        await load(signal);
      } catch (e) {
        if (e instanceof ApiError && e.status === 422) setRetry(null);
        if (e instanceof ApiError && [403, 404, 409].includes(e.status)) {
          setRetry(null); setEditor(null); setConfirmacao(null); setLeitura(null); setPainel(null); setResultados(null);
          await load(signal);
        }
        throw e;
      }
    });
  }
  function openVersion(id: string, editing?: { doc: Documento; versao: Versao }) {
    rememberFocus();
    setLeitura(null); setEditor(null); setConfirmacao(null);
    void run(async signal => {
      const data = await conhecimento<Leitura>(token, `versoes/${encodeURIComponent(id)}`, undefined, signal);
      if (!active.current) return;
      if (editing) setEditor({ ...editing, conteudo: data.conteudo, origem: data.origem, publicos: data.publicos });
      else setLeitura(data);
    });
  }
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor || !painel?.responsavel_id) return;
    const fields = new FormData(event.currentTarget);
    const payload = {
      operacao_id: crypto.randomUUID(), versao_id: crypto.randomUUID(),
      conteudo: editor.conteudo, origem: editor.origem, publicos: editor.publicos,
      ...(editor.doc && editor.versao ? { anterior_id: editor.versao.id } : {
        id: crypto.randomUUID(), titulo: fields.get('titulo'), assunto: fields.get('assunto'), responsavel_id: painel.responsavel_id,
      }),
    };
    void mutate({ path: editor.doc ? `documentos/${editor.doc.id}/rascunhos` : 'documentos', payload, criada: true });
  }
  function confirm() {
    if (!confirmacao) return;
    const { doc, versao, acao } = confirmacao;
    void mutate({ path: `documentos/${doc.id}/${acao}`, payload: {
      operacao_id: crypto.randomUUID(), ...(acao === 'excluir' ? { confirmacao: 'EXCLUIR DOCUMENTO' } : { versao_id: versao.id }),
      ...(acao === 'publicar' ? { publicos: versao.publicos, vigente_esperada_id: doc.vigente_id } : {}),
    } });
  }

  const pending = [...(painel?.pendentes ?? [])];
  if (recibo && !pending.some(p => p.versao_id === recibo.versao_id)) pending.unshift(recibo);

  return <div className="screen conhecimento-screen" aria-busy={busy}>
    <div className="screen-head"><div className="titles"><h2>Conhecimento oficial</h2><p>Documentos aprovados pela igreja, com versão e público definidos.</p></div>
      <button className="btn" disabled={busy || !!retry} onClick={() => { setPainel(null); setLeitura(null); setResultados(null); setEditor(null); setConfirmacao(null); void run(load); }}>Atualizar</button>
    </div>
    <p>Conversas e mensagens privadas nunca são convertidas em conhecimento oficial. A revisão é opcional; somente o administrador aprova e publica.</p>
    {erro && <p role="alert">{erro}</p>}
    {aviso && <p role="status">{aviso}</p>}
    {retry && <section className="card card-pad"><p>O resultado ainda não foi confirmado. Repita a mesma operação com segurança para consultar o recibo.</p><button className="btn" disabled={busy} onClick={() => void mutate(retry)}>Repetir operação</button></section>}
    <fieldset disabled={busy || !!retry} className="conhecimento-controls">
      <legend className="sr-only">Consulta e edição</legend>
      <form onSubmit={e => { e.preventDefault(); setResultados(null); setLeitura(null); void run(async signal => { setResultados(await conhecimento<Trecho[]>(token, `busca?q=${encodeURIComponent(consulta)}`, undefined, signal)); }); }}>
        <label htmlFor="conhecimento-busca">Buscar nos documentos publicados</label><div className="conhecimento-actions"><input id="conhecimento-busca" required maxLength={200} value={consulta} onChange={e => setConsulta(e.target.value)} /><button className="btn" type="submit">Buscar</button></div>
      </form>
      {resultados && <section aria-label="Resultados da busca"><h3>Resultados</h3>{resultados.length === 0 && <p role="status">Nenhum trecho autorizado encontrado. Consulte o responsável se faltar informação oficial.</p>}
        <ul>{resultados.map((r, i) => <li key={i}><button className="btn" onClick={() => openVersion(r.versao_id)}>{r.titulo}</button><p>{r.trecho}</p></li>)}</ul></section>}
      {painel?.pode_criar && <button className="btn btn-primary" onClick={() => { rememberFocus(); setEditor({ conteudo: '', origem: '', publicos: [] }); setLeitura(null); setConfirmacao(null); }}>Criar rascunho</button>}
      {pending.map((p, i) => <section key={p.versao_id} className="card card-pad"><h3>Rascunho pendente {i + 1}</h3><p>O rascunho é restrito ao administrador até o envio para revisão. Você pode retomar o envio após voltar ao painel.</p><button className="btn" onClick={() => void mutate({ path: `documentos/${p.documento_id}/enviar-revisao`, payload: { operacao_id: crypto.randomUUID(), versao_id: p.versao_id } })}>Enviar rascunho salvo para revisão</button></section>)}
      {!painel && !erro && <p role="status">Carregando documentos…</p>}
      {painel && <section aria-label="Documentos"><h3>Documentos disponíveis</h3>{painel.documentos.length === 0 && <p>Nenhum documento disponível para seu acesso.</p>}
        {painel.documentos.map(doc => <article key={doc.id} className="card card-pad"><h4>{doc.titulo}</h4><p>{doc.assunto}</p>
          <p>Versão vigente: {(doc.vigente_numero ?? doc.versoes.find(v => v.vigente)?.numero) ? `versão ${doc.vigente_numero ?? doc.versoes.find(v => v.vigente)!.numero}` : 'nenhuma versão disponível para leitura'}</p>
          {doc.pode_excluir && <button className="btn" onClick={() => { rememberFocus(); setEditor(null); setLeitura(null); setConfirmacao({ doc, versao: doc.versoes[0]!, acao: 'excluir' }); }}>Excluir documento</button>}
          <details><summary>Versões e histórico</summary><ol>{doc.versoes.map(v => <li key={v.id}>
            <p><strong>Versão {v.numero} · {ESTADOS[v.estado] ?? 'Estado indisponível'}{v.vigente ? ' · Vigente' : ''}</strong></p>
            <p>Público-alvo: {publicoTexto(v.publicos)}</p><p>Criada em {date(v.criada_em)}{v.revisada_em ? ` · Revisão registrada em ${date(v.revisada_em)}` : ''}{v.publicada_em ? ` · Publicada em ${date(v.publicada_em)}` : ''}</p>
            <div className="conhecimento-actions">{v.pode_ler && <button className="btn" onClick={() => openVersion(v.id)}>Ler versão {v.numero}</button>}
              {v.acoes.map(a => <button className="btn" key={a} disabled={a === 'publicar' && !v.publicos.length} onClick={() => {
                if (a === 'editar') {
                  if (v.pode_ler) openVersion(v.id, { doc, versao: v });
                  else { rememberFocus(); setLeitura(null); setConfirmacao(null); setEditor({ doc, versao: v, conteudo: '', origem: '', publicos: v.publicos }); }
                }
                else { rememberFocus(); setEditor(null); setLeitura(null); setConfirmacao({ doc, versao: v, acao: a }); }
              }}>{ACTIONS[a]}</button>)}</div>
            {!v.pode_ler && <p>Conteúdo indisponível. O histórico não concede acesso ao texto retirado.</p>}
          </li>)}</ol></details>
        </article>)}
      </section>}
      {painel?.tem_mais && <button className="btn" onClick={() => void run(async signal => {
        const next = await conhecimento<Painel>(token, `documentos?pagina=${(painel.pagina ?? 1) + 1}`, undefined, signal);
        if (active.current) setPainel(previous => appendPainel(previous, next));
      })}>Carregar mais documentos e versões</button>}
      {(leitura || editor || confirmacao) && <section ref={detailRef} tabIndex={-1} className="card card-pad conhecimento-detail" aria-label="Documento selecionado">
        <button className="btn" onClick={closeDetail}>Fechar documento</button>
        {leitura && <><h3>{leitura.titulo}</h3><p>{ESTADOS[leitura.estado]}</p><p>Público-alvo: {publicoTexto(leitura.publicos)}</p><p>Origem: {leitura.origem}</p><div className="conhecimento-text">{leitura.conteudo}</div></>}
        {editor && <form onSubmit={save}><h3>{editor.doc ? `Nova versão de ${editor.doc.titulo}` : 'Novo documento'}</h3>
          <p>Novos documentos ficam sob sua responsabilidade. Alterar texto ou público cria uma nova versão que exige aprovação.</p>
          {editor.versao && !editor.versao.pode_ler && <p>Você pode propor uma substituição, mas não tem acesso ao texto vigente. Redija a nova versão sem copiar o conteúdo restrito.</p>}
          {!editor.doc && <><label htmlFor="conhecimento-titulo">Título</label><input id="conhecimento-titulo" name="titulo" required maxLength={200} /><label htmlFor="conhecimento-assunto">Assunto</label><input id="conhecimento-assunto" name="assunto" required maxLength={120} /></>}
          <label htmlFor="conhecimento-origem">Origem oficial</label><input id="conhecimento-origem" required maxLength={500} value={editor.origem} onChange={e => setEditor({ ...editor, origem: e.target.value })} />
          <label htmlFor="conhecimento-texto">Texto do documento</label><textarea id="conhecimento-texto" required maxLength={100000} rows={12} value={editor.conteudo} onChange={e => setEditor({ ...editor, conteudo: e.target.value })} />
          <fieldset><legend>Público-alvo explícito</legend><p>Selecione quem poderá ler após a publicação. Sem seleção, não é possível publicar.</p>{Object.entries(PUBLICOS).map(([value, label]) => <label key={value} className="conhecimento-check"><input type="checkbox" checked={editor.publicos.includes(value)} onChange={e => setEditor({ ...editor, publicos: e.target.checked ? [...editor.publicos, value] : editor.publicos.filter(p => p !== value) })} />{label}</label>)}</fieldset>
          <button className="btn btn-primary" type="submit">Salvar rascunho</button></form>}
        {confirmacao && <><h3>{ACTIONS[confirmacao.acao]}</h3><p>{confirmacao.doc.titulo} · Versão {confirmacao.versao.numero}</p><p>Público-alvo: {publicoTexto(confirmacao.versao.publicos)}</p>
          <p>{confirmacao.acao === 'excluir' ? 'Todas as versões e trechos serão apagados definitivamente, incluindo os índices de busca. O recibo e o histórico de auditoria sem conteúdo serão preservados. Esta ação não pode ser desfeita.' : confirmacao.acao === 'publicar' ? 'Esta aprovação publica o texto para os públicos selecionados e substitui a versão vigente, se houver.' : confirmacao.acao === 'revogar' ? 'O texto deixará de estar disponível para novas leituras e buscas imediatamente.' : confirmacao.acao === 'revisar' ? 'Registra sua revisão deste texto. A publicação depende do administrador.' : 'O pastor responsável poderá ler esta versão. O envio não publica o documento.'}</p>
          <button className="btn btn-primary" onClick={confirm}>Confirmar {(ACTIONS[confirmacao.acao] ?? 'operação').toLocaleLowerCase('pt-BR')}</button></>}
      </section>}
    </fieldset>
  </div>;
}
