"use client";

/**
 * Minha Célula — visão do LÍDER (Células PR: Líder). Orquestra a gestão da célula:
 *   • planejar reunião pontual (US-06) e relatar a reunião em etapas (US-07..11);
 *   • discípulos (US-12) e campos sensíveis via Solicitação (US-13/14);
 *   • publicar/inativar avisos da célula (US-12A/12B) e ler materiais (US-21).
 *
 * O `celula_id` do líder não vem de /auth/me; é resolvido no cliente a partir da
 * próxima reunião, das solicitações ou dos avisos (primeira fonte disponível).
 * Campos sensíveis NUNCA são salvos direto — abrem a Solicitação (RF-14).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Tabs } from "@/components/ds/Tabs";
import { DsToast, DsToastRegion } from "@/components/ds/Toast";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/lib/icons";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import {
  getMyLedCells,
  getNextMeeting,
  getCellMembers,
  listReunioes,
  fetchCellDetail,
  type CellMember,
  type Reuniao,
} from "@/lib/cells-api";
import { listRequests } from "@/lib/cell-requests-api";
import { listNotices } from "@/lib/cell-notices-api";
import { listMaterials, type Material } from "@/lib/cell-materials-api";
import type { LeaderMeetingOut } from "@/lib/cell-meetings-api";

import { PlanMeetingModal } from "./PlanMeetingModal";
import { MeetingReportForm } from "./MeetingReportForm";
import { DisciplesList } from "./DisciplesList";
import { CellNoticeForm } from "./CellNoticeForm";
import { LeaderNoticesFeed } from "./LeaderNoticesFeed";
import { MyRequestsList } from "./MyRequestsList";
import {
  SensitiveFieldRequestModal,
  type SensitiveCellRequestType,
} from "./SensitiveFieldRequestModal";
import { MultiplicationRequestModal } from "./MultiplicationRequestModal";
import { MaterialsFeed } from "./MaterialsFeed";
import { formatMeetingDate } from "./format";
import type { CellToast } from "./types";

/** Contexto exibido no cabeçalho da célula (nome + dados de agenda/cobertura). Os
 *  campos sensíveis vêm de fetchCellDetail; nome tem fallback via getMyLedCells.
 *  Endereço e nº de visitantes ainda não existem na API do líder (lacuna). */
type CellContext = {
  nome: string;
  diaReuniao: string | null;
  horario: string | null;
  coberturaEspiritual: string | null;
};

type LeaderArea =
  | "relatorio"
  | "pessoas"
  | "avisos"
  | "materiais"
  | "solicitacoes"
  | "dados";

/** Campos sensíveis da célula (viram Solicitação, RF-14). */
const CELL_SENSITIVE: { tipo: SensitiveCellRequestType; label: string }[] = [
  { tipo: "alterar_dia", label: "Alterar dia" },
  { tipo: "alterar_horario", label: "Alterar horário" },
  { tipo: "alterar_endereco", label: "Alterar endereço" },
  { tipo: "alterar_anfitriao", label: "Alterar anfitrião" },
  { tipo: "alterar_auxiliar", label: "Alterar auxiliar" },
];

