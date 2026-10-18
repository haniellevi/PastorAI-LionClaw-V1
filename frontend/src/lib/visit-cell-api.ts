import { ApiError, authedFetch, readDetail } from "./dashboard-api";

export interface VisitCellSuggestion {
  pessoa_id: string;
  pessoa_nome: string;
  evento_id: string;
  celula_id: string | null;
  celula_nome: string | null;
  data_ocorrencia: string;
  revision: string;
  blocked_reason: string | null;
  already_linked: boolean;
}
export interface VisitCellPage {
  items: VisitCellSuggestion[];
  page: number;
  page_size: number;
  total: number;
}
export async function readVisitSuggestions(token: string, personId: string | undefined, page: number): Promise<VisitCellPage> {
  const path = personId ? `/contacts/${personId}/visit-cell-suggestion` : `/cell-central/visit-cell-suggestions?page=${page}&page_size=20`;
  const res = await authedFetch(token, path);
  if (!res.ok) throw new ApiError(res.status, (await readDetail(res)) ?? "Não foi possível concluir a solicitação.");
  const data = await res.json();
  return personId ? {items: data ? [data] : [], page: 1, page_size: 1, total: data ? 1 : 0} : data;
}
export async function confirmVisitCell(token: string, item: VisitCellSuggestion): Promise<void> {
  const res = await authedFetch(token, `/contacts/${item.pessoa_id}/visit-cell-suggestion/confirm`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({evento_id: item.evento_id, celula_id: item.celula_id, revision: item.revision}),
  });
  if (!res.ok) throw new ApiError(res.status, (await readDetail(res)) ?? "Não foi possível concluir a solicitação.");
}
