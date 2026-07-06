/**
 * Cliente da API de reuniões de célula (Minha Célula — Discípulo e Líder).
 * Consome os endpoints do backend (cell_meetings.py + cell_discipulo.py):
 *
 *   POST   /cell-meetings                                  -> LeaderMeetingOut  (planejar)
 *   PUT    /cell-meetings/{id}                             -> LeaderMeetingOut  (editar)
 *   POST   /cell-meetings/{id}/attendance/confirm         -> AttendanceOut      (discípulo, 1 toque)
 *   DELETE /cell-meetings/{id}/attendance/confirm         -> AttendanceOut      (reverter)
 *   PUT    /cell-meetings/{id}/attendance                 -> SetAttendanceOut   (líder, presença real)
 *   POST   /cell-meetings/{id}/visitor-expectations       -> VisitorExpectationOut (discípulo, nominal)
 *   GET    /cell-meetings/{id}/visitor-expectations       -> VisitorExpectationsOut (líder)
 *   POST   /cell-meetings/{id}/visitors                   -> VisitorOut         (líder, registrar visitante)
 *   POST   /cell-meetings/{id}/records                    -> RecordOut          (líder)
 *   GET    /cell-meetings/{id}/records                    -> RecordsOut         (líder)
 *   PUT    /cell-meetings/{id}/report                     -> SaveReportOut      (draft)
 *   POST   /cell-meetings/{id}/report/submit              -> SubmitReportOut    (consolidar)
 *   GET    /cell-meetings/{id}/report                     -> ReportOut          (consolidado)
 *
 * Contratos espelham EXATAMENTE os schemas do backend: os endpoints do Discípulo
 * (attendance/confirm) e do PR2 (visitor-expectations) usam camelCase no request
 * (RegisterExpectativaRequest) e snake_case na saída; os endpoints do Líder usam
 * snake_case. Reaproveita o transporte autenticado (authedFetch) do dashboard-api.
 */

import {
  ApiError,
  authedFetch,
  isRecord,
  readDetail,
} from "./dashboard-api";

// ---------------------------------------------------------------------------
// Tipos — Discípulo (cell_discipulo.py, snake_case na saída)
// ---------------------------------------------------------------------------
/** Saída da confirmação/reversão de presença (AttendanceOut). */
export interface AttendanceOut {
  reuniao_id: string;
  /** `participou` | `faltou` | `confirmou` | `nao_confirmou` (E5). */
  minha_presenca: string;
}

/** Payload da expectativa nominal de visitante (RegisterExpectativaRequest). */
export interface IndicateVisitorInput {
  nomeVisitante: string;
  observacaoOracao?: string | null;
}

/** Saída da expectativa criada pelo próprio membro (VisitorExpectationOut). */
export interface VisitorExpectationOut {
  id: string;
  reuniao_id: string;
  nome_visitante: string;
  observacao_oracao: string | null;
}

// ---------------------------------------------------------------------------
// Tipos — Líder (cell_meetings.py, snake_case)
// ---------------------------------------------------------------------------
/** Reunião na visão do líder (LeaderMeetingOut). */
export interface LeaderMeetingOut {
  id: string;
  celula_id: string;
  /** ISO date (YYYY-MM-DD). */
  data: string;
  hora: string | null;
  tema: string | null;
  status: string;
  relatorio_status: string;
}

export interface PlanMeetingInput {
  celula_id: string;
  /** ISO date (YYYY-MM-DD). */
  data: string;
  hora?: string | null;
  tema?: string | null;
}

export interface UpdateMeetingInput {
  /** ISO date (YYYY-MM-DD). */
  data: string;
  hora?: string | null;
  tema?: string | null;
}

/** Entrada de presença real por membro (AttendanceEntry). */
export interface AttendanceEntry {
  pessoa_id: string;
  compareceu: boolean;
}

/** Saída da presença real gravada pelo líder (SetAttendanceOut). */
export interface SetAttendanceOut {
  meeting_id: string;
  presencas: AttendanceEntry[];
}

export interface RegisterVisitorInput {
  nome_visitante: string;
  expectativa_id?: string | null;
  observacao?: string | null;
}

/** Visitante registrado pelo líder (VisitorOut). */
export interface VisitorOut {
  id: string;
  reuniao_id: string;
  nome_visitante: string;
  expectativa_id: string | null;
}

/** Item da lista de expectativas de visitante da reunião (VisitorExpectationItem). */
export interface VisitorExpectationItem {
  id: string;
  nome_visitante: string;
  indicado_por: string;
  compareceu: boolean;
}

