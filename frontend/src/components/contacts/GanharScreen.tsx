"use client";

/**
 * Tela #ganhar — primeira etapa do ciclo G12 (SPEC screen `ganhar`).
 *
 * Abas (tabs) sobre a mesma base de entrada (GET /pipeline?etapa=ganhar):
 *  - novos-contatos: falaram com a igreja e ainda não visitaram;
 *  - visitantes: já foram à célula/evento e seguem visitantes até aceitar
 *    Jesus ou completar 3 presenças.
 *
 * Cada aba é uma data-table com status-pill e empty-state, nos estados
 * loading / empty / populated. Promover visitante chama api-pipeline (PUT) e
 * fica desabilitado com tooltip enquanto presenças < 3 e não aceitou Jesus.
 * Para admin, abrir contato atravessa para a superfície administrativa e
 * preserva o deep-link do detalhe em #contatos/<id>.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  classifyGanhar,
  fetchGanharPage,
  type GanharSummary,
  followStatus,
  summarizeGanhar,
  linkContactCell,
  meetsPromotionCriteria,
  promoteContact,
  type Contact,
} from "@/lib/contacts-api";
import {
  ApiError,
  clearAuthedResponseCache,
  type Cell,
} from "@/lib/dashboard-api";
import { Icon, type IconKey } from "@/lib/icons";
import { isAdmin } from "@/lib/roles";
import { navigateToAdminRoute } from "@/lib/surface";

import { LinkCellModal } from "./LinkCellModal";

import "./people-ux-v2.css";

type Tab = "novos-contatos" | "visitantes";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

function maskPhone(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 6) return phone;
  const tail = digits.slice(-4);
  const head = digits.slice(0, digits.length - 6);
  return `+${head} •••• ${tail}`;
}

export function GanharScreen() {
  const { token, user, expireSession } = useAuth();
  const canOpenContact = user ? isAdmin(user.roles) : false;
  const canLinkCell =
    user?.roles.some((role) => role === "admin" || role === "pastor") ?? false;
  const canAdvancePipeline =
    user?.roles.some((role) =>
      [
        "admin",
        "pastor",
        "lider_g12",
        "lider_consol",
      ].includes(role),
    ) ?? false;

  const [contacts, setContacts] = useState<Contact[]>([]);
  const [cells, setCells] = useState<Cell[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("novos-contatos");
  const [pageNumber, setPageNumber] = useState(1);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<GanharSummary | null>(null);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const loadGeneration = useRef(0);
  const loadedQueryKey = useRef("");
  const dataKey = `${tab}:${pageNumber}:${query}:${user?.churchId ?? ""}`;
  useEffect(() => { if (search.trim() === query) return; const timer = window.setTimeout(() => { setQuery(search.trim()); setPageNumber(1); },250); return () => window.clearTimeout(timer); },[search,query]);

  const [busyId, setBusyId] = useState<string | null>(null);
  const [linkTarget, setLinkTarget] = useState<Contact | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  useEffect(() => {
    if (canLinkCell) return;
    setCells([]);
    setLinkTarget(null);
    setLinkError(null);
  }, [canLinkCell]);

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
      const generation = ++loadGeneration.current;
      setLoading(true);
      if (mode === "initial" && loadedQueryKey.current !== dataKey) setLoaded(false);
      if (mode === "retry") {
        clearAuthedResponseCache(
          token,
          canLinkCell ? ["/pipeline?", "/cells?"] : ["/pipeline?"],
        );
      }
      setError(null);
      try {
        const page = await fetchGanharPage(token, {page:pageNumber,pageSize:50,group:tab,...(query ? {q:query} : {})});
        if (generation !== loadGeneration.current) return;
        setContacts(page.items);
        setTotal(page.total);
        setSummary(page.summary);
        loadedQueryKey.current = dataKey;
        setLoaded(true);
      } catch (err) {
        if (generation !== loadGeneration.current) return;
        if (handleSessionError(err)) return;
        setError(
          err instanceof ApiError
            ? err.message
            : "Não foi possível carregar a base de entrada.",
        );
      } finally {
        if (generation === loadGeneration.current) setLoading(false);
      }
    },
    [token, pageNumber, tab, query, dataKey, canLinkCell, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
    return () => { loadGeneration.current += 1; };
  }, [load]);

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

  const { novos, visitantes } = useMemo(() => {
    const novosList: Contact[] = [];
    const visList: Contact[] = [];
    for (const c of contacts) {
      if (classifyGanhar(c) === "novos-contatos") novosList.push(c);
      else visList.push(c);
    }
    return { novos: novosList, visitantes: visList };
  }, [contacts]);

  const stats: Array<{
    icon: IconKey;
    label: string;
    value: number;
    delta: string;
    alert?: boolean;
  }> = useMemo(() => {
    const semAcomp = visitantes.filter((v) => !v.celulaId).length;
    const comDecisao = visitantes.filter((v) => v.aceitouJesus).length;
    return [
      { icon: "user" as const, label: "Novos contatos", value: summary?.novosContatos ?? novos.length, delta: "redes e WhatsApp" },
      {
        icon: "user" as const,
        label: "Visitantes sem acompanhamento",
        value: summary?.visitantesSemCelula ?? semAcomp,
        delta: "conectar a uma célula",
        alert: semAcomp > 0,
      },
      { icon: "check" as const, label: "Visitantes com decisão", value: summary?.visitantesComDecisao ?? comDecisao, delta: "aceitaram Jesus" },
      { icon: "ganhar" as const, label: "Base de entrada", value: summary?.total ?? contacts.length, delta: "no estágio Ganhar" },
    ];
  }, [novos, visitantes, contacts.length, summary]);

  const openContact = useCallback(
    (c: Contact) => {
      if (!canOpenContact) return;
      navigateToAdminRoute(`contatos/${encodeURIComponent(c.id)}`);
    },
    [canOpenContact],
  );

  const handlePromote = useCallback(
    async (c: Contact) => {
      if (!canAdvancePipeline || !token) return;
      setBusyId(c.id);
      try {
        await promoteContact(token, c.id, "consolidar");
        setContacts((prev) => prev.filter((p) => p.id !== c.id));
        const removed = summarizeGanhar([c]);
        setSummary(current => current ? Object.fromEntries(Object.entries(current).map(([key,value]) => [key,Math.max(0,value - removed[key as keyof GanharSummary])])) as unknown as GanharSummary : null);
        setTotal(current => Math.max(0,current - 1));
        flashToast({ kind: "ok", text: `${c.nome} promovido para Consolidar.` });
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível promover.",
        });
      } finally {
        setBusyId(null);
      }
    },
    [canAdvancePipeline, token, flashToast, handleSessionError],
  );

  const handleLink = useCallback(
    async (celulaId: string) => {
      if (!canLinkCell || !token || !linkTarget) return;
      setBusyId(linkTarget.id);
      setLinkError(null);
      try {
        const updated = await linkContactCell(token, linkTarget.id, celulaId);
        setContacts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
        const before = summarizeGanhar([linkTarget]);
        const after = summarizeGanhar([updated]);
        setSummary(current => current ? Object.fromEntries(Object.entries(current).map(([key,value]) => [key,Math.max(0,value + after[key as keyof GanharSummary] - before[key as keyof GanharSummary])])) as unknown as GanharSummary : null);
        flashToast({ kind: "ok", text: `${updated.nome} conectado à célula.` });
        setLinkTarget(null);
      } catch (err) {
        if (handleSessionError(err)) return;
        setLinkError(
          err instanceof ApiError ? err.message : "Não foi possível conectar à célula.",
        );
      } finally {
        setBusyId(null);
      }
    },
    [canLinkCell, token, linkTarget, flashToast, handleSessionError],
  );

  const showSkeleton = loading && !loaded;
  const rows = tab === "novos-contatos" ? novos : visitantes;

  // ---- colunas por aba ----------------------------------------------------
  const novosColumns: Array<Column<Contact>> = useMemo(
    () => [
      {
        header: "Pessoa",
        cell: (c) => (
          <>
            <div className="nm">{c.nome}</div>
            <div className="sub mono">{maskPhone(c.telefone)}</div>
          </>
        ),
      },
      {
        header: "Situação",
        cell: (c) => {
          const s = followStatus(c);
          return <StatusPill tone={s.tone}>{s.label}</StatusPill>;
        },
      },
      {
        header: "Próxima ação",
        cell: (c) => (
          <div className="row-actions" onKeyDown={(e) => e.stopPropagation()}>
            {canLinkCell && !c.celulaId ? (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={busyId === c.id}
                onClick={(e) => {
                  e.stopPropagation();
                  setLinkError(null);
                  setLinkTarget(c);
                }}
              >
                Vincular célula
              </button>
            ) : null}
            {canOpenContact ? (
              <button
                type="button"
                className="btn btn-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  openContact(c);
                }}
              >
                Ver contato
              </button>
            ) : null}
          </div>
        ),
      },
    ],
    [busyId, canLinkCell, canOpenContact, openContact],
  );

  const visitantesColumns: Array<Column<Contact>> = useMemo(
    () => [
      {
        header: "Visitante",
        cell: (c) => (
          <>
            <div className="nm">{c.nome}</div>
            <div className="sub mono">{maskPhone(c.telefone)}</div>
          </>
        ),
      },
      {
        header: "Presenças",
        numeric: true,
        cell: (c) => `${c.presencasCelula} / 3`,
      },
      {
        header: "Situação",
        cell: (c) => {
          if (c.aceitouJesus) return <StatusPill tone="ok">Decisão registrada</StatusPill>;
          const s = followStatus(c);
          return <StatusPill tone={s.tone}>{s.label}</StatusPill>;
        },
      },
      {
        header: "Próxima ação",
        cell: (c) => {
          const canPromote = meetsPromotionCriteria(c);
          return (
            <div className="people-next-action" onKeyDown={(e) => e.stopPropagation()}>
              <p className="people-meta">
                {canPromote ? "Critério para Consolidar atendido" : "Precisa de 3 presenças ou decisão por Jesus"}
              </p>
              <div className="row-actions">
              {canLinkCell && !c.celulaId ? (
                <button
                  type="button"
                  className={`btn btn-sm${!canPromote || !canAdvancePipeline ? " btn-primary" : ""}`}
                  disabled={busyId === c.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setLinkError(null);
                    setLinkTarget(c);
                  }}
                >
                  Vincular célula
                </button>
              ) : null}
              {canAdvancePipeline ? (
                <button
                  type="button"
                  className={`btn btn-sm${canPromote ? " btn-primary" : ""}`}
                  disabled={!canPromote || busyId === c.id}
                  aria-disabled={!canPromote || undefined}
                  title={
                    canPromote
                      ? undefined
                      : "Visitante só pode ser promovido com 3+ presenças em célula ou decisão por Jesus"
                  }
                  onClick={(e) => {
                    e.stopPropagation();
                    if (canPromote) void handlePromote(c);
                  }}
                >
                  Avançar para Consolidar
                </button>
              ) : null}
              {canOpenContact ? (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    openContact(c);
                  }}
                >
                  Ver contato
                </button>
              ) : null}
              </div>
            </div>
          );
        },
      },
    ],
    [
      busyId,
      canAdvancePipeline,
      canLinkCell,
      canOpenContact,
      handlePromote,
      openContact,
    ],
  );

  return (
    <div className="screen journey-screen journey-screen--ganhar people-ux" key="ganhar">
      <div className="screen-head">
        <div className="titles">
          <h2>Contatos e visitantes</h2>
          <p>Acompanhe visitantes e ajude a construir o próximo vínculo.</p>
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load("retry")}
            disabled={loading}
          >
            <Icon name="refresh" />
            <span>Atualizar</span>
          </button>
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

      <div className="field"><label htmlFor="ganhar-search">Buscar nome, telefone ou e-mail</label><input id="ganhar-search" type="search" value={search} onChange={event => setSearch(event.target.value)} /></div>
      <div className="card">
        <div className="panel-title">
          Pessoas que chegaram
          <div className="right">
            <div className="tabs people-filter-group" role="group" aria-label="Filtrar contatos e visitantes">
              <button
                type="button"
                aria-pressed={tab === "novos-contatos"}
                className={`tab${tab === "novos-contatos" ? " active" : ""}`}
                onClick={() => { setTab("novos-contatos"); setPageNumber(1); }}
              >
                Novos contatos {loaded ? <span className="num">{summary?.novosContatos ?? novos.length}</span> : null}
              </button>
              <button
                type="button"
                aria-pressed={tab === "visitantes"}
                className={`tab${tab === "visitantes" ? " active" : ""}`}
                onClick={() => { setTab("visitantes"); setPageNumber(1); }}
              >
                Visitantes {loaded ? <span className="num">{summary ? summary.total - summary.novosContatos : visitantes.length}</span> : null}
              </button>
            </div>
          </div>
        </div>

        <p className="lock-note">
          {tab === "novos-contatos"
            ? "Pessoas que falaram com a igreja nas redes ou no WhatsApp e ainda não visitaram presencialmente."
            : "Status de visitante até aceitar Jesus (informado pela consolidação ou pelo líder) ou atingir 3 presenças numa célula."}
        </p>

        {showSkeleton ? (
          <div className="queue">
            {Array.from({ length: 4 }).map((_, i) => (
              <div className="qitem skeleton" key={i}>
                <span className="qicon sk-icon" />
                <div className="qbody">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        ) : !loaded ? null : (
          <DataTable
            className="people-table"
            columns={tab === "novos-contatos" ? novosColumns : visitantesColumns}
            rows={rows}
            rowKey={(c) => c.id}
            empty={{
              icon: tab === "novos-contatos" ? "user" : "ganhar",
              title:
                tab === "novos-contatos"
                  ? "Nenhum novo contato por aqui."
                  : "Nenhum visitante aguardando.",
              hint:
                tab === "novos-contatos"
                  ? "Quem falar com a igreja pelo WhatsApp aparece aqui."
                  : "Visitantes registrados no estágio Ganhar aparecem nesta lista.",
            }}
            onRowClick={canOpenContact ? openContact : undefined}
          />
        )}
      </div>

      {loaded && total > 50 ? <div className="people-toolbar"><button type="button" className="btn btn-sm" disabled={loading || pageNumber <= 1} onClick={() => setPageNumber(value => value - 1)}>Página anterior</button><span role="status">Página {pageNumber} de {Math.ceil(total / 50)} · {total} pessoas nesta aba</span><button type="button" className="btn btn-sm" disabled={loading || pageNumber * 50 >= total} onClick={() => setPageNumber(value => value + 1)}>Próxima página</button></div> : null}
      {loaded || showSkeleton ? <details className="people-disclosure people-overview">
        <summary>Resumo da base de entrada</summary>
      <div className="stat-grid">
        {showSkeleton
          ? Array.from({ length: 4 }).map((_, i) => (
              <div className="stat skeleton" key={i}>
                <div className="sk-line sk-sm" />
                <div className="sk-line sk-lg" />
              </div>
            ))
          : stats.map((s) => (
              <div className={`stat${s.alert ? " alert" : ""}`} key={s.label}>
                <div className="lbl">
                  <Icon name={s.icon} />
                  {s.label}
                </div>
                <div className="val num">{s.value}</div>
                <div className="delta">{s.delta}</div>
              </div>
            ))}
      </div>

        <p className="people-meta">Contagens de toda a base neste filtro, dentro do seu acesso atual.</p>
      </details> : null}

      {canLinkCell && linkTarget ? (
        <LinkCellModal
          token={token}
          onSessionExpired={expireSession}
          cells={cells}
          contactName={linkTarget.nome}
          busy={busyId === linkTarget.id}
          error={linkError}
          onClose={() => {
            setLinkTarget(null);
            setLinkError(null);
          }}
          onLink={(celulaId) => void handleLink(celulaId)}
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
