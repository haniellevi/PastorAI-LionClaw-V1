"use client";

/**
 * Minha Célula — visão do LÍDER (Células PR: Líder). Orquestra a gestão da célula:
 *   • planejar reunião pontual (US-06) e relatar a reunião em seções (US-07..11);
 *   • discípulos (US-12) e campos sensíveis via Solicitação (US-13/14);
 *   • publicar/inativar avisos da célula (US-12A/12B) e ler materiais (US-21).
 *
 * O `celula_id` do líder não vem de /auth/me; é resolvido no cliente a partir da
 * próxima reunião, das solicitações ou dos avisos (primeira fonte disponível).
 * Campos sensíveis NUNCA são salvos direto — abrem a Solicitação (RF-14).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  const [selectedReuniaoId, setSelectedReuniaoId] = useState<string>("");

  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showPlan, setShowPlan] = useState(false);
  const [showMult, setShowMult] = useState(false);
  const [sensitive, setSensitive] = useState<SensitiveCellRequestType | null>(null);
  const [requestsReload, setRequestsReload] = useState(0);
  const [noticesReload, setNoticesReload] = useState(0);

  const [toast, setToast] = useState<CellToast | null>(null);
  const toastTimer = useRef<number | null>(null);
  const flashToast = useCallback((t: CellToast) => {
    setToast(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3600);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

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
  const resolveCellId = useCallback(async (): Promise<string | null> => {
    const led = await getMyLedCells(token!);
    if (led[0]?.id) return led[0].id;
    const next = await getNextMeeting(token!);
    if (next.meeting?.celula_id) return next.meeting.celula_id;
    const reqs = await listRequests(token!);
    if (reqs.items[0]?.celula_id) return reqs.items[0].celula_id;
    const notices = await listNotices(token!);
    const withCell = notices.items.find((n) => n.celula_id);
    return withCell?.celula_id ?? null;
  }, [token]);

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (!token) return;
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const cid = await resolveCellId();
        if (!cid) {
          setCellId(null);
          setLoaded(true);
          return;
        }
        setCellId(cid);

        const [membersRes, reunioesRes, materialsRes] = await Promise.all([
          getCellMembers(token, cid),
          listReunioes(token, cid),
          listMaterials(token),
        ]);
        setMembers(membersRes.members);
        setReunioes(reunioesRes);
        setMaterials(materialsRes.items);
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
    [token, resolveCellId, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const activeMembers = useMemo(() => members.filter((m) => m.ativo), [members]);
  const selectedReuniao = useMemo(
    () => reunioes.find((r) => r.id === selectedReuniaoId) ?? null,
    [reunioes, selectedReuniaoId],
  );

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
    <div className="screen" key="minha-celula-lider">
      <div className="screen-head">
        <div className="titles">
          <h2>Minha Célula</h2>
          <p>Gestão da célula que você lidera.</p>
        </div>
        {cellId ? (
          <div className="head-actions">
            <Button variant="primary" size="sm" onClick={() => setShowPlan(true)}>
              <Icon name="calendar" />
              <span>Planejar reunião</span>
            </Button>
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load("retry")}
            disabled={loading}
          >
            Tentar novamente
          </button>
        </div>
      ) : null}

      {showSkeleton ? (
        <div className="mc-stack">
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
            <h3>Nenhuma célula vinculada</h3>
            <p>
              Você ainda não tem uma célula sob sua liderança com dados carregáveis.
              Assim que a Central vincular ou houver uma reunião, o painel aparece aqui.
            </p>
          </div>
        </div>
      ) : (
        <div className="mc-stack">
          {/* Reunião a relatar */}
          <section className="card" aria-label="Reunião">
            <div className="panel-title">
              <Icon name="calendar" /> Relatório da reunião
            </div>
            <div className="section-body">
              {reunioes.length === 0 ? (
                <p className="muted-note">
                  Nenhuma reunião ainda. Use “Planejar reunião” para criar a primeira.
                </p>
              ) : (
                <div className="field">
                  <label htmlFor="reuniao-picker">Escolha a reunião</label>
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
            </div>
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

          {/* Discípulos (leitura) */}
          <DisciplesList members={members} />

          <section className="card" aria-label="Dados sensíveis da célula">
            <div className="panel-title">
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

          {/* Avisos da célula */}
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

          {/* Materiais (leitura) */}
          <MaterialsFeed materials={materials} />

          {/* Minhas solicitações */}
          <MyRequestsList
            token={token!}
            reloadToken={requestsReload}
            onToast={flashToast}
          />
        </div>
      )}

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

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
