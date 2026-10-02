"use client";

/**
 * Hook compartilhado por #consolidar e #consol-individual.
 *
 * Centraliza o carregamento (pipeline da consolidação + contatos + células +
 * fila de trabalho), o tick do deadline-badge e os fluxos de lançar decisão
 * (api-launch-decision) e avançar/concluir etapa (api-pipeline / advance-stage).
 *
 * Os vínculos consolidacaoId/responsável vivem na sessão (consolidacao-store),
 * pois o backend não expõe leitura de consolidação por pessoa.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { fetchCellsFull, type CellSummary } from "@/lib/cells-api";
import {
  advanceStage,
  launchDecision,
  StageGateError,
  type LaunchDecisionInput,
} from "@/lib/consolidacao-api";
import {
  getConsolidation,
  patchConsolidation,
  upsertConsolidation,
  useConsolidationStore,
} from "@/lib/consolidacao-store";
import {
  fetchContacts,
  fetchPipeline,
  followStatus,
  type Contact,
} from "@/lib/contacts-api";
import { useVisibleInterval } from "@/lib/use-visible-interval";
import { ApiError, fetchWorkQueue, type WorkItem } from "@/lib/dashboard-api";

export interface Toast {
  kind: "ok" | "err";
  text: string;
}

/** Pessoa consolidada (trilha 100%). */
export function isConsolidated(c: Contact): boolean {
  return followStatus(c).label === "Consolidado";
}

