"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { MatriculaUV, PresencaRevisao, TurmaDetalhe } from "@/lib/uv-api";

type Props = {
  detail: TurmaDetalhe;
  busy: boolean;
  request: <T>(path: string, method?: string, payload?: unknown) => Promise<T>;
  run: (action: () => Promise<void>) => Promise<void>;
  reload: () => Promise<void>;
};

export function UVAttendance(props: Props) {
  return <section className="card"><h3>Chamada de presença</h3>
    <p>As oito aulas são obrigatórias. A reposição cumpre a aula original. Encontro e conclusão serão tratados separadamente.</p>
    {!props.detail.atividades.some(a => a.tipo === "aula") ? <p>Salve o calendário antes de registrar a chamada.</p> : null}
    {props.detail.matriculas.map(m => <StudentAttendance key={m.id} {...props} student={m} />)}
  </section>;
}

function StudentAttendance({ detail, busy, request, run, reload, student }: Props & { student: MatriculaUV }) {
  const [aula, setAula] = useState(1);
  const [presente, setPresente] = useState(true);
  const [modalidade, setModalidade] = useState<"regular" | "reposicao">("regular");
  const [confirmed, setConfirmed] = useState(false);
  const [history, setHistory] = useState<PresencaRevisao[] | null>(null);
  const [notice, setNotice] = useState("");
  const key = useRef<{ intent: string; id: string } | null>(null);
  const current = student.presencas?.find(p => p.aula === aula);
  useEffect(() => {
    setPresente(current?.presente ?? true);
    setModalidade(current?.modalidade ?? "regular");
    setConfirmed(false);
    setHistory(null);
    key.current = null;
  }, [aula, current?.registro_id, current?.presente, current?.modalidade]);
  const path = `/${detail.id}/matriculas/${student.id}/presencas/${aula}`;
  const available = detail.atividades.some(a => a.tipo === "aula" && a.aula === aula);
  const reset = () => { key.current = null; setConfirmed(false); setHistory(null); setNotice(""); };

  function submit(event: FormEvent) {
    event.preventDefault();
    if (student.conclusao || busy || detail.encerrada || !available) return;
    void run(async () => {
      const intent = JSON.stringify({ aula, presente, modalidade, anterior_id: current?.registro_id ?? null });
      if (key.current?.intent !== intent) key.current = { intent, id: crypto.randomUUID() };
      await request(path, "POST", { id: key.current.id, presente, modalidade, anterior_id: current?.registro_id ?? null });
      key.current = null; setConfirmed(false); setHistory(null);
      await reload(); setNotice(current ? "Correção registrada com histórico." : "Presença registrada.");
    });
  }

  return <article className="uv-student">
    <h4>{student.nome}</h4>
    <p>Cumpridas: {student.aulas_cumpridas?.join(", ") || "nenhuma"}. Pendentes: {student.aulas_pendentes?.join(", ") || "nenhuma"}.</p>
    <label>Aula da chamada<select aria-label="Aula da chamada" disabled={busy} value={aula} onChange={e => { setAula(Number(e.target.value)); reset(); }}>
      {Array.from({ length: 8 }, (_, i) => <option key={i + 1} value={i + 1}>Aula {i + 1}</option>)}
    </select></label>
    {current ? <p>Registro atual: {current.presente ? "Presente" : "Ausente"} · {current.modalidade === "reposicao" ? "Reposição" : "Regular"}</p> : <p>Sem registro nesta aula.</p>}
    <form onSubmit={submit}>
      <fieldset disabled={busy || detail.encerrada || !available || !!student.conclusao}>
        <legend>{current ? "Correção explícita do registro" : "Registrar chamada"}</legend>
        <label>Situação<select value={String(presente)} onChange={e => { setPresente(e.target.value === "true"); reset(); }}><option value="true">Presente</option><option value="false">Ausente</option></select></label>
        <label>Modalidade<select aria-label="Modalidade da presença" value={modalidade} onChange={e => { setModalidade(e.target.value as typeof modalidade); reset(); }}><option value="regular">Regular</option><option value="reposicao">Reposição</option></select></label>
        {current ? <label><input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Confirmo a correção; o registro anterior permanecerá no histórico.</label> : null}
        <button className="btn btn-primary" disabled={!!current && !confirmed}>{current ? "Salvar correção" : "Registrar presença"}</button>
      </fieldset>
    </form>
    {student.conclusao ? <p>UV concluída: chamada disponível somente para consulta.</p> : null}
    {detail.encerrada ? <p>Turma encerrada: chamada disponível para consulta.</p> : !available ? <p>Defina o calendário desta aula para lançar presença.</p> : null}
    <button className="btn" type="button" disabled={busy} onClick={() => void run(async () => { setHistory(await request<PresencaRevisao[]>(`${path}/historico`)); })}>Consultar histórico da aula {aula}</button>
    {notice ? <p role="status">{notice}</p> : null}
    {history ? history.length ? <ol>{history.map(h => <li key={h.registro_id}>{h.anterior_id ? "Correção" : "Registro inicial"}: {h.presente ? "Presente" : "Ausente"} · {h.modalidade === "reposicao" ? "Reposição" : "Regular"} · {new Date(h.registrada_em).toLocaleString("pt-BR")} · {h.registrada_por_nome || "Usuário da equipe"}</li>)}</ol> : <p>Nenhum registro nesta aula.</p> : null}
  </article>;
}
