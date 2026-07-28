"use client";

/**
 * Minha Célula — visão do Discípulo (Células PR3). Orquestra, em paralelo:
 *   próxima reunião (US-01), avisos (US-04), materiais (US-21) e histórico (US-05).
 * Ações de escrita: confirmar presença (US-02) e indicar visitante (US-03).
 * Estados de cada seção: loading (skeleton) · empty · populated · erro (retry).
 */
import { useCallback, useEffect, useState } from "react";

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
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const [nextRes, noticeRes, materialRes, historyRes] = await Promise.all([
          getNextMeeting(token),
          getMyNotices(token),
          listMaterials(token),
          getMyHistory(token),
        ]);
        setMeeting(nextRes.meeting);
        setNotices(noticeRes);
        setMaterials(materialRes.items);
        setHistory(historyRes.items);
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
    [token, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  // Gate 9.1: sem timer manual — o DsToast e o dono do ciclo de vida.
  const flashToast = useCallback((t: CellToast) => setToast(t), []);

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen mc mc--member" key="minha-celula">
      <div className="screen-head">
        {/* PR212-CORRECTIVE-1: o h1 "Minha Célula" é da Topbar (SCREEN_META);
            repetir o mesmo texto aqui duplicava o título na tela. Fica só o
            subtítulo. */}
        <div className="titles">
          <p>Sua próxima reunião, avisos e histórico.</p>
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
            <NoticesFeed notices={notices} />
          </div>
          <div className="mc-area mc-area--materials">
            <MaterialsFeed materials={materials} />
          </div>
          <div className="mc-area mc-area--history">
            <MeetingHistoryList items={history} />
          </div>
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