export interface VisitorExpectationsOut {
  expectations: VisitorExpectationItem[];
}

export interface AddRecordInput {
  tipo: string;
  conteudo: string;
  pessoa_id?: string | null;
}

/** Registro (decisão/oração/etc.) criado na reunião (RecordOut). */
export interface RecordOut {
  id: string;
  reuniao_id: string;
  tipo: string;
  conteudo: string;
  pessoa_id: string | null;
  autor_id: string | null;
}

/** Item de registro na listagem (RecordItem). */
export interface RecordItem {
  id: string;
  tipo: string;
  conteudo: string;
  pessoa_id: string | null;
}

export interface RecordsOut {
  records: RecordItem[];
}

export interface SaveReportInput {
  oferta_valor?: number | null;
  observacoes?: string | null;
}

/** Saída do rascunho do relatório salvo (SaveReportOut). */
export interface SaveReportOut {
  meeting_id: string;
  oferta_valor: number | null;
  observacoes: string | null;
  relatorio_status: string;
}

/** Saída do envio do relatório (SubmitReportOut). */
export interface SubmitReportOut {
  meeting_id: string;
  relatorio_status: string;
  relatorio_enviado_em: string | null;
  relatorio_enviado_por: string | null;
}

export interface ReportPresenca {
  pessoa_id: string;
  estado: string;
  origem: string | null;
}

export interface ReportVisitante {
  id: string;
  nome_visitante: string;
  expectativa_id: string | null;
  observacao: string | null;
}

export interface ReportRecord {
  id: string;
  tipo: string;
  conteudo: string;
  pessoa_id: string | null;
}

/** Relatório consolidado da reunião (ReportOut). */
export interface ReportOut {
  meeting_id: string;
  /** ISO date (YYYY-MM-DD). */
  data: string;
  tema: string | null;
  relatorio_status: string;
  oferta_valor: number | null;
  observacoes: string | null;
  presencas: ReportPresenca[];
  visitantes: ReportVisitante[];
  records: ReportRecord[];
}

/** Erro de conflito de estado (409) — ex.: reunião já ocorreu, relatório enviado. */
export class MeetingConflictError extends ApiError {
  constructor(message: string) {
    super(409, message);
    this.name = "MeetingConflictError";
  }
}

async function conflictMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (isRecord(body.detail) && typeof body.detail.message === "string") {
      return body.detail.message;
    }
  } catch {
    /* mantém fallback */
  }
  return fallback;
}

// ===========================================================================
// Discípulo — presença (1 toque, idempotente) e visitante nominal
// ===========================================================================
/**
 * Confirma a própria presença na reunião (1 toque). Idempotente: repetir mantém
 * `confirmou`. 409 se a reunião já ocorreu; 403 sem vínculo ativo na célula.
 */
export async function confirmAttendance(
  token: string,
  reuniaoId: string,
): Promise<AttendanceOut> {
  const res = await authedFetch(
    token,
    `/cell-meetings/${reuniaoId}/attendance/confirm`,
    { method: "POST", body: JSON.stringify({}) },
  );
  if (res.status === 409) {
    throw new MeetingConflictError(
      await conflictMessage(res, "A reunião já ocorreu; não é possível confirmar presença."),
    );
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível confirmar sua presença.");
  }
  return (await res.json()) as AttendanceOut;
}

/**
 * Reverte a confirmação da própria presença enquanto a reunião não ocorreu.
 * Idempotente: sem linha, responde 200 com `nao_confirmou`. 409 se já ocorreu.
 */
export async function revertAttendance(
  token: string,
  reuniaoId: string,
): Promise<AttendanceOut> {
  const res = await authedFetch(
    token,
    `/cell-meetings/${reuniaoId}/attendance/confirm`,
    { method: "DELETE" },
  );
  if (res.status === 409) {
    throw new MeetingConflictError(
      await conflictMessage(res, "A reunião já ocorreu; não é possível reverter a presença."),
    );
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível reverter sua presença.");
  }
  return (await res.json()) as AttendanceOut;
}

/**
 * Indica (nominalmente) um visitante do próprio membro para a reunião. Permite
 * N registros. 422 para nome inválido; 403 sem vínculo ativo na célula.
 */
export async function indicateVisitor(
  token: string,
  reuniaoId: string,
  input: IndicateVisitorInput,
): Promise<VisitorExpectationOut> {
  const res = await authedFetch(
    token,
    `/cell-meetings/${reuniaoId}/visitor-expectations`,
    {
      method: "POST",
      body: JSON.stringify({
        nomeVisitante: input.nomeVisitante,
        observacaoOracao: input.observacaoOracao ?? null,
      }),
    },
  );
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível indicar o visitante.");
  }
  return (await res.json()) as VisitorExpectationOut;
}