export function MinhaCelulaLider() {
  const { token, expireSession } = useAuth();

  const [cellId, setCellId] = useState<string | null>(null);
  const [members, setMembers] = useState<CellMember[]>([]);
  const [reunioes, setReunioes] = useState<Reuniao[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [cellCtx, setCellCtx] = useState<CellContext | null>(null);
  const [selectedReuniaoId, setSelectedReuniaoId] = useState<string>("");
  const [activeArea, setActiveArea] = useState<LeaderArea>("relatorio");

  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showPlan, setShowPlan] = useState(false);
  const [showMult, setShowMult] = useState(false);
  const [sensitive, setSensitive] = useState<SensitiveCellRequestType | null>(null);
  const [requestsReload, setRequestsReload] = useState(0);
  const [noticesReload, setNoticesReload] = useState(0);

  // Gate 9.1: sem timer manual — o DsToast e o dono do ciclo de vida
  // (ok auto-dismiss 3600ms; err persistente ate fechar).
  const [toast, setToast] = useState<CellToast | null>(null);
  const flashToast = useCallback((t: CellToast) => setToast(t), []);

  const handleSessionError = useCallback(
    (err: unknown): boolean => {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return true;
      }
      return false;
    },
    [expireSession],
  );

  /** Resolve o `celula_id` do líder. Fonte AUTORITATIVA = célula que ele LIDERA
   *  (celulas.lider_id); as demais são só fallback e derivam de MEMBRESIA, que
   *  para um líder que também é membro da célula do seu líder resolveria a célula
   *  errada. */
  const resolveCell = useCallback(async (): Promise<{
    id: string;
    nome: string | null;
  } | null> => {
    const led = await getMyLedCells(token!);
    if (led[0]?.id) return { id: led[0].id, nome: led[0].nome };
    const next = await getNextMeeting(token!);
    if (next.meeting?.celula_id) return { id: next.meeting.celula_id, nome: null };
    const reqs = await listRequests(token!);
    if (reqs.items[0]?.celula_id) return { id: reqs.items[0].celula_id, nome: null };
    const notices = await listNotices(token!);
    const withCell = notices.items.find((n) => n.celula_id);
    return withCell?.celula_id ? { id: withCell.celula_id, nome: null } : null;
  }, [token]);

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (!token) return;
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const resolved = await resolveCell();
        if (!resolved) {
          setCellId(null);
          setLoaded(true);
          return;
        }
        setCellId(resolved.id);

        // Detalhe (dia/horário/cobertura) é opcional para o hero: se a leitura
        // falhar, o painel segue com nome + contadores (não quebra a tela).
        const [membersRes, reunioesRes, materialsRes, detail] = await Promise.all([
          getCellMembers(token, resolved.id),
          listReunioes(token, resolved.id),
          listMaterials(token),
          fetchCellDetail(token, resolved.id).catch(() => null),
        ]);
        setMembers(membersRes.members);
        setReunioes(reunioesRes);
        setMaterials(materialsRes.items);
        setCellCtx({
          nome: detail?.nome ?? resolved.nome ?? "Sua célula",
          diaReuniao: detail?.diaReuniao ?? null,
          horario: detail?.horario ?? null,
          coberturaEspiritual: detail?.coberturaEspiritual ?? null,
        });
        setSelectedReuniaoId((prev) => prev || reunioesRes[0]?.id || "");

        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar sua célula.",
        );
      } finally {
        setLoading(false);
      }
    },
    [token, resolveCell, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const activeMembers = useMemo(() => members.filter((m) => m.ativo), [members]);
  const selectedReuniao = useMemo(
    () => reunioes.find((r) => r.id === selectedReuniaoId) ?? null,
    [reunioes, selectedReuniaoId],
  );
  const leaderTabs = useMemo(
    () => [
      { id: "relatorio", label: "Relatório" },
      { id: "pessoas", label: "Pessoas", badge: activeMembers.length },
      { id: "avisos", label: "Avisos" },
      { id: "materiais", label: "Materiais" },
      { id: "solicitacoes", label: "Solicitações" },
      { id: "dados", label: "Dados da célula" },
    ],
    [activeMembers.length],
  );

  /** Linha de contexto do hero: "dia hora · cobertura: X" (só as partes que há). */
  const heroMeta = useMemo(() => {
    if (!cellCtx) return "";
    const parts: string[] = [];
    const agenda = [cellCtx.diaReuniao, cellCtx.horario].filter(Boolean).join(" ");
    if (agenda) parts.push(agenda);
    if (cellCtx.coberturaEspiritual) {
      parts.push(`cobertura: ${cellCtx.coberturaEspiritual}`);
    }
    return parts.join(" · ");
  }, [cellCtx]);

  function handlePlanned(meeting: LeaderMeetingOut) {
    const created: Reuniao = {
      id: meeting.id,
      celulaId: meeting.celula_id,
      data: meeting.data,
      hora: meeting.hora,
      tema: meeting.tema,
      status: meeting.status,
    };
    setReunioes((prev) => [created, ...prev.filter((r) => r.id !== created.id)]);
    setSelectedReuniaoId(created.id);
  }

  function openSensitive(tipo: SensitiveCellRequestType) {
    setSensitive(tipo);
  }

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen mc mc--leader" key="minha-celula-lider">
      <div className="mc-shell">
        <div className="screen-head mc-screen-head">
          <div className="titles">
            <p>Cuide da sua célula e conclua cada reunião com clareza.</p>
          </div>
          {cellId ? (
            <div className="actions">
              <DsButton variant="secondary" onClick={() => setShowPlan(true)}>
                <Icon name="calendar" />
                <span>Planejar reunião</span>
              </DsButton>
            </div>
          ) : null}
        </div>

        {error ? (
          <DsBanner
            kind="error"
            action={
              <DsButton
                variant="secondary"
                onClick={() => void load("retry")}
                disabled={loading}
              >
                Tentar novamente
              </DsButton>
            }
          >
            {error}
          </DsBanner>
        ) : null}

        {showSkeleton ? (
          <div className="mc-stack" aria-label="Carregando sua célula">
            {Array.from({ length: 3 }).map((_, i) => (
              <div className="card skeleton" key={i} style={{ padding: "var(--s5)" }}>
                <div className="sk-line sk-sm" />
                <div className="sk-line sk-lg" />
              </div>
            ))}
          </div>
        ) : !cellId ? (
          <div className="card">
            <div className="scaffold">
              <Icon name="team" className="scaffold-ic" />
              <h2>Nenhuma célula vinculada</h2>
              <p>
                Você ainda não tem uma célula sob sua liderança com dados carregáveis.
                Assim que a Central vincular ou houver uma reunião, o painel aparece aqui.
              </p>
            </div>
          </div>
        ) : (
          <div className="mc-leader-workspace">
            {cellCtx ? (
              <section className="mc-cell-context" aria-labelledby="mc-cell-name">
                <div className="mc-cell-context-icon" aria-hidden="true">
                  <Icon name="central-celula" />
                </div>
                <div className="mc-cell-context-body">
                  <h2 id="mc-cell-name">{cellCtx.nome}</h2>
                  {heroMeta ? <p>{heroMeta}</p> : null}
                </div>
                <div className="mc-cell-count" aria-label={`${activeMembers.length} ${activeMembers.length === 1 ? "membro" : "membros"}`}>
                  <strong>{activeMembers.length}</strong>
                  <span>{activeMembers.length === 1 ? "membro" : "membros"}</span>
                </div>
              </section>
            ) : null}

            <Tabs
              tabs={leaderTabs}
              active={activeArea}
              onChange={(id) => setActiveArea(id as LeaderArea)}
              label="Áreas da sua célula"
            >
              {activeArea === "relatorio" ? (
                <div className="mc-area-panel mc-area-panel--report">
                  <section className="mc-report-picker" aria-labelledby="mc-report-picker-title">
                    <div className="mc-report-picker-copy">
                      <h2 id="mc-report-picker-title">Relatório da reunião</h2>
                      <p>Escolha uma reunião e avance por uma etapa de cada vez.</p>
                    </div>
                    {reunioes.length === 0 ? (
                      <p className="muted-note">
                        Nenhuma reunião ainda. Use “Planejar reunião” para criar a primeira.
                      </p>
                    ) : (
                      <div className="field mc-report-select">
                        <label htmlFor="reuniao-picker">Reunião</label>
                        <select
                          id="reuniao-picker"
                          value={selectedReuniaoId}
                          onChange={(e) => setSelectedReuniaoId(e.target.value)}
                        >
                          {reunioes.map((r) => (
                            <option key={r.id} value={r.id}>
                              {formatMeetingDate(r.data)}
                              {r.tema ? ` — ${r.tema}` : ""}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </section>

                  {selectedReuniao ? (
                    <MeetingReportForm
                      key={selectedReuniao.id}
                      token={token!}
                      reuniaoId={selectedReuniao.id}
                      members={activeMembers}
                      onToast={flashToast}
                    />
                  ) : null}
                </div>
              ) : null}

              {activeArea === "pessoas" ? (
                <div className="mc-area-panel">
                  <DisciplesList members={members} />
                </div>
              ) : null}

              {activeArea === "avisos" ? (
                <div className="mc-area-panel mc-area-stack">
                  <CellNoticeForm
                    token={token!}
                    cellId={cellId}
                    onToast={flashToast}
                    onPublished={() => setNoticesReload((n) => n + 1)}
                  />
                  <LeaderNoticesFeed
                    token={token!}
                    reloadToken={noticesReload}
                    onToast={flashToast}
                  />
                </div>
              ) : null}

              {activeArea === "materiais" ? (
                <div className="mc-area-panel">
                  <MaterialsFeed materials={materials} />
                </div>
              ) : null}

              {activeArea === "solicitacoes" ? (
                <div className="mc-area-panel">
                  <MyRequestsList
                    token={token!}
                    reloadToken={requestsReload}
                    onToast={flashToast}
                  />
                </div>
              ) : null}

              {activeArea === "dados" ? (
                <div className="mc-area-panel">
                  <section className="card" aria-labelledby="mc-sensitive-title">
                    <div className="panel-title" id="mc-sensitive-title">
                      <Icon name="shield" /> Dados da célula
                    </div>
                    <div className="section-body">
                      <p className="muted-note">
                        Alterações passam por aprovação da Central e não mudam na hora.
                      </p>
                      <div className="chip-actions">
                        {CELL_SENSITIVE.map((f) => (
                          <Button
                            key={f.tipo}
                            variant="default"
                            size="sm"
                            onClick={() => openSensitive(f.tipo)}
                          >
                            <Icon name="lock" />
                            <span>{f.label}</span>
                          </Button>
                        ))}
                        <Button
                          variant="default"
                          size="sm"
                          onClick={() => setShowMult(true)}
                        >
                          <Icon name="send" />
                          <span>Solicitar multiplicação</span>
                        </Button>
                      </div>
                    </div>
                  </section>
                </div>
              ) : null}
            </Tabs>
          </div>
        )}
        </div>

      {showPlan && token && cellId ? (
        <PlanMeetingModal
          token={token}
          cellId={cellId}
          onClose={() => setShowPlan(false)}
          onToast={flashToast}
          onPlanned={handlePlanned}
        />
      ) : null}

      {showMult && token && cellId ? (
        <MultiplicationRequestModal
          token={token}
          cellId={cellId}
          members={activeMembers}
          onClose={() => setShowMult(false)}
          onToast={flashToast}
          onCreated={() => setRequestsReload((n) => n + 1)}
        />
      ) : null}

      {sensitive && token && cellId ? (
        <SensitiveFieldRequestModal
          token={token}
          cellId={cellId}
          tipo={sensitive}
          members={activeMembers}
          onClose={() => setSensitive(null)}
          onToast={flashToast}
          onCreated={() => setRequestsReload((n) => n + 1)}
        />
      ) : null}

      {/* Gate 9.1: primitive real — ok some em 3600ms; err e role=alert
          PERSISTENTE, fecha so pelo botao do primitive. */}
      <DsToastRegion>
        {toast ? (
          toast.kind === "ok" ? (
            <DsToast
              kind="ok"
              text={toast.text}
              duration={3600}
              onDismiss={() => setToast(null)}
            />
          ) : (
            <DsToast kind="err" text={toast.text} onDismiss={() => setToast(null)} />
          )
        ) : null}
      </DsToastRegion>
    </div>
  );
}
