"use client";

/**
 * Tela #enviar — Painel do Enviar (multiplicações, US-21/22/23, delta-027).
 *
 * Abas (tabs) sobre /multiplicacoes + derivações:
 *  - agendadas: multiplicações com data prevista aguardando aprovação;
 *  - sem-agendamento: pendências sem data prevista (destaque de pendência);
 *  - aptos: pessoas aptas a liderar (derivado de api-contacts — consolidados);
 *  - historico: multiplicações aprovadas/concluídas.
 *
 * Agendar usa POST /multiplicacoes; aprovar fica DESABILITADO com motivo quando
 * supervisao_ok=false (delta-027). Acesso de agendar/aprovar é de liderança.
 *
 * Estados: loading · empty · agendadas · sem-agendamento · aptos · historico.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { fetchCellsFull, type CellSummary } from "@/lib/cells-api";
import { fetchContacts, followStatus, type Contact } from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon, type IconKey } from "@/lib/icons";
import { initials } from "@/lib/g12-api";
import {
  approveMultiplicacao,
  canApprove,
  classifyMult,
  fetchMultiplicacoes,
  scheduleMultiplicacao,
  type Multiplicacao,
  type MultTab,
  type ScheduleMultiplicacaoInput,
} from "@/lib/multiplicacoes-api";
import { isLeader } from "@/lib/roles";

import { ScheduleMultModal } from "./ScheduleMultModal";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Sem data";
  const [y, m, d] = iso.split("-");
  if (!y || !m || !d) return iso;
  return `${d}/${m}/${y}`;
}

/** Apto a liderar: consolidado na trilha ou já discípulo (derivação de UI). */
function isApt(c: Contact): boolean {
  return followStatus(c).label === "Consolidado" || c.tipo === "discipulo";
}