// ===========================================================================
// Líder — planejar/editar reunião
// ===========================================================================
export async function planMeeting(
  token: string,
  input: PlanMeetingInput,
): Promise<LeaderMeetingOut> {
  const res = await authedFetch(token, `/cell-meetings`, {
    method: "POST",
    body: JSON.stringify({
      celula_id: input.celula_id,
      data: input.data,
      hora: input.hora ?? null,
      tema: input.tema ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível planejar a reunião.");
  }
  return (await res.json()) as LeaderMeetingOut;
}

export async function updateMeeting(
  token: string,
  reuniaoId: string,
  input: UpdateMeetingInput,
): Promise<LeaderMeetingOut> {
  const res = await authedFetch(token, `/cell-meetings/${reuniaoId}`, {
    method: "PUT",
    body: JSON.stringify({
      data: input.data,
      hora: input.hora ?? null,
      tema: input.tema ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível editar a reunião.");
  }
  return (await res.json()) as LeaderMeetingOut;
}

// ===========================================================================
// Líder — presença real, visitantes, registros
// ===========================================================================
export async function setRealAttendance(
  token: string,
  reuniaoId: string,
  presencas: AttendanceEntry[],
): Promise<SetAttendanceOut> {
  const res = await authedFetch(token, `/cell-meetings/${reuniaoId}/attendance`, {
    method: "PUT",
    body: JSON.stringify({ presencas }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar a presença.");
  }
  return (await res.json()) as SetAttendanceOut;
}

export async function getVisitorExpectations(
  token: string,
  reuniaoId: string,
): Promise<VisitorExpectationsOut> {
  const res = await authedFetch(
    token,
    `/cell-meetings/${reuniaoId}/visitor-expectations`,
  );
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar as expectativas.");
  }
  return (await res.json()) as VisitorExpectationsOut;
}

export async function registerVisitor(
  token: string,
  reuniaoId: string,
  input: RegisterVisitorInput,
): Promise<VisitorOut> {
  const res = await authedFetch(token, `/cell-meetings/${reuniaoId}/visitors`, {
    method: "POST",
    body: JSON.stringify({
      nome_visitante: input.nome_visitante,
      expectativa_id: input.expectativa_id ?? null,
      observacao: input.observacao ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível registrar o visitante.");
  }
  return (await res.json()) as VisitorOut;
}

export async function addRecord(
  token: string,
  reuniaoId: string,
  input: AddRecordInput,
): Promise<RecordOut> {
  const res = await authedFetch(token, `/cell-meetings/${reuniaoId}/records`, {
    method: "POST",
    body: JSON.stringify({
      tipo: input.tipo,
      conteudo: input.conteudo,
      pessoa_id: input.pessoa_id ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível adicionar o registro.");
  }
  return (await res.json()) as RecordOut;
}

export async function getRecords(
  token: string,
  reuniaoId: string,
): Promise<RecordsOut> {
  const res = await authedFetch(token, `/cell-meetings/${reuniaoId}/records`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar os registros.");
  }
  return (await res.json()) as RecordsOut;
}

// ===========================================================================
// Líder — ciclo do relatório (draft → submit → consolidado)
// ===========================================================================
export async function saveReport(
  token: string,
  reuniaoId: string,
  input: SaveReportInput,
): Promise<SaveReportOut> {
  const res = await authedFetch(token, `/cell-meetings/${reuniaoId}/report`, {
    method: "PUT",
    body: JSON.stringify({
      oferta_valor: input.oferta_valor ?? null,
      observacoes: input.observacoes ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar o relatório.");
  }
  return (await res.json()) as SaveReportOut;
}

export async function submitReport(
  token: string,
  reuniaoId: string,
): Promise<SubmitReportOut> {
  const res = await authedFetch(
    token,
    `/cell-meetings/${reuniaoId}/report/submit`,
    { method: "POST", body: JSON.stringify({}) },
  );
  if (res.status === 409) {
    throw new MeetingConflictError(
      await conflictMessage(res, "O relatório já foi enviado e está bloqueado para edição."),
    );
  }
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível enviar o relatório.");
  }
  return (await res.json()) as SubmitReportOut;
}

export async function getReport(
  token: string,
  reuniaoId: string,
): Promise<ReportOut> {
  const res = await authedFetch(token, `/cell-meetings/${reuniaoId}/report`);
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível carregar o relatório.");
  }
  return (await res.json()) as ReportOut;
}
