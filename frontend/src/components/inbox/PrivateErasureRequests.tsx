"use client";

import { useCallback, useEffect, useState } from "react";
import { Dialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import { SessionExpiredError } from "@/lib/api";
import { authedFetch } from "@/lib/dashboard-api";

type Request = {
  id: string;
  state: "pendente" | "aprovado" | "recusado";
  created_at: string;
  idade_segundos: number;
  prazo_dias: number;
  prazo_versao: string;
  vencido: boolean;
  receipt: { estado: string; fora_do_alcance: string } | null;
};
type Props = { token: string; personId: string; expireSession: () => void };

export function PrivateErasureRequests(props: Props) {
  return <Requests key={`${props.personId}:${props.token}`} {...props} />;
}

function age(seconds: number): string {
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return `${Math.floor(seconds / 86400)} d e ${Math.floor(seconds % 86400 / 3600)} h`;
}

function Requests({ token, personId, expireSession }: Props) {
  const [items, setItems] = useState<Request[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [choice, setChoice] = useState<{ id: string; approve: boolean } | null>(null);
  const load = useCallback(async (signal?: AbortSignal) => {
    const response = await authedFetch(token, `/contacts/${personId}/private-erasure-requests`, { cache: "no-store", signal });
    // An older backend has no requests yet.
    if (response.status === 404) return [];
    if (!response.ok) throw new Error("read_failed");
    return (await response.json() as { items: Request[] }).items;
  }, [token, personId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).then(rows => {
      if (!controller.signal.aborted) setItems(rows);
    }).catch(cause => {
      if (controller.signal.aborted) return;
      if (cause instanceof SessionExpiredError) expireSession();
      else setError("Não foi possível consultar os pedidos. Tente atualizar.");
    });
    return () => controller.abort();
  }, [load, expireSession]);

  async function refresh() {
    setBusy(true); setError(null);
    try { setItems(await load()); }
    catch (cause) {
      if (cause instanceof SessionExpiredError) expireSession();
      else setError("Não foi possível atualizar os pedidos. Tente novamente.");
    } finally { setBusy(false); }
  }

  async function decide() {
    if (!choice) return;
    setBusy(true); setError(null);
    try {
      const response = await authedFetch(token, `/private-erasure-requests/${choice.id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision: choice.approve ? "aprovado" : "recusado", confirmacao: "DECIDIR PEDIDO DE EXCLUSAO" }),
      });
      if (!response.ok) throw new Error("decision_failed");
      const result = await response.json() as Pick<Request, "id" | "state" | "receipt">;
      setItems(rows => rows.map(row => row.id === result.id ? { ...row, ...result, vencido: false } : row));
      setChoice(null);
    } catch (cause) {
      if (cause instanceof SessionExpiredError) expireSession();
      else setError("Não foi possível confirmar a decisão. Atualize o pedido ou tente novamente; repetir a decisão é seguro.");
    } finally { setBusy(false); }
  }

  if (!items.length && !error) return null;
  return <section className="panel-section">
    <h4>Pedidos de exclusão</h4>
    <Button size="sm" onClick={() => void refresh()} disabled={busy}>Atualizar pedidos</Button>
    {items.map(row => <div key={row.id}>
      <p>Pedido de {new Date(row.created_at).toLocaleDateString("pt-BR")}: {row.state}.</p>
      <p>Idade: {age(row.idade_segundos)}. Prazo de atendimento: {row.prazo_dias} dias.</p>
      {row.state === "pendente" && row.vencido ? <p><strong className="pill danger" role="status">Prazo vencido</strong></p> : null}
      {row.state === "pendente" ? <>
        <p>Uso da memória suspenso até a decisão. O conteúdo ainda está preservado.</p>
        <Button size="sm" variant="danger" disabled={busy} onClick={() => setChoice({ id: row.id, approve: true })}>Aprovar exclusão</Button>
        <Button size="sm" disabled={busy} onClick={() => setChoice({ id: row.id, approve: false })}>Recusar pedido</Button>
      </> : null}
      {row.state === "recusado" ? <p>Suspensão encerrada. A memória continua sujeita à validação de origem e acesso.</p> : null}
      {row.receipt ? <>
        <p>{row.receipt.estado === "concluido" ? "Exclusão concluída no alcance operacional." : row.receipt.estado === "pendente_envio" ? "Envio em andamento: recibo pendente." : "Limpeza externa pendente. Atualize para acompanhar."}</p>
        <p>Fora do alcance: {row.receipt.fora_do_alcance}.</p>
      </> : null}
    </div>)}
    {!choice && error ? <p role="alert">{error}</p> : null}
    <Dialog open={choice !== null} onClose={() => { if (!busy) { setChoice(null); setError(null); } }}
      title={choice?.approve ? "Aprovar exclusão do conteúdo privado?" : "Recusar pedido de exclusão?"}
      footer={<>
        <Button disabled={busy} onClick={() => { setChoice(null); setError(null); }}>Cancelar</Button>
        <Button variant={choice?.approve ? "danger" : "default"} loading={busy} onClick={() => void decide()}>
          {choice?.approve ? "Confirmar exclusão" : "Confirmar recusa"}
        </Button>
      </>}>
      <p>{choice?.approve
        ? "Serão excluídas todas as conversas, áudios, transcrições e resumos privados desta pessoa nesta igreja. Esta ação não pode ser desfeita. Cadastro, opt-out e prova de consentimento sem conteúdo são preservados."
        : "O pedido será encerrado e a suspensão da memória será removida. O conteúdo será preservado."}</p>
      {error ? <p role="alert">{error}</p> : null}
    </Dialog>
  </section>;
}
