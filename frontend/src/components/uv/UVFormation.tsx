"use client";
import { useRef, useState, type FormEvent } from "react";
import type { MarcoUV, MatriculaUV, TurmaDetalhe } from "@/lib/uv-api";

type Request = <T>(path: string, method?: string, payload?: unknown) => Promise<T>;
type Run = (action: () => Promise<void>) => Promise<void>;
type Actions = { disabled: boolean; request: Request; run: Run; reload: () => Promise<void> };

export function UVFormation({ detail, busy, coordination, ...actions }: Omit<Actions, "disabled"> & { detail: TurmaDetalhe; busy: boolean; coordination: boolean }) {
  return <section className="card"><h3>Marcos e conclusão</h3>
    <p>Oito aulas cumpridas, Encontro e batismo validados e confirmação humana. A conexão à célula continua como pendência. Ninguém repete o batismo.</p>
    {detail.matriculas.map(m => <Formation key={m.id} enrollment={m} turma={detail.id} coordination={coordination} reencontroDisabled={busy} disabled={busy || detail.encerrada} {...actions} />)}
  </section>;
}

function Formation({ enrollment: m, turma, disabled, coordination, reencontroDisabled, request, run, reload }: Actions & { enrollment: MatriculaUV; turma: string; coordination: boolean; reencontroDisabled: boolean }) {
  const [confirmed, setConfirmed] = useState(false);
  const receipt = useRef<string | null>(null);
  const base = `/${turma}/matriculas/${m.id}`;
  const ready = m.aulas_pendentes?.length === 0 && ["encontro", "batismo"].every(tipo => m.marcos?.some(v => v.tipo === tipo && !v.revogada));
  return <article className="uv-student"><h4>{m.nome}</h4>
    {(["encontro", "batismo", "reencontro"] as const).map(tipo => {
      if (tipo === "reencontro" && !coordination && !m.marcos?.some(v => v.tipo === tipo)) return null;
      const record = m.marcos?.find(v => v.tipo === tipo && !v.revogada) ?? m.marcos?.find(v => v.tipo === tipo);
      return record ? <div key={tipo}><p>{tipo === "encontro" ? "Encontro" : tipo === "reencontro" ? "Reencontro" : "Batismo"}: {record.data} · {record.anterior_turma ? "Anterior à turma de origem" : "Durante a turma de origem"}: {record.turma_nome} · Validado por {record.validada_por} em {record.validada_em}</p>
          {record.revogada ? <><p>{tipo === "reencontro" ? "Reencontro" : tipo === "encontro" ? "Encontro" : "Batismo"}: evidência revogada em {record.revogada_em}. Novas nomeações bloqueadas; liderança preservada.</p>{coordination ? <Milestone tipo={tipo} revalidation base={base} disabled={reencontroDisabled} request={request} run={run} reload={reload} /> : null}</> : tipo === "reencontro" && coordination ? <Revoke base={base} disabled={reencontroDisabled} request={request} run={run} reload={reload} /> : null}</div>
        : <Milestone key={tipo} tipo={tipo} base={base} disabled={tipo === "reencontro" ? reencontroDisabled : disabled || !!m.conclusao} request={request} run={run} reload={reload} />;
    })}
    {m.conclusao ? <p role="status">UV concluída em {m.conclusao.confirmada_em} por {m.conclusao.confirmada_por}. Jornada: {m.conclusao.etapa_anterior ?? "Sem etapa"} → {m.conclusao.etapa_resultante}. Aptidão à próxima CD: {m.conclusao.origem_aptidao}. Sem matrícula automática.</p>
      : <form onSubmit={e => {
        e.preventDefault(); if (!ready || !confirmed || disabled) return;
        void run(async () => {
          receipt.current ??= crypto.randomUUID();
          await request(`${base}/concluir`, "POST", { id: receipt.current, confirmado: true });
          receipt.current = null; setConfirmed(false); await reload();
        });
      }}><fieldset disabled={disabled}><legend>Conclusão da UV de {m.nome}</legend>
        <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Confirmo a conclusão da UV desta Pessoa</label>
        <p>A conclusão registra o histórico na Pessoa e a aptidão à próxima CD, sem matrícula automática.</p>
        <button className="btn btn-primary" disabled={disabled || !ready || !confirmed}>Concluir UV</button>
      </fieldset></form>}
  </article>;
}

function Milestone({ tipo, base, disabled, request, run, reload, revalidation = false }: Actions & { tipo: MarcoUV["tipo"]; base: string; revalidation?: boolean }) {
  const [date, setDate] = useState("");
  const [prior, setPrior] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const receipt = useRef<{ intent: string; id: string } | null>(null);
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (disabled || !confirmed || !date) return;
    void run(async () => {
      const intent = JSON.stringify([date, prior]);
      if (receipt.current?.intent !== intent) receipt.current = { intent, id: crypto.randomUUID() };
      await request(`${base}/marcos/${tipo}`, "POST", { id: receipt.current.id, data: date, anterior_turma: prior, confirmado: true });
      receipt.current = null; setConfirmed(false); await reload();
    });
  }
  return <form onSubmit={submit}><fieldset disabled={disabled}>
    <legend>{revalidation ? "Revalidação · " : ""}{tipo === "encontro" ? "Encontro" : tipo === "reencontro" ? "Reencontro" : "Batismo"}: validação humana</legend>
    <label>Data do {tipo}<input required name="data" type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
    <label><input type="checkbox" checked={prior} onChange={e => setPrior(e.target.checked)} />Anterior à turma</label>
    <label><input type="checkbox" name="confirmado" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Validei este marco da Pessoa</label>
    <button className="btn" disabled={disabled || !date || !confirmed}>{revalidation ? "Revalidar" : "Validar"} {tipo}</button>
  </fieldset></form>;
}

function Revoke({ base, disabled, request, run, reload }: Actions & { base: string }) {
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  return <form onSubmit={e => {
    e.preventDefault(); if (!reason.trim() || !confirmed || disabled) return;
    void run(async () => {
      await request(`${base}/marcos/reencontro/revogar`, "POST", { motivo: reason.trim() });
      await reload();
    });
  }}><fieldset disabled={disabled}><legend>Revogar validação de Reencontro</legend>
    <label>Motivo obrigatório<input required maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /></label>
    <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Confirmo a revogação definitiva desta evidência</label>
    <p>A liderança atual será preservada. Novas nomeações serão bloqueadas.</p>
    <button className="btn" disabled={disabled || !reason.trim() || !confirmed}>Revogar Reencontro</button>
  </fieldset></form>;
}
