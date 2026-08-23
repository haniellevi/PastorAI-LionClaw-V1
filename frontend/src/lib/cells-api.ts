/**
 * Cliente da API de células (#celulas — F7 / delta-007).
 * Consome os endpoints do backend (sprint-004):
 *
 *   GET  /cells                                  -> Page<CellSummary>
 *   GET  /cells/{id}                             -> CellDetail (com alerts)
 *   POST /cells                                  -> CellSummary  (upsert)
 *   POST /cells/{id}/membros                     -> CellMembro   (vínculo)
 *   POST /cells/{id}/alerts/{aid}/baixar         -> CellAlert    (tratado=true)
 *
 * Reaproveita o transporte autenticado (authedFetch) e o tratamento de 401
 * do dashboard-api. Editar célula exige líder-ou-superior (403); criar exige
 * papel de liderança pastoral. cobertura_espiritual é obrigatória (422/edge).
 */

import {
  ApiError,
  authedFetch,
  readDetail,
  type Page,
} from "./dashboard-api";

export type { Page } from "./dashboard-api";

/** Projeção de célula retornada por /cells (CellOut). */
export interface CellSummary {
  id: string;
  nome: string;
  liderId: string | null;
  diaReuniao: string | null;
  /** HH:MM (o backend valida o formato). */
  horario: string | null;
  coberturaEspiritual: string;
  ativo: boolean;
}

/** Alerta aberto sobre um liderado da célula (cell_alerts). */
export interface CellAlert {
  id: string;
  pessoaId: string;
  gatilho: string | null;
  acaoEsperada: string | null;
  tratado: boolean;
}

/** Detalhe da célula com seus alertas em aberto. */
export interface CellDetail extends CellSummary {
  alerts: CellAlert[];
}

/** Entrada para criar (sem id) ou editar (com id) uma célula. */
export interface UpsertCellInput {
  id?: string | null;
  nome: string;
  liderId?: string | null;
  diaReuniao?: string | null;
  /** HH:MM. Sensível (3.2): junto com diaReuniao, só a Central altera. */
  horario?: string | null;
  coberturaEspiritual: string;
  ativo?: boolean;
}

// ---------------------------------------------------------------------------
// Leitura
// ---------------------------------------------------------------------------
export async function fetchCellsFull(
  token: string,
  pageSize = 200,
): Promise<Page<CellSummary>> {
  const res = await authedFetch(token, `/cells?page=1&pageSize=${pageSize}`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar as células.");
  }
  return (await res.json()) as Page<CellSummary>;
}

export async function fetchCellDetail(
  token: string,
  cellId: string,
): Promise<CellDetail> {
  const res = await authedFetch(token, `/cells/${cellId}`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível abrir a célula.");
  }
  return (await res.json()) as CellDetail;
}

/** Vínculo ativo em celula_membro — projeção do MemberOut do backend (camelCase). */
export interface CellMembro {
  id: string;
  pessoaId: string;
  papel: string;
  ativo: boolean;
}

/**
 * Vínculos ATIVOS da célula pela fonte canônica `celula_membro`
 * (GET /cells/{id}/membros). É a leitura da Central — distinta de
 * getCellMembers (/members), exclusiva do líder da própria célula. Não traz o
 * nome; resolva o pessoaId contra os contatos já carregados.
 */
export async function fetchCellMembros(
  token: string,
  cellId: string,
): Promise<CellMembro[]> {
  const res = await authedFetch(token, `/cells/${cellId}/membros`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os discípulos.");
  }
  return (await res.json()) as CellMembro[];
}

/**
 * Vincula uma Pessoa já cadastrada à célula. Esta operação não cria usuário,
 * convite ou acesso ao painel; acesso continua sendo responsabilidade de
 * `/team/invite` na tela de Equipe.
 */
