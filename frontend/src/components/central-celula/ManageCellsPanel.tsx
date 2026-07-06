"use client";

/**
 * Aba "Gerenciar células" da Central. Empilha, no mesmo código-base (desktop e
 * mobile), as três listas de acompanhamento:
 *   • CellHealthList (US-18) — saúde com até 10 bolinhas, menos saudáveis primeiro;
 *   • PendingReportsList (US-16) — relatórios pendentes (célula/líder/reunião);
 *   • MultiplicationsList (US-19) — multiplicações pendentes e registradas.
 * Cada lista carrega e trata loading/empty/error por conta própria.
 */
import { CellHealthList } from "./CellHealthList";
import { PendingReportsList } from "./PendingReportsList";
import { MultiplicationsList } from "./MultiplicationsList";

export function ManageCellsPanel({ token }: { token: string }) {
  return (
    <div className="central-stack">
      <CellHealthList token={token} />
      <PendingReportsList token={token} />
      <MultiplicationsList token={token} />
    </div>
  );
}