export function useConsolidation() {
  const { token, user, expireSession } = useAuth();
  const selfId = user?.appUserId ?? "";

  const [people, setPeople] = useState<Contact[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [cells, setCells] = useState<CellSummary[]>([]);
  const [deadlinesReady,setDeadlinesReady] = useState(false);
  const [workItems, setWorkItems] = useState<WorkItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pipelineTotal, setPipelineTotal] = useState(0);
  const [pipelinePage, setPipelinePage] = useState(1);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadGeneration = useRef(0);
  const [supportError, setSupportError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // Re-render quando o store de sessão muda (confirmações/decisões).
  const storeVersion = useConsolidationStore();

  // Decision modal.
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [decisionPessoa, setDecisionPessoa] = useState<string | null>(null);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  // Track modal.
  const [trackContact, setTrackContact] = useState<Contact | null>(null);
  const [trackBusy, setTrackBusy] = useState(false);
  const [trackError, setTrackError] = useState<string | null>(null);

  const [toast, setToast] = useState<Toast | null>(null);

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
      setSupportError(null);
      setDeadlinesReady(false);
      setLoadingMore(false);
      const generation = ++loadGeneration.current;
      try {
        // Deadline and labels enrich the list independently; no picker catalog blocks its first page.
        void fetchWorkQueue(token).then(queue => { if (generation === loadGeneration.current) { setWorkItems(queue.items); setDeadlinesReady(true); } }).catch(err => { if (generation === loadGeneration.current && !handleSessionError(err)) setSupportError("Não foi possível confirmar os prazos da fila. Atualize para tentar novamente."); });
        void fetchCellsFull(token).then(page => { if (generation === loadGeneration.current) setCells(page.items); }).catch(err => { if (generation === loadGeneration.current && !handleSessionError(err)) setSupportError("Nomes de células indisponíveis. Atualize para tentar novamente."); });
        const pipe = await fetchPipeline(token, "consolidar", 50);
        if (generation !== loadGeneration.current) return;
        setPeople(pipe.items);
        setContacts(pipe.items);
        setPipelinePage(1);
        setPipelineTotal(pipe.total);
        setLoaded(true);
      } catch (err) {
        if (generation !== loadGeneration.current || handleSessionError(err)) return;
        setError(
          err instanceof ApiError
            ? err.message
            : "Não foi possível carregar a consolidação.",
        );
      } finally {
        if (generation === loadGeneration.current) setLoading(false);
      }
    },
    [token, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
    return () => { loadGeneration.current += 1; };
  }, [load]);

  useVisibleInterval(() => setNow(Date.now()), 30_000);

  const loadMore = useCallback(async () => {
    if (!token || loadingMore || people.length >= pipelineTotal) return;
    const generation = loadGeneration.current;
    setLoadingMore(true);
    try {
      const page = await fetchPipeline(token,"consolidar",50,{page:pipelinePage+1});
      if (generation !== loadGeneration.current) return;
      if (page.items.length === 0 && people.length < page.total) throw new ApiError(502,"A base mudou. Atualize para confirmar os próximos registros.");
      setPeople(current => [...new Map([...current,...page.items].map(item => [item.id,item])).values()]);
      setContacts(current => [...new Map([...current,...page.items].map(item => [item.id,item])).values()]);
      setPipelinePage(page.page);
      setPipelineTotal(page.total);
    } catch(error) { if (generation === loadGeneration.current && !handleSessionError(error)) setError(error instanceof ApiError ? error.message : "Não foi possível carregar mais pessoas."); }
    finally { if (generation === loadGeneration.current) setLoadingMore(false); }
  },[token,loadingMore,people.length,pipelineTotal,pipelinePage,handleSessionError]);

  const toastTimer = useRef<number | null>(null);
  const flashToast = useCallback((t: Toast) => {
    setToast(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  // ---- mapas derivados ----------------------------------------------------
  const cellName = useCallback(
    (id: string | null) =>
      id ? cells.find((c) => c.id === id)?.nome ?? "Célula" : "Sem célula",
    [cells],
  );

  const personName = useCallback(
    (id: string | null) =>
      id ? contacts.find((c) => c.id === id)?.nome ?? "Consolidador" : null,
    [contacts],
  );

  /** Prazo de conexão por pessoa: fila (conectar_celula) + sessão (24h). */
  const prazoByPessoa = useMemo(() => {
    const map = new Map<string, string>();
    for (const it of workItems) {
      if (it.tipo === "conectar_celula" && it.pessoaId && it.prazo) {
        map.set(it.pessoaId, it.prazo);
      }
    }
    for (const p of people) {
      const s = getConsolidation(p.id);
      if (s?.prazoConexao) map.set(p.id, s.prazoConexao);
    }
    // storeVersion mantém o memo coerente com mudanças do store.
    void storeVersion;
    return map;
  }, [workItems, people, storeVersion]);

  const consolidadorName = useCallback(
    (pessoaId: string): string | null => {
      const s = getConsolidation(pessoaId);
      void storeVersion;
      return s?.responsavelId ? personName(s.responsavelId) : null;
    },
    [personName, storeVersion],
  );

  // ---- decision modal -----------------------------------------------------
  const openDecision = useCallback((pessoaId?: string | null) => {
    setDecisionPessoa(pessoaId ?? null);
    setDecisionError(null);
    setDecisionOpen(true);
  }, []);

  const closeDecision = useCallback(() => {
    setDecisionOpen(false);
    setDecisionError(null);
  }, []);

  const handleLaunch = useCallback(
    async (input: LaunchDecisionInput) => {
      if (!token) return;
      setDecisionBusy(true);
      setDecisionError(null);
      try {
        const result = await launchDecision(token, input);
        upsertConsolidation({
          consolidacaoId: result.consolidacaoId,
          pessoaId: input.pessoa,
          responsavelId: result.responsavel,
          prazoConexao: result.prazoConexao,
          vinculo: input.vinculo,
          confirmedStages: [],
          concluida: false,
        });
        setDecisionOpen(false);
        flashToast({
          kind: "ok",
          text:
            input.vinculo === "visitante"
              ? "Decisão lançada — prazo de 24h aberto para conectar à célula."
              : "Decisão lançada — consolidação assumida.",
        });
        void load("retry");
      } catch (err) {
        if (handleSessionError(err)) return;
        setDecisionError(
          err instanceof ApiError ? err.message : "Não foi possível lançar a decisão.",
        );
      } finally {
        setDecisionBusy(false);
      }
    },
    [token, flashToast, load, handleSessionError],
  );

  // ---- track modal --------------------------------------------------------
  const openTrack = useCallback((c: Contact) => {
    setTrackContact(c);
    setTrackError(null);
  }, []);

  const closeTrack = useCallback(() => {
    setTrackContact(null);
    setTrackError(null);
  }, []);

  const handleConfirm = useCallback(
    async (etapa: string) => {
      if (!token || !trackContact) return;
      const session = getConsolidation(trackContact.id);
      if (!session) return;
      setTrackBusy(true);
      setTrackError(null);
      try {
        const result = await advanceStage(token, {
          consolidacaoId: session.consolidacaoId,
          etapa,
        });
        patchConsolidation(trackContact.id, {
          confirmedStages: Array.from(new Set([...session.confirmedStages, etapa])),
          concluida: result.concluida,
        });
        flashToast({ kind: "ok", text: "Etapa confirmada." });
      } catch (err) {
        if (handleSessionError(err)) return;
        setTrackError(
          err instanceof ApiError ? err.message : "Não foi possível confirmar a etapa.",
        );
      } finally {
        setTrackBusy(false);
      }
    },
    [token, trackContact, flashToast, handleSessionError],
  );

  const handleConclude = useCallback(async () => {
    if (!token || !trackContact) return;
    const session = getConsolidation(trackContact.id);
    if (!session) return;
    setTrackBusy(true);
    setTrackError(null);
    try {
      await advanceStage(token, {
        consolidacaoId: session.consolidacaoId,
        concluir: true,
      });
      patchConsolidation(trackContact.id, { concluida: true });
      flashToast({ kind: "ok", text: "Consolidação concluída." });
      void load("retry");
    } catch (err) {
      if (handleSessionError(err)) return;
      if (err instanceof StageGateError) {
        const nomes = err.etapasPendentes.join(", ");
        setTrackError(
          nomes
            ? `Há etapas obrigatórias pendentes: ${nomes}.`
            : err.message,
        );
      } else {
        setTrackError(
          err instanceof ApiError ? err.message : "Não foi possível concluir.",
        );
      }
    } finally {
      setTrackBusy(false);
    }
  }, [token, trackContact, flashToast, load, handleSessionError]);

  return {
    // identidade
    selfId,
    token,
    expireSession,
    hasMore: people.length < pipelineTotal,
    pipelineTotal,
    loadingMore,
    loadMore,
    supportError,
    deadlinesReady,
    roles: user?.roles ?? [],
    // dados
    people,
    contacts,
    cells,
    loading,
    loaded,
    error,
    now,
    storeVersion,
    // derivados
    cellName,
    personName,
    prazoByPessoa,
    consolidadorName,
    sessionFor: (pessoaId: string) => getConsolidation(pessoaId),
    // ações
    reload: () => load("retry"),
    // decision modal
    decisionOpen,
    decisionPessoa,
    decisionBusy,
    decisionError,
    openDecision,
    closeDecision,
    handleLaunch,
    // track modal
    trackContact,
    trackBusy,
    trackError,
    openTrack,
    closeTrack,
    handleConfirm,
    handleConclude,
    // toast
    toast,
  };
}
