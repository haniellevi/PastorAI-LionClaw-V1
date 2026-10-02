"use client";

import "../cells/operations-ux-v2.css";

/**
 * Minha Célula — visão do Discípulo (Células PR3). Orquestra, em paralelo:
 *   próxima reunião (US-01), avisos (US-04), materiais (US-21) e histórico (US-05).
 * Ações de escrita: confirmar presença (US-02) e indicar visitante (US-03).
 * Estados de cada seção: loading (skeleton) · empty · populated · erro (retry).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { SupportReveal } from "@/components/brand/SupportReveal";
import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsToast, DsToastRegion } from "@/components/ds/Toast";
import { Icon } from "@/lib/icons";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { getNextMeeting, getMyHistory, type NextMeetingBody, type HistoryItem } from "@/lib/cells-api";
import { getMyNotices, type DiscipleNotice } from "@/lib/cell-notices-api";
import { listMaterials, type Material } from "@/lib/cell-materials-api";

import { NextMeetingCard } from "./NextMeetingCard";
import { NoticesFeed } from "./NoticesFeed";
import { MaterialsFeed } from "./MaterialsFeed";
import { MeetingHistoryList } from "./MeetingHistoryList";
import { IndicateVisitorModal } from "./IndicateVisitorModal";
import type { CellToast } from "./types";

export function DiscipuloScreen() {
  const { token, expireSession } = useAuth();

  const [meeting, setMeeting] = useState<NextMeetingBody | null>(null);
  const [notices, setNotices] = useState<DiscipleNotice[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const generation = useRef(0);
  const primaryRequest = useRef(0);
  const [supportState, setSupportState] = useState<Record<string, "loading" | "ready" | "error">>({});

  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showVisitor, setShowVisitor] = useState(false);
  const [toast, setToast] = useState<CellToast | null>(null);

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

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (!token) return;
      const request = ++primaryRequest.current;
      const epoch = generation.current;
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const nextRes = await getNextMeeting(token);
        if (request !== primaryRequest.current || epoch !== generation.current) return;
        setMeeting(nextRes.meeting);
        setLoaded(true);
      } catch (err) {
        if (request !== primaryRequest.current || epoch !== generation.current) return;
        if (handleSessionError(err)) return;
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar sua célula.",
        );
      } finally {
        if (request === primaryRequest.current && epoch === generation.current) setLoading(false);
      }
    },
    [token, handleSessionError],
  );

  const loadSupport = useCallback(async (kind: "notices" | "materials" | "history") => {
    if (!token) return;
    const epoch = generation.current;
    setSupportState((state) => ({ ...state, [kind]: "loading" }));
    try {
      if (kind === "notices") {
        const data = await getMyNotices(token);
        if (epoch === generation.current) setNotices(data);
      } else if (kind === "materials") {
        const data = await listMaterials(token);
        if (epoch === generation.current) setMaterials(data.items);
      } else {
        const data = await getMyHistory(token);
        if (epoch === generation.current) setHistory(data.items);
      }
      if (epoch === generation.current) setSupportState((state) => ({ ...state, [kind]: "ready" }));
    } catch (error) {
      if (epoch === generation.current && !handleSessionError(error)) setSupportState((state) => ({ ...state, [kind]: "error" }));
    }
  }, [token, handleSessionError]);

  useEffect(() => {
    generation.current += 1;
    setSupportState({});
    setNotices([]); setMaterials([]); setHistory([]);
    void load("initial");
    void loadSupport("notices");
    return () => { generation.current += 1; };
  }, [load, loadSupport]);

  const supportFeedback = (kind: "notices" | "materials" | "history") => supportState[kind] === "error"
    ? <div role="alert">Esta seção está indisponível. <button type="button" className="btn btn-sm" onClick={() => void loadSupport(kind)}>Tentar novamente</button></div>
    : supportState[kind] !== "ready" ? <p role="status">Carregando…</p> : null;

  // Gate 9.1: sem timer manual — o DsToast e o dono do ciclo de vida.
  const flashToast = useCallback((t: CellToast) => setToast(t), []);

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen mc mc--member ops-v2" key="minha-celula">
      <div className="screen-head">
        {/* PR212-CORRECTIVE-1: o h1 "Minha Célula" é da Topbar (SCREEN_META);
            repetir o mesmo texto aqui duplicava o título na tela. Fica só o
            subtítulo. */}
        <div className="titles">
          <p>Sua próxima reunião, avisos e materiais da célula.</p>
        </div>
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
        <div className="mc-stack">
          {Array.from({ length: 3 }).map((_, i) => (
            <div className="card skeleton" key={i} style={{ padding: "var(--s5)" }}>
              <div className="sk-line sk-sm" />
              <div className="sk-line sk-lg" />
            </div>
          ))}
        </div>
      ) : (
        <div className="mc-member-layout">
          {token ? (
            <div className="mc-area mc-area--meeting">
              <NextMeetingCard
                token={token}
                meeting={meeting}
                onToast={flashToast}
                onIndicateVisitor={() => setShowVisitor(true)}
              />
            </div>
          ) : null}
          <div className="mc-area mc-area--notices">
            {supportFeedback("notices")}
            {supportState.notices === "ready" ? <NoticesFeed notices={notices} /> : null}
          </div>
          <SupportReveal className="mc-area mc-area--materials">
            <details className="ops-disclosure" onToggle={(event) => { if (event.currentTarget.open && !supportState.materials) void loadSupport("materials"); }}>
              <summary>Materiais da célula</summary>
              <div className="ops-disclosure-body">{supportFeedback("materials")}{supportState.materials === "ready" ? <MaterialsFeed materials={materials} /> : null}</div>
            </details>
          </SupportReveal>
          <SupportReveal className="mc-area mc-area--history">
            <details className="ops-disclosure" onToggle={(event) => { if (event.currentTarget.open && !supportState.history) void loadSupport("history"); }}>
              <summary>Meu histórico de reuniões</summary>
              <div className="ops-disclosure-body">{supportFeedback("history")}{supportState.history === "ready" ? <MeetingHistoryList items={history} /> : null}</div>
            </details>
          </SupportReveal>
        </div>
      )}

      {showVisitor && token && meeting ? (
        <IndicateVisitorModal
          token={token}
          reuniaoId={meeting.id}
          onClose={() => setShowVisitor(false)}
          onToast={flashToast}
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
