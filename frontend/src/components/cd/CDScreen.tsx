"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { cdRequest, type CurriculoCD, type TurmaCD, type DetalheCD, type MatriculaCD, type PresencaCD, type ProgressoCD, type CertificadoCD } from "@/lib/cd-api";
import { Dialog } from "@/components/ds/Dialog";
import "@/components/uv/uv.css";

type Source = { id: string; numero: number; versao: string; modulo_destino_id: string };
type CertificatePerson = { pessoa_id: string; nome: string; pessoa_arquivada: boolean; curriculo_id: string };
type Choice = { id: string; nome: string };
export function CDScreen() {
  const { token, user } = useAuth();
  if (!token || !user?.roles.some(r => ["admin", "pastor", "lider_consol"].includes(r))) return <section className="card"><h1>Capacitação Destino</h1><p role="alert">Acesso restrito à coordenação e aos responsáveis autorizados.</p></section>;
  return <CDPanel key={`${user.churchId}:${user.appUserId}:${token}`} token={token} coordination={user.roles.some(r => ["admin", "pastor"].includes(r))} />;
}
function CDPanel({ token, coordination }: { token: string; coordination: boolean }) {
  const [catalogs, setCatalogs] = useState<CurriculoCD[]>([]);
  const [turmas, setTurmas] = useState<TurmaCD[]>([]);
  const [detail, setDetail] = useState<DetalheCD | null>(null);
  const [options, setOptions] = useState<Choice[]>([]);
  const [enrollments, setEnrollments] = useState<MatriculaCD[]>([]);
  const [eligible, setEligible] = useState<Choice[]>([]);
  const [search, setSearch] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [personId, setPersonId] = useState("");
  const [calling, setCalling] = useState<MatriculaCD | null>(null);
  const [lesson, setLesson] = useState("");
  const [history, setHistory] = useState<PresencaCD[]>([]);
  const [finishing, setFinishing] = useState<{ person: MatriculaCD; equivalence: boolean } | null>(null);
  const [equivalenceSource, setEquivalenceSource] = useState("");
  const [evidence, setEvidence] = useState("");
  const [certPerson, setCertPerson] = useState<CertificatePerson | null>(null);
  const [progress, setProgress] = useState<ProgressoCD | null>(null);
  const [issuing, setIssuing] = useState(false);
  const [revoking, setRevoking] = useState<CertificadoCD | null>(null);
  const [reason, setReason] = useState("");
  const [canceling, setCanceling] = useState<MatriculaCD | null>(null);
  const [selected, setSelected] = useState("");
  const [moduleId, setModuleId] = useState("");
  const [nome, setNome] = useState("");
  const [catalogName, setCatalogName] = useState("");
  const [version, setVersion] = useState("");
  const [previousCurriculum, setPreviousCurriculum] = useState("");
  const [equivSearch, setEquivSearch] = useState("");
  const [equivPeople, setEquivPeople] = useState<Choice[]>([]);
  const [equivPerson, setEquivPerson] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [equivEvidence, setEquivEvidence] = useState("");
  const [confirmEquiv, setConfirmEquiv] = useState(false);
  const [levels, setLevels] = useState<{ nome: string; modulos: number[] }[]>([]);
  const [dates, setDates] = useState<Record<string, string>>({});
  const [responsibles, setResponsibles] = useState<string[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [closing, setClosing] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const createKey = useRef<{ intent: string; id: string } | null>(null);
  const request = <T,>(path: string, method = "GET", payload?: unknown) => cdRequest<T>(token, path, method, payload, controller.current?.signal);
  function key(intent: unknown) {
    const text = JSON.stringify(intent);
    if (createKey.current?.intent !== text) createKey.current = { intent: text, id: crypto.randomUUID() };
    return createKey.current.id;
  }
  async function refresh() {
    setTurmas(await request<TurmaCD[]>("/turmas"));
    if (coordination) setCatalogs(await request<CurriculoCD[]>("/curriculos"));
  }
  async function load(id: string) {
    setCalling(null); setHistory([]); setFinishing(null); setCertPerson(null); setProgress(null); setIssuing(false); setRevoking(null);
    const value = await request<DetalheCD>(`/turmas/${id}`);
    const [matriculas, pessoas] = await Promise.all([
      request<MatriculaCD[]>(`/turmas/${id}/matriculas`),
      !value.encerrada ? request<Choice[]>(`/turmas/${id}/elegiveis`) : Promise.resolve([]),
    ]);
    setSearch(""); setSearchQuery(""); setOffset(0);
    setEnrollments(matriculas); setEligible(pessoas); setPersonId("");
    setDetail(value); setDates(Object.fromEntries(value.calendario.map(a => [a.aula_id, a.data])));
    setResponsibles(value.responsaveis.filter(r => r.elegivel).map(r => r.usuario_id));
    setOptions(coordination && !value.encerrada ? await request<Choice[]>("/opcoes") : []);
  }
  async function searchPeople(q: string, page: number) {
    if (!detail) return;
    const people = await request<Choice[]>(`/turmas/${detail.id}/elegiveis?${new URLSearchParams({ q, limit: "100", offset: String(page) })}`);
    setEligible(people); setPersonId(""); setSearchQuery(q); setOffset(page);
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); }
    catch (err) {
      if (err instanceof ApiError && [401, 403, 404].includes(err.status)) { setDetail(null); setTurmas([]); setCatalogs([]); setEquivPeople([]); setSources([]); setEquivPerson(""); setConfirmEquiv(false); setOptions([]); setEnrollments([]); setEligible([]); setCanceling(null); setCalling(null); setHistory([]); setFinishing(null); setCertPerson(null); setProgress(null); setIssuing(false); setRevoking(null); }
      if (!controller.current?.signal.aborted) setError(err instanceof Error ? err.message : "Falha ao carregar CD.");
    } finally { if (!controller.current?.signal.aborted) setBusy(false); }
  }
  useEffect(() => {
    const abort = new AbortController(); controller.current = abort;
    void Promise.all([cdRequest<TurmaCD[]>(token, "/turmas", "GET", undefined, abort.signal), coordination ? cdRequest<CurriculoCD[]>(token, "/curriculos", "GET", undefined, abort.signal) : Promise.resolve([])])
      .then(([list, curricula]) => { if (!abort.signal.aborted) { setTurmas(list); setCatalogs(curricula); } })
      .catch(err => { if (!abort.signal.aborted) setError(err instanceof Error ? err.message : "Falha ao carregar CD."); })
      .finally(() => { if (!abort.signal.aborted) setBusy(false); });
    return () => abort.abort();
  }, [token, coordination]);
  const submit = (action: () => Promise<void>) => (event: FormEvent) => { event.preventDefault(); void run(action); };
  const current = catalogs.find(c => c.id === selected);
  async function rename(cid: string, kind: string, id: string, value: string) {
    await request(`/curriculos/${cid}/${kind}/${id}`, "PUT", { nome: value }); await refresh(); setNotice("Nome atualizado.");
  }
  async function loadHistory(m: MatriculaCD, aula: string) {
    if (!detail) return;
    const revisions = await request<PresencaCD[]>(`/turmas/${detail.id}/matriculas/${m.id}/presencas/${aula}/historico`);
    setCalling(m); setLesson(aula); setHistory(revisions);
  }
  async function record(presente: boolean, modalidade: "regular" | "reposicao") {
    if (!detail || !calling) return;
    const intent = { turma: detail.id, matricula: calling.id, aula: lesson, presente, modalidade, anterior_id: history.at(-1)?.registro_id ?? null };
    await request(`/turmas/${detail.id}/matriculas/${calling.id}/presencas/${lesson}`, "POST", {
      id: key(intent), presente, modalidade, anterior_id: intent.anterior_id,
    });
    await loadHistory(calling, lesson); createKey.current = null; setNotice("Frequência registrada.");
  }
  async function loadCertificates(m: CertificatePerson) {
    const value = await request<ProgressoCD>(`/pessoas/${m.pessoa_id}/curriculos/${m.curriculo_id}`);
    setCertPerson(m); setProgress(value);
  }
  return <section className="screen uv-screen" aria-busy={busy}>
    <header><h1>Capacitação Destino</h1><p>Currículos versionados, turmas e calendário de aulas.</p></header>
    {error ? <p role="alert">{error}</p> : null}{notice ? <p role="status">{notice}</p> : null}{busy ? <p role="status">Carregando…</p> : null}
    <button className="btn" disabled={busy} onClick={() => void run(async () => { await refresh(); if (detail) await load(detail.id); })}>Atualizar</button>
    {coordination ? <>
      <form className="card" onSubmit={submit(async () => {
        const intent = { nome: catalogName, versao: version, niveis: levels, curriculo_anterior_id: previousCurriculum || null };
        await request("/curriculos", "POST", { ...intent, id: key(intent) }); createKey.current = null;
        setCatalogName(""); setVersion(""); setPreviousCurriculum(""); setLevels([]); await refresh(); setNotice("Currículo criado com 6 módulos de 10 aulas.");
      })}><h2>Novo currículo</h2><fieldset disabled={busy}>
        <label>Nome do currículo<input required maxLength={120} value={catalogName} onChange={e => setCatalogName(e.target.value)} /></label>
        <label>Versão anterior da mesma família<select value={previousCurriculum} onChange={e => setPreviousCurriculum(e.target.value)}><option value="">Novo currículo independente</option>{catalogs.map(c => <option key={c.id} value={c.id}>{c.nome} · {c.versao}</option>)}</select></label>
        <label>Versão<input required maxLength={80} value={version} onChange={e => setVersion(e.target.value)} /></label>
        <p>Estrutura inicial: 6 módulos de 10 aulas. Níveis são opcionais; quando usados, distribua todos os módulos uma vez.</p>
        {levels.map((level, i) => <fieldset key={i}><legend>Nível {i + 1}</legend>
          <label>Nome do nível<input required maxLength={120} value={level.nome} onChange={e => setLevels(ls => ls.map((l, j) => i === j ? { ...l, nome: e.target.value } : l))} /></label>
          {[1, 2, 3, 4, 5, 6].map(n => <label key={n}><input type="checkbox" checked={level.modulos.includes(n)} onChange={e => setLevels(ls => ls.map((l, j) => i === j ? { ...l, modulos: e.target.checked ? [...l.modulos, n] : l.modulos.filter(m => m !== n) } : l))} />Módulo {n}</label>)}
          <button type="button" className="btn" onClick={() => setLevels(ls => ls.filter((_, j) => i !== j))}>Remover nível {i + 1}</button>
        </fieldset>)}
        <button type="button" className="btn" disabled={levels.length >= 6} onClick={() => setLevels(ls => [...ls, { nome: "", modulos: [] }])}>Adicionar nível</button>
        <button className="btn btn-primary">Criar currículo</button>
      </fieldset></form>
      <div className="card"><h2>Catálogo</h2><label>Currículo<select value={selected} disabled={busy} onChange={e => { setSelected(e.target.value); setModuleId(""); setEquivPeople([]); setEquivPerson(""); setSources([]); setSourceId(""); setConfirmEquiv(false); }}><option value="">Selecione uma versão</option>{catalogs.map(c => <option key={c.id} value={c.id}>{c.nome} · {c.versao}</option>)}</select></label>
        {current ? <><p>Para mudar a estrutura, crie outra versão. Os nomes podem ser editados.</p>
          <Rename key={current.id + current.nome} label="Nome do currículo" value={current.nome} busy={busy} save={value => run(() => rename(current.id, "curriculo", current.id, value))} />
          {current.niveis.map(n => <Rename key={n.id + n.nome} label={`Nome do nível ${n.numero}`} value={n.nome} busy={busy} save={value => run(() => rename(current.id, "nivel", n.id, value))} />)}
          {current.modulos.map(m => <details key={m.id}><summary>{m.nome}{m.nivel_id ? ` · ${current.niveis.find(n => n.id === m.nivel_id)?.nome}` : ""}</summary>
            <Rename key={m.id + m.nome} label={`Nome do módulo ${m.numero}`} value={m.nome} busy={busy} save={value => run(() => rename(current.id, "modulo", m.id, value))} />
            {m.aulas.map(a => <Rename key={a.id + a.nome} label={`Nome da aula ${a.numero}`} value={a.nome} busy={busy} save={value => run(() => rename(current.id, "aula", a.id, value))} />)}
          </details>)}
        </> : <p>Selecione um currículo ou crie a primeira versão.</p>}
      </div>
      <div className="card"><h2>Equivalência entre versões</h2>
        <p>Selecione no catálogo a versão de destino. A coordenação pode reconhecer o mesmo módulo de uma versão anterior da família, sem matrícula na turma nova.</p>
        <form onSubmit={submit(async () => {
          setEquivPeople(await request<Choice[]>(`/curriculos/${selected}/pessoas-equivalencia?${new URLSearchParams({ q: equivSearch })}`));
          setEquivPerson(""); setSources([]); setSourceId(""); setConfirmEquiv(false);
        })}><fieldset disabled={busy || !selected}>
          <label>Buscar pessoa com conclusão anterior<input aria-label="Pessoa para equivalência" type="search" maxLength={120} value={equivSearch} onChange={e => setEquivSearch(e.target.value)} /></label>
          <button className="btn">Buscar conclusões anteriores</button>
        </fieldset></form>
        <label>Pessoa com histórico<select disabled={busy || !selected} value={equivPerson} onChange={e => {
          const pid = e.target.value; setEquivPerson(pid); setSources([]); setSourceId(""); setConfirmEquiv(false);
          if (pid) void run(async () => setSources(await request<Source[]>(`/pessoas/${pid}/curriculos/${selected}/origens-equivalencia`)));
        }}><option value="">Selecione uma pessoa</option>{equivPeople.map(p => <option key={p.id} value={p.id}>{p.nome}</option>)}</select></label>
        <button className="btn" disabled={busy || !equivPerson} onClick={() => void run(() => loadCertificates({ pessoa_id: equivPerson, nome: equivPeople.find(p => p.id === equivPerson)?.nome ?? "Pessoa selecionada", pessoa_arquivada: false, curriculo_id: selected }))}>Progresso e certificados da versão selecionada</button>
        <label>Conclusão de origem<select disabled={busy || !equivPerson} value={sourceId} onChange={e => { setSourceId(e.target.value); setConfirmEquiv(false); }}><option value="">Selecione o módulo concluído</option>{sources.map(r => <option key={r.id} value={r.id}>Módulo {r.numero} · Versão {r.versao}</option>)}</select></label>
        <label>Evidência entre versões<textarea maxLength={300} disabled={busy || !sourceId} value={equivEvidence} onChange={e => { setEquivEvidence(e.target.value); setConfirmEquiv(false); }} /></label>
        <p>Informe apenas o critério ou documento conferido, sem dados pessoais adicionais.</p>
        <button className="btn" disabled={busy || !sourceId || !equivEvidence.trim()} onClick={() => setConfirmEquiv(true)}>Registrar equivalência entre versões</button>
        <Dialog open={confirmEquiv} onClose={() => { if (!busy) setConfirmEquiv(false); }} title="Confirmar equivalência entre versões?" description={`Reconhecer o módulo ${sources.find(r => r.id === sourceId)?.numero ?? ""} de ${equivPeople.find(p => p.id === equivPerson)?.nome ?? ""} na versão ${current?.versao ?? ""}. Sua identidade e a conclusão de origem serão registradas.`}>
          {error ? <p role="alert">{error}</p> : null}
          <button className="btn" disabled={busy} onClick={() => setConfirmEquiv(false)}>Voltar</button>
          <button className="btn btn-primary" disabled={busy} onClick={() => void run(async () => {
            const source = sources.find(r => r.id === sourceId); if (!source) return;
            const path = `/pessoas/${equivPerson}/curriculos/${selected}/equivalencias`;
            const data = { confirmado: true, modulo_id: source.modulo_destino_id, conclusao_origem_id: source.id, evidencia: equivEvidence.trim() };
            await request(path, "POST", { id: key({ path, ...data }), ...data });
            createKey.current = null; setConfirmEquiv(false); setSourceId(""); setEquivEvidence("");
            setSources(await request<Source[]>(`/pessoas/${equivPerson}/curriculos/${selected}/origens-equivalencia`));
            if (detail?.curriculo_id === selected) await load(detail.id);
            setNotice("Equivalência entre versões registrada.");
          })}>Confirmar reconhecimento</button>
        </Dialog>
      </div>
      <form className="card" onSubmit={submit(async () => {
        const intent = { nome, curriculo_id: selected, modulo_id: moduleId };
        const created = await request<TurmaCD>("/turmas", "POST", { ...intent, id: key(intent) });
        createKey.current = null; setNome(""); await refresh(); await load(created.id); setNotice("Turma criada.");
      })}><h2>Nova turma</h2><fieldset disabled={busy}>
        <label>Nome da turma<input required maxLength={120} value={nome} onChange={e => setNome(e.target.value)} /></label>
        <label>Módulo da versão selecionada<select required value={moduleId} onChange={e => setModuleId(e.target.value)}><option value="">Selecione um módulo</option>{current?.modulos.map(m => <option key={m.id} value={m.id}>{m.nome}</option>)}</select></label>
        <button className="btn btn-primary" disabled={!moduleId || !nome.trim()}>Criar turma</button>
      </fieldset></form>
    </> : null}
      <Dialog open={certPerson !== null} onClose={() => { if (!busy) { setCertPerson(null); setProgress(null); setIssuing(false); setRevoking(null); } }} title={certPerson ? `Certificados de ${certPerson.nome}` : "Certificados"} description="Certificados registram a formação. Aptidão de liderança, nomeação e Enviar são independentes.">
        {error ? <p role="alert">{error}</p> : null}
        <p>{new Set(progress?.modulos_cumpridos ?? []).size} módulos cumpridos · {progress?.equivalencias?.filter(e => e.valida).length ?? 0} equivalências válidas · {progress?.niveis_concluidos.length ?? 0} níveis concluídos.</p>
        {progress?.certificados.map(c => <div className="card" key={c.id}><p>{c.nome_pessoa} · {c.nome_curriculo} · Versão {c.versao_curriculo}</p>
          <p>Código: {c.codigo} · {new Date(c.emitida_em).toLocaleString("pt-BR")} · {c.revogada ? "Revogado" : "Ativo"}</p>
          {c.revogada ? <p>{c.motivo_revogacao} · {c.revogada_em ? new Date(c.revogada_em).toLocaleString("pt-BR") : ""}</p> : <button className="btn" disabled={busy || issuing || !!revoking} onClick={() => { setReason(""); setRevoking(c); }}>Revogar certificado</button>}
        </div>)}
        {!certPerson?.pessoa_arquivada && !progress?.certificados.some(c => !c.revogada) && !issuing && !revoking ? <button className="btn" disabled={busy} onClick={() => setIssuing(true)}>Emitir certificado</button> : null}
        {issuing ? <><p>Confirmo a emissão após todos os módulos obrigatórios. O certificado guardará os nomes atuais da pessoa e do currículo.</p>
          <button className="btn" disabled={busy} onClick={() => setIssuing(false)}>Voltar</button>
          <button className="btn btn-primary" disabled={busy} onClick={() => void run(async () => {
            if (!certPerson) return;
            const path = `/pessoas/${certPerson.pessoa_id}/curriculos/${certPerson.curriculo_id}/certificados`;
            await request(path, "POST", { id: key({ path }), confirmado: true });
            await loadCertificates(certPerson); createKey.current = null; setIssuing(false); setNotice("Certificado emitido.");
          })}>Confirmar emissão</button></> : null}
        {revoking ? <><label>Motivo da revogação<textarea required maxLength={300} value={reason} disabled={busy} onChange={e => setReason(e.target.value)} /></label>
          <button className="btn" disabled={busy} onClick={() => setRevoking(null)}>Voltar</button>
          <button className="btn btn-primary" disabled={busy || !reason.trim()} onClick={() => void run(async () => {
            if (!certPerson) return;
            await request(`/certificados/${revoking.id}/revogar`, "POST", { motivo: reason.trim() });
            await loadCertificates(certPerson); setRevoking(null); setNotice("Certificado revogado.");
          })}>Confirmar revogação</button></> : null}
        <button className="btn" disabled={busy} onClick={() => { setCertPerson(null); setProgress(null); setIssuing(false); setRevoking(null); }}>Fechar certificados</button>
      </Dialog>
    <nav className="actions" aria-label="Turmas CD">{turmas.map(t => <button className="btn" key={t.id} disabled={busy} aria-pressed={detail?.id === t.id} onClick={() => void run(() => load(t.id))}>{t.nome}{t.encerrada ? " · Encerrada" : ""}</button>)}</nav>
    {!busy && !error && !turmas.length ? <p>Nenhuma turma disponível.</p> : null}
    {detail ? <article className="uv-detail"><h2>{detail.nome}{detail.encerrada ? " · Encerrada" : ""}</h2><p>{detail.modulo.nome} · Versão {detail.versao}</p>
      {coordination && !detail.encerrada ? <Rename key={detail.id + detail.nome} label="Alterar nome da turma" value={detail.nome} busy={busy} save={value => run(async () => { await request(`/turmas/${detail.id}`, "PUT", { nome: value }); await refresh(); await load(detail.id); })} /> : null}
      <form className="card" onSubmit={submit(async () => {
        await request(`/turmas/${detail.id}/calendario`, "PUT", { aulas: detail.modulo.aulas.map(a => ({ aula_id: a.id, data: dates[a.id] })) }); await load(detail.id); setNotice("Calendário salvo.");
      })}><h3>Calendário</h3><fieldset disabled={busy || !coordination || detail.encerrada}>
        {detail.modulo.aulas.map(a => <label key={a.id}>{a.numero}. {a.nome}<input type="date" required value={dates[a.id] ?? ""} onChange={e => setDates(ds => ({ ...ds, [a.id]: e.target.value }))} /></label>)}
        {coordination ? <button className="btn btn-primary">Salvar calendário</button> : null}
      </fieldset></form>
      <div className="card"><h3>Matrículas</h3>
        <p>Ingresso explícito para pessoas aptas por UV concluída ou legado. Os demais módulos exigem conclusão registrada dos anteriores.</p>
        {!detail.encerrada ? <>
          <form onSubmit={submit(() => searchPeople(search, 0))}><label>Buscar pessoa por nome<input type="search" maxLength={120} value={search} disabled={busy} onChange={e => setSearch(e.target.value)} /></label><button className="btn" disabled={busy}>Buscar pessoas</button></form>
          <div className="actions"><button className="btn" disabled={busy || offset === 0} onClick={() => void run(() => searchPeople(searchQuery, Math.max(0, offset - 100)))}>Página anterior</button><button className="btn" disabled={busy || eligible.length < 100} onClick={() => void run(() => searchPeople(searchQuery, offset + 100))}>Próxima página</button></div>
          <form onSubmit={submit(async () => {
          const intent = { turma: detail.id, pessoa_id: personId };
          await request(`/turmas/${detail.id}/matriculas`, "POST", { id: enrollments.find(m => m.pessoa_id === personId && !m.ativa)?.id ?? key(intent), pessoa_id: personId });
          createKey.current = null; await load(detail.id); setNotice("Matrícula registrada.");
        })}><fieldset disabled={busy}>
          <label>Pessoa elegível<select required value={personId} onChange={e => setPersonId(e.target.value)}><option value="">Selecione uma pessoa</option>{eligible.map(p => <option key={p.id} value={p.id}>{p.nome}</option>)}</select></label>
          {!eligible.length ? <p>Nenhuma pessoa elegível disponível.</p> : null}
          <button className="btn btn-primary" disabled={!personId}>Matricular</button>
        </fieldset></form></> : null}
        {!enrollments.length ? <p>Nenhuma matrícula registrada.</p> : null}
        {enrollments.map(m => <div key={m.id}><p>{m.nome}{m.pessoa_arquivada ? " · Pessoa arquivada" : ""} · {m.conclusao ? "Concluída" : m.ativa ? "Ativa" : "Cancelada"} · {m.origem_aptidao === "legado" ? "Aptidão legada" : "UV concluída"}</p>
          <button className="btn" disabled={busy || m.pessoa_arquivada || !detail.modulo.aulas.length} onClick={() => { const first = detail.modulo.aulas[0]; if (first) void run(() => loadHistory(m, first.id)); }}>Chamada de {m.nome}</button>
          {m.ativa && !m.conclusao && !detail.encerrada ? <button className="btn" disabled={busy} onClick={() => setCanceling(m)}>Cancelar matrícula de {m.nome}</button> : null}
          {m.conclusao ? <p>Conclusão por {m.conclusao.origem === "equivalencia" ? "equivalência" : "frequência"} · {new Date(m.conclusao.confirmada_em).toLocaleString("pt-BR")}{coordination && m.conclusao.origem_equivalencia ? ` · Origem: ${m.conclusao.origem_equivalencia}` : ""}{coordination && m.conclusao.evidencia ? ` · ${m.conclusao.evidencia}` : ""}</p> : null}
          {m.ativa && !m.conclusao && !m.pessoa_arquivada && !detail.encerrada ? <>
            <button className="btn" disabled={busy} onClick={() => { setEvidence(""); setEquivalenceSource(""); setFinishing({ person: m, equivalence: false }); }}>Concluir módulo de {m.nome}</button>
            {coordination ? <button className="btn" disabled={busy} onClick={() => { setEvidence(""); setEquivalenceSource(""); setFinishing({ person: m, equivalence: true }); }}>Registrar equivalência de {m.nome}</button> : null}
          </> : null}
          {coordination ? <button className="btn" disabled={busy} onClick={() => void run(() => loadCertificates({ ...m, curriculo_id: detail.curriculo_id }))}>Certificados de {m.nome}</button> : null}
        </div>)}
      </div>
      <Dialog open={finishing !== null} onClose={() => { if (!busy) setFinishing(null); }} title={finishing?.equivalence ? "Confirmar equivalência?" : "Concluir módulo?"} description={finishing ? `Confirme a conclusão de ${finishing.person.nome}. O registro será definitivo e a matrícula não aceitará mais frequência ou cancelamento.` : ""}>
        {error ? <p role="alert">{error}</p> : null}
        {finishing?.equivalence ? <><label>Origem da equivalência<input required maxLength={120} value={equivalenceSource} disabled={busy} onChange={e => setEquivalenceSource(e.target.value)} /></label><label>Evidência da equivalência<textarea required maxLength={300} value={evidence} aria-describedby="cd-evidence-help" disabled={busy} onChange={e => setEvidence(e.target.value)} /></label></> : <p>Todas as aulas devem estar cumpridas por presença ou reposição. Sua identidade será registrada na confirmação.</p>}
        {finishing?.equivalence ? <p id="cd-evidence-help">Descreva brevemente o documento ou critério conferido, sem dados pessoais adicionais.</p> : null}
        <button className="btn" disabled={busy} onClick={() => setFinishing(null)}>Voltar</button>
        <button className="btn btn-primary" disabled={busy || (finishing?.equivalence && (!evidence.trim() || !equivalenceSource.trim()))} onClick={() => void run(async () => {
          if (!finishing) return;
          const path = `/turmas/${detail.id}/matriculas/${finishing.person.id}/${finishing.equivalence ? "equivalencia" : "conclusao"}`;
          const data = { confirmado: true, ...(finishing.equivalence ? { evidencia: evidence.trim(), origem_equivalencia: equivalenceSource.trim() } : {}) };
          await request(path, "POST", { id: key({ path, ...data }), ...data });
          await load(detail.id); createKey.current = null; setNotice("Conclusão registrada.");
        })}>{finishing?.equivalence ? "Confirmar equivalência" : "Confirmar conclusão"}</button>
      </Dialog>
      <Dialog open={calling !== null} onClose={() => { if (!busy) { setCalling(null); setHistory([]); } }} title={calling ? `Chamada de ${calling.nome}` : "Chamada"} description="Presenças e reposições cumprem a aula. Correções preservam o histórico anterior.">
        <label>Aula da chamada<select value={lesson} disabled={busy} onChange={e => { const value = e.target.value; if (calling) void run(() => loadHistory(calling, value)); }}>
          {detail.modulo.aulas.map(a => <option key={a.id} value={a.id}>{a.numero}. {a.nome}</option>)}
        </select></label>
        {error ? <p role="alert">{error}</p> : null}
        <h4>Histórico</h4>
        {!history.length ? <p>Nenhum lançamento nesta aula.</p> : <ol>{history.map(h => <li key={h.registro_id}>{h.presente ? h.modalidade === "reposicao" ? "Reposição" : "Presente" : "Ausente"} · {h.registrada_por_nome} · {new Date(h.registrada_em).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })}</li>)}</ol>}
        <button className="btn" disabled={busy} onClick={() => { if (calling) void run(() => loadHistory(calling, lesson)); }}>Atualizar histórico</button>
        {history.length ? <p>A alteração corrigirá o último lançamento exibido.</p> : null}
        <fieldset disabled={busy || detail.encerrada || !calling?.ativa || !!calling?.conclusao}>
          <legend>Registrar frequência</legend>
          <button className="btn" onClick={() => void run(() => record(true, "regular"))}>Registrar presença</button>
          <button className="btn" onClick={() => void run(() => record(false, "regular"))}>Registrar ausência</button>
          <button className="btn" onClick={() => void run(() => record(true, "reposicao"))}>Registrar reposição</button>
        </fieldset>
        <button className="btn" disabled={busy} onClick={() => { setCalling(null); setHistory([]); }}>Fechar chamada</button>
      </Dialog>
      <Dialog open={canceling !== null} onClose={() => { if (!busy) setCanceling(null); }} title="Cancelar matrícula?" description={canceling ? `A matrícula de ${canceling.nome} será cancelada. O registro será preservado.` : ""}>
        <button className="btn" disabled={busy} onClick={() => setCanceling(null)}>Voltar</button>
        <button className="btn btn-primary" disabled={busy} onClick={() => void run(async () => {
          if (!canceling) return;
          await request(`/turmas/${detail.id}/matriculas/${canceling.id}/cancelar`, "POST");
          setCanceling(null); await load(detail.id); setNotice("Matrícula cancelada.");
        })}>Confirmar cancelamento</button>
      </Dialog>
      <div className="card"><h3>Responsáveis</h3>{detail.responsaveis.map(r => <p key={r.usuario_id}>{r.nome}{r.elegivel ? "" : " · Acesso indisponível"}</p>)}
        {coordination ? <form onSubmit={submit(async () => {
          await request(`/turmas/${detail.id}/responsaveis`, "PUT", { usuarios: responsibles }); await load(detail.id); setNotice("Responsáveis salvos.");
        })}><fieldset disabled={busy || detail.encerrada}><legend>Usuários ativos e autorizados</legend>
          {options.map(u => <label key={u.id}><input type="checkbox" checked={responsibles.includes(u.id)} onChange={e => setResponsibles(rs => e.target.checked ? [...rs, u.id] : rs.filter(id => id !== u.id))} />{u.nome}</label>)}
          <button className="btn btn-primary">Salvar responsáveis</button>
        </fieldset></form> : null}
      </div>
      {coordination ? detail.encerrada ? <button className="btn" disabled={busy} onClick={() => void run(async () => { await request(`/turmas/${detail.id}/reabrir`, "POST"); await refresh(); await load(detail.id); })}>Reabrir turma</button> : <button className="btn" disabled={busy} onClick={() => setClosing(true)}>Encerrar turma</button> : null}
      <Dialog open={closing} onClose={() => { if (!busy) setClosing(false); }} title="Encerrar turma?" description="A turma ficará disponível para consulta. A coordenação poderá reabri-la.">
        <button className="btn" disabled={busy} onClick={() => setClosing(false)}>Cancelar</button><button className="btn btn-primary" disabled={busy} onClick={() => void run(async () => {
          await request(`/turmas/${detail.id}/encerrar`, "POST"); setClosing(false); await refresh(); await load(detail.id);
        })}>Confirmar encerramento</button>
      </Dialog>
    </article> : null}
  </section>;
}
function Rename({ label, value, busy, save }: { label: string; value: string; busy: boolean; save: (value: string) => Promise<void> }) {
  const [name, setName] = useState(value);
  return <form onSubmit={e => { e.preventDefault(); void save(name); }}><label>{label}<input required maxLength={120} value={name} disabled={busy} onChange={e => setName(e.target.value)} /></label><button className="btn" disabled={busy || !name.trim() || name === value}>Salvar nome</button></form>;
}