export function EnviarScreen() {
  const { token, user, expireSession } = useAuth();

  const [mults, setMults] = useState<Multiplicacao[]>([]);
  const [cells, setCells] = useState<CellSummary[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [tab, setTab] = useState<MultTab>("agendadas");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showSchedule, setShowSchedule] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  const canManage = isLeader(user?.roles ?? []);

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
        const [multPage, cellPage, contactPage] = await Promise.all([
          fetchMultiplicacoes(token),
          fetchCellsFull(token),
          fetchContacts(token),
        ]);
        setMults(multPage.items);
        setCells(cellPage.items);
        setContacts(contactPage.items);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar as multiplicações.");
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

  const cellName = useCallback(
    (id: string | null) => (id ? cells.find((c) => c.id === id)?.nome ?? "Célula" : "Célula"),
    [cells],
  );
  const personName = useCallback(
    (id: string | null) => (id ? contacts.find((c) => c.id === id)?.nome ?? null : null),
    [contacts],
  );

  const groups = useMemo(() => {
    const agendadas: Multiplicacao[] = [];
    const semAgendamento: Multiplicacao[] = [];
    const historico: Multiplicacao[] = [];
    for (const m of mults) {
      const g = classifyMult(m);
      if (g === "agendadas") agendadas.push(m);
      else if (g === "sem-agendamento") semAgendamento.push(m);
      else historico.push(m);
    }
    return { agendadas, semAgendamento, historico };
  }, [mults]);

  const aptos = useMemo(() => contacts.filter(isApt), [contacts]);

  const stats: Array<{ icon: IconKey; label: string; value: number; delta: string; alert?: boolean }> =
    useMemo(
      () => [
        { icon: "document", label: "Multiplicações agendadas", value: groups.agendadas.length, delta: "aguardando aprovação" },
        {
          icon: "alert",
          label: "Sem agendamento",
          value: groups.semAgendamento.length,
          delta: "definir data prevista",
          alert: groups.semAgendamento.length > 0,
        },
        { icon: "user", label: "Aptos a liderar", value: aptos.length, delta: "consolidados na trilha" },
        { icon: "check", label: "Aprovadas / concluídas", value: groups.historico.length, delta: "histórico" },
      ],
      [groups, aptos],
    );

  const handleSchedule = useCallback(
    async (input: ScheduleMultiplicacaoInput) => {
      if (!token) return;
      setSaving(true);
      setFormError(null);
      try {
        const created = await scheduleMultiplicacao(token, input);
        setMults((prev) => [created, ...prev]);
        setShowSchedule(false);
        flashToast({
          kind: "ok",
          text: input.dataPrevista
            ? "Multiplicação agendada."
            : "Multiplicação registrada sem data — defina o agendamento.",
        });
        setTab(input.dataPrevista ? "agendadas" : "sem-agendamento");
      } catch (err) {
        if (handleSessionError(err)) return;
        setFormError(err instanceof ApiError ? err.message : "Não foi possível agendar a multiplicação.");
      } finally {
        setSaving(false);
      }
    },
    [token, flashToast, handleSessionError],
  );

  const handleApprove = useCallback(
    async (m: Multiplicacao) => {
      if (!token) return;
      setBusyId(m.id);
      try {
        const result = await approveMultiplicacao(token, m.id);
        setMults((prev) =>
          prev.map((x) => (x.id === m.id ? { ...x, status: result.status, aprovadaPor: result.aprovadaPor } : x)),
        );
        flashToast({ kind: "ok", text: `Multiplicação de ${cellName(m.celulaId)} aprovada.` });
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível aprovar a multiplicação.",
        });
      } finally {
        setBusyId(null);
      }
    },
    [token, cellName, flashToast, handleSessionError],
  );

  const showSkeleton = loading && !loaded;

  const tabs: Array<{ id: MultTab; label: string; count: number; warn?: boolean }> = [
    { id: "agendadas", label: "Agendadas", count: groups.agendadas.length },
    { id: "sem-agendamento", label: "Sem agendamento", count: groups.semAgendamento.length, warn: groups.semAgendamento.length > 0 },
    { id: "aptos", label: "Aptos a liderar", count: aptos.length },
    { id: "historico", label: "Histórico", count: groups.historico.length },
  ];

  return (
    <div className="screen" key="enviar">
      <div className="screen-head">
        <div className="titles">
          <h2>Painel do Enviar</h2>
          <p>
            Cobre, supervisione e aprove multiplicações de células. Acompanhe quem está apto a
            liderar e o histórico por descendência.
          </p>
        </div>
        <div className="actions">
          {canManage ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setFormError(null);
                setShowSchedule(true);
              }}
            >
              <Icon name="send" />
              <span>Agendar multiplicação</span>
            </button>
          ) : null}
        </div>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button type="button" className="btn btn-sm" onClick={() => void load("retry")} disabled={loading}>
            Tentar novamente
          </button>
        </div>
      ) : null}

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

      <div className="card">
        <div className="panel-title">
          Multiplicações
          <div className="right">
            <div className="tabs">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`tab${tab === t.id ? " active" : ""}`}
                  style={t.warn ? { color: "var(--warn)" } : undefined}
                  onClick={() => setTab(t.id)}
                >
                  {t.label} <span className="num">{t.count}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {showSkeleton ? (
          <div className="queue">
            {Array.from({ length: 3 }).map((_, i) => (
              <div className="qitem skeleton" key={i}>
                <span className="qicon sk-icon" />
                <div className="qbody">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        ) : tab === "aptos" ? (
          <AptosList aptos={aptos} cellName={cellName} />
        ) : (
          <MultList
            tab={tab}
            items={
              tab === "agendadas"
                ? groups.agendadas
                : tab === "sem-agendamento"
                  ? groups.semAgendamento
                  : groups.historico
            }
            cellName={cellName}
            personName={personName}
            canManage={canManage}
            busyId={busyId}
            onApprove={(m) => void handleApprove(m)}
            onSchedulePending={() => {
              setFormError(null);
              setShowSchedule(true);
            }}
          />
        )}
      </div>

      {showSchedule ? (
        <ScheduleMultModal
          cells={cells}
          leaders={contacts}
          busy={saving}
          error={formError}
          onClose={() => {
            setShowSchedule(false);
            setFormError(null);
          }}
          onSubmit={(input) => void handleSchedule(input)}
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

// ---------------------------------------------------------------------------
// Lista de multiplicações por aba
// ---------------------------------------------------------------------------
function MultList({
  tab,
  items,
  cellName,
  personName,
  canManage,
  busyId,
  onApprove,
  onSchedulePending,
}: {
  tab: MultTab;
  items: Multiplicacao[];
  cellName: (id: string | null) => string;
  personName: (id: string | null) => string | null;
  canManage: boolean;
  busyId: string | null;
  onApprove: (m: Multiplicacao) => void;
  onSchedulePending: () => void;
}) {
  if (items.length === 0) {
    const empty: Record<string, { title: string; hint: string }> = {
      agendadas: {
        title: "Nenhuma multiplicação agendada.",
        hint: "Agende uma multiplicação para acompanhar a supervisão e a aprovação.",
      },
      "sem-agendamento": {
        title: "Nenhuma pendência sem agendamento.",
        hint: "Multiplicações sem data prevista aparecem aqui para cobrança.",
      },
      historico: {
        title: "Nenhuma multiplicação concluída ainda.",
        hint: "Aprovações e conclusões aparecem no histórico.",
      },
    };
    const e = empty[tab] ?? {
      title: "Nada por aqui ainda.",
      hint: "Os itens aparecem conforme as multiplicações forem cadastradas.",
    };
    return (
      <div className="empty-state" style={{ padding: "var(--s6)" }}>
        <Icon name="send" />
        <p>
          <strong>{e.title}</strong> {e.hint}
        </p>
      </div>
    );
  }

  return (
    <div className="queue">
      {items.map((m) => {
        const approvable = canApprove(m);
        const novoLider = personName(m.novoLiderId);
        const pending = tab === "sem-agendamento";
        const approved = m.status === "aprovada" || m.status === "concluida";
        return (
          <div className="qitem" key={m.id}>
            <span className={`qicon ${pending ? "r" : approved ? "v" : "h"}`}>
              <Icon name={pending ? "alert" : approved ? "check" : "user"} />
            </span>
            <div className="qbody">
              <strong>{cellName(m.celulaId)} → nova célula</strong>
              <div className="meta">
                {novoLider ? `Novo líder: ${novoLider} · ` : "Novo líder a definir · "}
                {pending ? (
                  <span style={{ color: "var(--warn)" }}>sem data prevista</span>
                ) : (
                  `data ${formatDate(m.dataPrevista)}`
                )}
                {m.descendencia ? ` · descendência ${m.descendencia}` : ""}
              </div>
              <div className="meta">
                {approved ? (
                  <StatusPill tone="ok">Aprovada</StatusPill>
                ) : m.supervisaoOk ? (
                  <StatusPill tone="accent">Supervisão concluída</StatusPill>
                ) : (
                  <StatusPill tone="warn">Aguardando supervisão</StatusPill>
                )}
              </div>
            </div>
            {canManage ? (
              <div className="qactions">
                {pending ? (
                  <button type="button" className="btn btn-sm" onClick={onSchedulePending}>
                    Definir data
                  </button>
                ) : null}
                {!approved ? (
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={!approvable || busyId === m.id}
                    aria-disabled={!approvable || undefined}
                    title={
                      approvable
                        ? undefined
                        : "Aprovação bloqueada: a supervisão ainda não assinou esta multiplicação (delta-027)."
                    }
                    onClick={() => approvable && onApprove(m)}
                  >
                    {busyId === m.id ? "Aprovando…" : "Aprovar"}
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Aba "Aptos a liderar"
// ---------------------------------------------------------------------------
function AptosList({
  aptos,
  cellName,
}: {
  aptos: Contact[];
  cellName: (id: string | null) => string;
}) {
  if (aptos.length === 0) {
    return (
      <div className="empty-state" style={{ padding: "var(--s6)" }}>
        <Icon name="user" />
        <p>
          <strong>Ninguém apto a liderar no momento.</strong> Pessoas consolidadas na trilha
          aparecem aqui como aptas a liderar uma nova célula.
        </p>
      </div>
    );
  }

  return (
    <div style={{ padding: "var(--s2) var(--s4) var(--s4)" }}>
      {aptos.map((p) => {
        const consolidado = followStatus(p).label === "Consolidado";
        return (
          <div className="list-row" key={p.id}>
            <span className="avatar">{initials(p.nome)}</span>
            <div style={{ flex: 1 }}>
              <div className="nm">{p.nome}</div>
              <div className="sub">
                {p.celulaId ? `${cellName(p.celulaId)} · ` : ""}
                {consolidado ? "Consolidação concluída" : "Discípulo em formação"}
              </div>
            </div>
            <StatusPill tone={consolidado ? "ok" : "accent"}>
              {consolidado ? "Apto" : "Em formação"}
            </StatusPill>
          </div>
        );
      })}
    </div>
  );
}
