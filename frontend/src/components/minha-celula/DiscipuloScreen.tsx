"use client";

/**
 * Minha Célula — visão do Discípulo (Células PR3). Orquestra, em paralelo:
 *   próxima reunião (US-01), avisos (US-04), materiais (US-21) e histórico (US-05).
 * Ações de escrita: confirmar presença (US-02) e indicar visitante (US-03).
 * Estados de cada seção: loading (skeleton) · empty · populated · erro (retry).
 */
import { useCallback, useEffect, useRef, useState } from "react";

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

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="minha-celula">
      <div className="screen-head">
        <div className="titles">
          <h2>Minha Célula</h2>
          <p>Sua próxima reunião, avisos e histórico.</p>
        </div>
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
      ) : (
        <div className="mc-stack">
          {token ? (
            <NextMeetingCard
              token={token}
              meeting={meeting}
              onToast={flashToast}
              onIndicateVisitor={() => setShowVisitor(true)}
            />
          ) : null}
          <NoticesFeed notices={notices} />
          <MaterialsFeed materials={materials} />
          <MeetingHistoryList items={history} />
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

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
