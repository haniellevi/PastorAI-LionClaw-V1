"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { uvRequest, type Turma, type TurmaDetalhe, type UVOpcoes, type Atividade } from "@/lib/uv-api";
import { ApiError } from "@/lib/dashboard-api";
import { Dialog } from "@/components/ds/Dialog";

import "./uv.css";

const curriculum = [1, 2, 3, 4, null, 5, 6, 7, 8];
const label = (n: number | null) => n === null ? "Encontro" : `Aula ${n}`;

export function UVScreen() {
  const { token, user } = useAuth();
  if (!token || !user?.roles.some(r => ["admin", "pastor", "lider_consol"].includes(r))) {
    return <section className="card"><h1>Universidade da Vida</h1><p role="alert">Acesso restrito à coordenação e aos responsáveis autorizados.</p></section>;
  }
  return <UVPanel key={`${user.churchId}:${user.appUserId}:${token}`} token={token} />;
}

function UVPanel({ token }: { token: string }) {
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [detail, setDetail] = useState<TurmaDetalhe | null>(null);
  const [options, setOptions] = useState<UVOpcoes>({ pessoas: [], usuarios: [] });
  const [nome, setNome] = useState("");
  const [search, setSearch] = useState("");
  const [person, setPerson] = useState("");
  const [responsibles, setResponsibles] = useState<string[]>([]);
  const [dates, setDates] = useState<string[]>(curriculum.map(() => ""));
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [closing, setClosing] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const createKey = useRef<string | null>(null);
  const enrollKey = useRef<{ person: string; turma: string; id: string } | null>(null);

  const request = <T,>(path = "", method = "GET", payload?: unknown) =>
    uvRequest<T>(token, path, method, payload, controller.current?.signal);

  async function loadDetail(id: string) {
    const value = await request<TurmaDetalhe>(`/${id}`);
    setDetail(value);
    setResponsibles(value.responsaveis.filter(r => r.elegivel).map(r => r.usuario_id));
    setDates(curriculum.map((_, index) => value.atividades.find(a => a.ordem === index + 1)?.data ?? ""));
    setPerson("");
  }

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); }
    catch (err) {
      if (err instanceof ApiError && [401, 403, 404].includes(err.status)) { setDetail(null); setTurmas([]); setOptions({ pessoas: [], usuarios: [] }); }
      if (!controller.current?.signal.aborted) setError(err instanceof Error ? err.message : "Não foi possível carregar a UV.");
    } finally { if (!controller.current?.signal.aborted) setBusy(false); }
  }

  useEffect(() => {
    const abort = new AbortController(); controller.current = abort;
    void Promise.all([
      uvRequest<Turma[]>(token, "", "GET", undefined, abort.signal),
      uvRequest<UVOpcoes>(token, "/opcoes", "GET", undefined, abort.signal),
    ]).then(([list, choices]) => { if (!abort.signal.aborted) { setTurmas(list); setOptions(choices); } })
      .catch(err => { if (!abort.signal.aborted) setError(err instanceof Error ? err.message : "Falha ao carregar turmas."); })
      .finally(() => { if (!abort.signal.aborted) setBusy(false); });
    return () => abort.abort();
  }, [token]);

  const submit = (action: () => Promise<void>) => (event: FormEvent) => { event.preventDefault(); void run(action); };

  return <section className="screen uv-screen" aria-busy={busy}>
    <header><h1>Universidade da Vida</h1><p>Organize turmas, calendário e matrículas. As presenças e a conclusão serão disponibilizadas em etapas futuras.</p></header>
    {error ? <p role="alert">{error}</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    {busy ? <p role="status">Carregando…</p> : null}
    <button type="button" className="btn" disabled={busy} onClick={() => void run(async () => {
      setTurmas(await request<Turma[]>());
      if (detail) await loadDetail(detail.id);
    })}>Atualizar turmas</button>
    <form className="card" onSubmit={submit(async () => {
      createKey.current ??= crypto.randomUUID();
      const created = await request<Turma>("", "POST", { id: createKey.current, nome });
      createKey.current = null; setNome("");
      setTurmas(await request<Turma[]>()); await loadDetail(created.id); setNotice("Turma criada.");
    })}>
      <h2>Nova turma</h2>
      <label>Nome da turma<input required maxLength={120} value={nome} disabled={busy} onChange={event => { setNome(event.target.value); createKey.current = null; }} /></label>
      <button className="btn btn-primary" disabled={busy || !nome.trim()}>Criar turma</button>
    </form>
    <nav aria-label="Turmas UV" className="actions">{turmas.map(t => <button type="button" className="btn" key={t.id} disabled={busy} aria-pressed={detail?.id === t.id} onClick={() => void run(() => loadDetail(t.id))}>{t.nome}{t.encerrada ? " · Encerrada" : ""}</button>)}</nav>
    {!busy && !error && turmas.length === 0 ? <p>Nenhuma turma disponível. Crie uma turma para começar.</p> : null}
    {detail ? <article className="uv-detail">
      <h2>{detail.nome}{detail.encerrada ? " · Encerrada" : ""}</h2>
      <form className="card" onSubmit={submit(async () => {
        const atividades: Atividade[] = curriculum.map((aula, i) => ({ ordem: i + 1, tipo: aula === null ? "encontro" : "aula", aula, data: dates[i] ?? "" }));
        await request(`/${detail.id}/calendario`, "PUT", { atividades });
        await loadDetail(detail.id); setNotice("Calendário salvo.");
      })}>
        <h3>Calendário</h3>
        <fieldset disabled={busy || detail.encerrada}><legend>8 aulas e Encontro, em ordem</legend>
          {curriculum.map((n, i) => <label key={i}>{i + 1}. {label(n)}<input type="date" required value={dates[i]} onChange={e => setDates(current => current.map((value, j) => j === i ? e.target.value : value))} /></label>)}
          <button className="btn btn-primary">Salvar calendário</button>
        </fieldset>
      </form>
      <form className="card" onSubmit={submit(async () => {
        await request(`/${detail.id}/responsaveis`, "PUT", { usuarios: responsibles });
        // Saving can remove this user's own access. Clear cached identities first.
        setDetail(null); setTurmas(await request<Turma[]>()); setNotice("Responsáveis salvos.");
      })}>
        <h3>Responsáveis pela turma</h3>
        {detail.responsaveis.filter(r => !r.elegivel).map(r => <p key={r.usuario_id} role="status">{r.nome ?? "Responsável anterior"}: acesso indisponível. Remova ou substitua o vínculo.</p>)}
        <fieldset disabled={busy || detail.encerrada}><legend>Usuários ativos e autorizados</legend>
          {options.usuarios.map(u => <label key={u.id}><input type="checkbox" checked={responsibles.includes(u.id)} onChange={e => setResponsibles(current => e.target.checked ? [...current, u.id] : current.filter(id => id !== u.id))} />{u.nome}</label>)}
          <button className="btn btn-primary">Salvar responsáveis</button>
        </fieldset>
      </form>
      <div className="card"><h3>Matrículas</h3>
        <p>A matrícula exige decisão registrada e responsável na consolidação. A conexão à célula é acompanhada como pendência.</p>
        <form onSubmit={submit(async () => { setOptions(await request<UVOpcoes>(`/opcoes?q=${encodeURIComponent(search)}`)); setPerson(""); })}>
          <label>Buscar pessoa elegível<input value={search} maxLength={120} disabled={busy || detail.encerrada} onChange={e => setSearch(e.target.value)} /></label>
          <button className="btn" disabled={busy || detail.encerrada}>Buscar pessoa</button>
        </form>
        <form onSubmit={submit(async () => {
          if (enrollKey.current?.person !== person || enrollKey.current.turma !== detail.id) enrollKey.current = { person, turma: detail.id, id: crypto.randomUUID() };
          await request(`/${detail.id}/matriculas`, "POST", { id: enrollKey.current.id, pessoa_id: person });
          enrollKey.current = null; await loadDetail(detail.id); setNotice("Matrícula registrada.");
        })}>
          <label>Pessoa<select required value={person} disabled={busy || detail.encerrada} onChange={e => setPerson(e.target.value)}><option value="">Selecione uma pessoa</option>{options.pessoas.filter(p => !detail.matriculas.some(m => m.pessoa_id === p.id)).map(p => <option key={p.id} value={p.id}>{p.nome}</option>)}</select></label>
          <button className="btn btn-primary" disabled={busy || detail.encerrada || !person}>Matricular pessoa</button>
        </form>
        {detail.matriculas.length ? <ul>{detail.matriculas.map(m => <li key={m.id}>{m.nome}{m.conexao_celula_pendente ? " · Conexão à célula pendente" : ""}</li>)}</ul> : <p>Nenhuma pessoa matriculada.</p>}
      </div>
      {!detail.encerrada ? <button type="button" className="btn" disabled={busy} onClick={() => setClosing(true)}>Encerrar turma</button> : null}
      <Dialog open={closing} onClose={() => { if (!busy) setClosing(false); }} title="Encerrar turma?" description="A turma ficará disponível para consulta e não aceitará novas matrículas ou alterações.">
        <button className="btn" disabled={busy} onClick={() => setClosing(false)}>Cancelar</button>
        <button className="btn btn-primary" disabled={busy} onClick={() => void run(async () => {
          await request(`/${detail.id}/encerrar`, "POST"); setClosing(false);
          setTurmas(await request<Turma[]>()); await loadDetail(detail.id); setNotice("Turma encerrada.");
        })}>Confirmar encerramento</button>
      </Dialog>
    </article> : null}
  </section>;
}
