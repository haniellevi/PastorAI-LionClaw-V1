"use client";

import { useEffect, useState } from "react";
import { DsButton } from "@/components/ds/Button";
import { authedFetch } from "@/lib/dashboard-api";
import { PrivateChurchContentReset } from "./PrivateChurchContentReset";

interface MemoryOverview {
  pedidos_exclusao: {
    pendentes: number;
    vencidos: number;
    prazo_dias: number;
    prazo_versao: string;
    atendidos: number;
    recusados: number;
    mais_antigo_segundos: number | null;
    faixas_idade: { menos_24h: number; de_1_a_3_dias: number; mais_3_dias: number };
  };
  resumos_ativos: number;
  retomadas_entregues: number;
  tarefas_resumo: { queued: number; running: number; done: number; refused: number };
  limpezas_privadas: { pendente: number; concluida: number };
}

function age(seconds: number): string {
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return `${Math.floor(seconds / 86400)} d e ${Math.floor(seconds % 86400 / 3600)} h`;
}

/** Mounted only for admins by Hoje. Backend independently authorizes every read. */
export function PrivateMemoryIndicator({ token, churchName, onSessionError }: {
  token: string;
  churchName: string | null;
  onSessionError: (error: unknown) => unknown;
}) {
  const [attempt, setAttempt] = useState(0);
  const [resetOpen, setResetOpen] = useState(false);
  const [result, setResult] = useState<{
    token: string; attempt: number; data: MemoryOverview | null;
  } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await authedFetch(token, "/operations/private-memory", {
          cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) throw new Error("memory_overview_unavailable");
        const data = await response.json() as MemoryOverview;
        if (!controller.signal.aborted) setResult({ token, attempt, data });
      } catch (error) {
        if (controller.signal.aborted) return;
        onSessionError(error);
        setResult({ token, attempt, data: null });
      }
    }
    void load();
    return () => controller.abort();
  }, [token, attempt, onSessionError]);
  const current = result?.token === token && result.attempt === attempt ? result : null;
  const data = current?.data;
  const requests = data?.pedidos_exclusao;
  return (
    <section className="dh-panel" aria-label="Memória privada" aria-busy={!current}>
      <header className="dh-panel-head"><h3 className="dh-panel-title">Memória privada</h3></header>
      <div className="dh-context-body">
        {!current ? <p role="status">Carregando contagens da memória…</p> : !data || !requests ? (
          <p role="status">Contagens da memória indisponíveis agora.</p>
        ) : <>
          <p>{requests.pendentes === 0 ? "Nenhum pedido de exclusão pendente."
            : `${requests.pendentes} ${requests.pendentes === 1 ? "pedido de exclusão pendente" : "pedidos de exclusão pendentes"}.`}</p>
          <p>{requests.atendidos} atendidos e {requests.recusados} recusados.</p>
          <p><strong>{requests.vencidos} {requests.vencidos === 1 ? "pedido vencido" : "pedidos vencidos"}.</strong> Prazo configurado: {requests.prazo_dias} dias.</p>
          {requests.mais_antigo_segundos !== null ? <p>Pedido pendente mais antigo: {age(requests.mais_antigo_segundos)}.</p> : null}
          <ul aria-label="Idade dos pedidos pendentes">
            <li>Menos de 24 h: {requests.faixas_idade.menos_24h}</li>
            <li>De 1 a 3 dias: {requests.faixas_idade.de_1_a_3_dias}</li>
            <li>Mais de 3 dias: {requests.faixas_idade.mais_3_dias}</li>
          </ul>
          <p>Atendidos têm decisão aprovada; a limpeza pode continuar pendente no recibo.</p>
          <details>
            <summary>Contagens do acervo privado</summary>
            <p>Resumos disponíveis ou corrigidos, sem pedido pendente: {data.resumos_ativos}.</p>
            <p>Retomadas entregues no acervo atual: {data.retomadas_entregues}.</p>
            <ul aria-label="Tarefas de resumo por estado">
              <li>Na fila: {data.tarefas_resumo.queued}</li>
              <li>Em execução: {data.tarefas_resumo.running}</li>
              <li>Concluídas: {data.tarefas_resumo.done}</li>
              <li>Recusadas: {data.tarefas_resumo.refused}</li>
            </ul>
            <p>Limpezas privadas: {data.limpezas_privadas.pendente} pendentes e {data.limpezas_privadas.concluida} concluídas.</p>
          </details>
        </>}
        <DsButton variant="secondary" disabled={!current} onClick={() => setAttempt(value => value + 1)}>
          {current && !data ? "Tentar novamente" : "Atualizar contagens"}
        </DsButton>
        <p>No Atendimento, abra os dados do contato para aprovar ou recusar o pedido.</p>
        <a className="dh-shortcut" href="#inbox">Decidir pedidos no Atendimento</a>
        {churchName ? <DsButton variant="secondary" onClick={() => setResetOpen(true)}>
          Resetar conteúdo privado da igreja
        </DsButton> : <p>Reset da igreja indisponível sem o nome canônico da sessão.</p>}
      </div>
      {churchName ? <PrivateChurchContentReset open={resetOpen} token={token} churchName={churchName}
        onClose={() => setResetOpen(false)} onErased={() => setAttempt(value => value + 1)}
        onSessionError={onSessionError} /> : null}
    </section>
  );
}