export async function addCellMember(
  token: string,
  cellId: string,
  pessoaId: string,
): Promise<CellMembro> {
  const res = await authedFetch(token, `/cells/${cellId}/membros`, {
    method: "POST",
    body: JSON.stringify({ pessoaId }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível adicionar a pessoa à célula.");
  }
  return (await res.json()) as CellMembro;
}

/**
 * Transfere um membro da célula atual para a destino (Células pós-V1 — Central).
 * Execução direta: desativa o vínculo na origem, cria no destino, atualiza o
 * espelho e grava auditoria, na mesma transação. ``motivo`` é opcional.
 */
export async function transferCellMember(
  token: string,
  cellId: string,
  pessoaId: string,
  celulaDestinoId: string,
  motivo?: string,
): Promise<CellMembro> {
  const res = await authedFetch(token, `/cells/${cellId}/membros/transferir`, {
    method: "POST",
    body: JSON.stringify({
      pessoaId,
      celula_destino_id: celulaDestinoId,
      ...(motivo ? { motivo } : {}),
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível transferir o membro.");
  }
  return (await res.json()) as CellMembro;
}

/**
 * Remove um membro da célula (Células pós-V1 — Central). Execução direta:
 * desativa o vínculo, limpa o espelho ``pessoas.celula_id`` e grava auditoria,
 * na mesma transação. A pessoa NÃO é deletada. ``motivo`` é opcional.
 */
export async function removeCellMember(
  token: string,
  cellId: string,
  pessoaId: string,
  motivo?: string,
): Promise<CellMembro> {
  const res = await authedFetch(token, `/cells/${cellId}/membros/remover`, {
    method: "POST",
    body: JSON.stringify({
      pessoaId,
      ...(motivo ? { motivo } : {}),
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível remover o membro.");
  }
  return (await res.json()) as CellMembro;
}

// ---------------------------------------------------------------------------
// Escrita
// ---------------------------------------------------------------------------
/**
 * Cria ou edita uma célula. cobertura_espiritual é obrigatória. Editar uma
 * célula existente exige líder-ou-superior na hierarquia (403 com motivo).
 */
export async function upsertCell(
  token: string,
  input: UpsertCellInput,
): Promise<CellSummary> {
  const res = await authedFetch(token, `/cells`, {
    method: "POST",
    body: JSON.stringify({
      id: input.id ?? null,
      nome: input.nome,
      liderId: input.liderId ?? null,
      diaReuniao: input.diaReuniao ?? null,
      horario: input.horario ?? null,
      coberturaEspiritual: input.coberturaEspiritual,
      ativo: input.ativo ?? true,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar a célula.");
  }
  return (await res.json()) as CellSummary;
}

/** Marca um alerta da célula como tratado (tratado=true). */
export async function baixarAlert(
  token: string,
  cellId: string,
  alertId: string,
): Promise<CellAlert> {
  const res = await authedFetch(
    token,
    `/cells/${cellId}/alerts/${alertId}/baixar`,
    { method: "POST", body: JSON.stringify({}) },
  );
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível tratar o alerta.");
  }
  return (await res.json()) as CellAlert;
}

// ===========================================================================
// Minha Célula — domínio Discípulo (Células PR3)
// Contrato snake_case, espelhando exatamente os schemas do backend
// (app/routers/cell_discipulo.py e cell_meetings.py::MembersOut).
// ===========================================================================

/** Corpo da próxima reunião futura (NextMeetingBody). */
export interface NextMeetingBody {
  id: string;
  celula_id: string;
  /** ISO date (YYYY-MM-DD). */
  data: string;
  /** HH:MM ou null. */
  hora: string | null;
  /** Endereço da célula (leitura permitida ao discípulo), ou null. */
  local: string | null;
  tema: string | null;
  /** Presença do próprio membro (E5): confirmou|participou|faltou|nao_confirmou.
   *  Inicializa o botão de confirmação sem um 2º request. */
  minha_presenca: string;
}

/** Envelope da próxima reunião: `meeting` é null quando não houver. */
export interface NextMeetingResponse {
  meeting: NextMeetingBody | null;
}

/**
 * Rótulo da própria presença numa reunião passada (E5):
 * `participou` | `faltou` | `confirmou` | `nao_confirmou`.
 */
export type MinhaPresenca =
  | "participou"
  | "faltou"
  | "confirmou"
  | "nao_confirmou";

/** Item MINIMIZADO do histórico (só dados do próprio membro). */
export interface HistoryItem {
  /** ISO date (YYYY-MM-DD). */
  data: string;
  tema: string | null;
  minha_presenca: string;
  meus_visitantes_indicados: string[];
}

/** Página do histórico de reuniões passadas do discípulo (snake_case). */
export interface HistoryPage {
  items: HistoryItem[];
  page: number;
  page_size: number;
  total: number;
}

/** Membro de uma célula (MemberItem). */
export interface CellMember {
  pessoa_id: string;
  nome: string;
  ativo: boolean;
}

/** Lista de membros de uma célula (MembersOut). */
export interface CellMembersOut {
  members: CellMember[];
}

/**
 * Próxima reunião FUTURA da célula do discípulo. "Sem célula" ou "sem ocorrência
 * futura" são estados válidos e retornam `{ meeting: null }` (não erro).
 */
export async function getNextMeeting(
  token: string,
): Promise<NextMeetingResponse> {
  const res = await authedFetch(token, `/cells/me/next-meeting`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar a próxima reunião.");
  }
  return (await res.json()) as NextMeetingResponse;
}

/** Célula que o usuário LIDERA (via celulas.lider_id). */
export interface LedCell {
  id: string;
  nome: string;
}

/**
 * Células cujo líder é a Pessoa do usuário autenticado (fonte autoritativa da
 * célula LIDERADA — distinta da célula onde ele é MEMBRO). Lista vazia quando
 * não lidera nenhuma.
 */
export async function getMyLedCells(token: string): Promise<LedCell[]> {
  const res = await authedFetch(token, `/cells/me/leading`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível resolver sua célula.");
  }
  return (await res.json()) as LedCell[];
}

/** Contexto agregado das células que o usuário realmente lidera. */
export interface LedCellsTodayContext {
  cells: LedCell[];
  meeting: NextMeetingBody | null;
}

function meetingSlot(reuniao: Reuniao): number {
  const time = reuniao.hora ?? "23:59";
  return new Date(`${reuniao.data}T${time}:00`).getTime();
}

/**
 * Resolve a próxima reunião entre TODAS as células lideradas pelo ator.
 *
 * Não consulta `/cells/me/next-meeting`: esse endpoint representa a célula em
 * que a pessoa é membro e pode apontar para outra célula. Em empate, a ordem é
 * estável por nome/id da célula e id da reunião.
 */
export async function getLedCellsTodayContext(
  token: string,
  now = new Date(),
): Promise<LedCellsTodayContext> {
  const cells = [...(await getMyLedCells(token))].sort(
    (a, b) =>
      a.nome.localeCompare(b.nome, "pt-BR", { sensitivity: "base" }) ||
      a.id.localeCompare(b.id),
  );
  if (cells.length === 0) return { cells, meeting: null };

  const meetingsByCell = await Promise.all(
    cells.map(async (cell) => ({ cell, meetings: await listReunioes(token, cell.id) })),
  );
  const nowTime = now.getTime();
  const next = meetingsByCell
    .flatMap(({ cell, meetings }) =>
      meetings.map((reuniao) => ({ cell, reuniao, slot: meetingSlot(reuniao) })),
    )
    .filter(({ slot }) => Number.isFinite(slot) && slot >= nowTime)
    .sort(
      (a, b) =>
        a.slot - b.slot ||
        a.cell.nome.localeCompare(b.cell.nome, "pt-BR", { sensitivity: "base" }) ||
        a.cell.id.localeCompare(b.cell.id) ||
        a.reuniao.id.localeCompare(b.reuniao.id),
    )[0];

  if (!next) return { cells, meeting: null };
  return {
    cells,
    meeting: {
      id: next.reuniao.id,
      celula_id: next.cell.id,
      data: next.reuniao.data,
      hora: next.reuniao.hora,
      local: null,
      tema: `${next.cell.nome}: ${next.reuniao.tema ?? "Reunião da célula"}`,
      // A presença pessoal não faz parte do contrato de leitura do líder e não
      // é exibida pelo dashboard; mantemos o estado neutro do schema compartilhado.
      minha_presenca: "nao_confirmou",
    },
  };
}

/**
 * Histórico paginado das reuniões PASSADAS do membro (projeção mínima).
 * Mais recentes primeiro. Sem célula → página vazia (não erro).
 */
export async function getMyHistory(
  token: string,
  page = 1,
  pageSize = 20,
): Promise<HistoryPage> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  const res = await authedFetch(token, `/cells/me/history?${query.toString()}`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar o histórico.");
  }
  return (await res.json()) as HistoryPage;
}

/** Lista os membros de uma célula (reuso do endpoint do líder — leitura). */
export async function getCellMembers(
  token: string,
  cellId: string,
): Promise<CellMembersOut> {
  const res = await authedFetch(token, `/cells/${cellId}/members`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os membros.");
  }
  return (await res.json()) as CellMembersOut;
}

/**
 * Reunião de uma célula (ReuniaoOut, camelCase). Contrato do endpoint
 * `GET /cells/{cellId}/reunioes` (cell_meetings.py), aberto a qualquer
 * autenticado do tenant. Ordenado do mais recente para o mais antigo.
 */
export interface Reuniao {
  id: string;
  celulaId: string;
  /** ISO date (YYYY-MM-DD). */
  data: string;
  hora: string | null;
  tema: string | null;
  status: string;
}

/**
 * Lista TODAS as reuniões (passadas e futuras) de uma célula — base do painel
 * do líder para escolher a reunião a relatar. Sem paginação (BK-DEC-02).
 */
export async function listReunioes(
  token: string,
  cellId: string,
): Promise<Reuniao[]> {
  const res = await authedFetch(token, `/cells/${cellId}/reunioes`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar as reuniões.");
  }
  return (await res.json()) as Reuniao[];
}
