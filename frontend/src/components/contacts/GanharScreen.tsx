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
 * Abrir contato faz deep-link para o detalhe em #contatos.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  classifyGanhar,
  fetchPipeline,
  followStatus,
  linkContactCell,
  meetsPromotionCriteria,
  promoteContact,
  type Contact,
} from "@/lib/contacts-api";
import { ApiError, fetchCells, type Cell } from "@/lib/dashboard-api";
import { Icon, type IconKey } from "@/lib/icons";
import { useHashRoute } from "@/lib/use-hash-route";

import { LinkCellModal } from "./LinkCellModal";

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
  const { token, expireSession } = useAuth();
  const [, navigate] = useHashRoute();

  const [contacts, setContacts] = useState<Contact[]>([]);
  const [cells, setCells] = useState<Cell[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("novos-contatos");

  const [busyId, setBusyId] = useState<string | null>(null);
  const [linkTarget, setLinkTarget] = useState<Contact | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
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
      try {
        const [page, cellPage] = await Promise.all([
          fetchPipeline(token, "ganhar"),
          fetchCells(token),
        ]);
        setContacts(page.items);
        setCells(cellPage.items);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(
          err instanceof ApiError
            ? err.message
            : "Não foi possível carregar a base de entrada.",
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
      { icon: "user" as const, label: "Novos contatos", value: novos.length, delta: "redes e WhatsApp" },
      {
        icon: "user" as const,
        label: "Visitantes sem acompanhamento",
        value: semAcomp,
        delta: "conectar a uma célula",
        alert: semAcomp > 0,
      },
      { icon: "check" as const, label: "Visitantes com decisão", value: comDecisao, delta: "aceitaram Jesus" },
      { icon: "ganhar" as const, label: "Base de entrada", value: contacts.length, delta: "no estágio Ganhar" },
    ];
  }, [novos, visitantes, contacts.length]);

  const openContact = useCallback(
    (c: Contact) => navigate(`contatos/${c.id}`),
    [navigate],
  );

  const handlePromote = useCallback(
    async (c: Contact) => {
      if (!token) return;
      setBusyId(c.id);
      try {
        await promoteContact(token, c.id, "consolidar");
        setContacts((prev) => prev.filter((p) => p.id !== c.id));
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
    [token, flashToast, handleSessionError],
  );

  const handleLink = useCallback(
    async (celulaId: string) => {
      if (!token || !linkTarget) return;
      setBusyId(linkTarget.id);
      setLinkError(null);
      try {
        const updated = await linkContactCell(token, linkTarget.id, celulaId);
        setContacts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
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
    [token, linkTarget, flashToast, handleSessionError],
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
        header: "",
        width: "1px",
        cell: (c) => (
          <div className="row-actions">
            {!c.celulaId ? (
              <button
                type="button"
                className="btn btn-sm"
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
          </div>
        ),
      },
    ],
    [busyId, openContact],
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
        header: "",
        width: "1px",
        cell: (c) => {
          const canPromote = meetsPromotionCriteria(c);
          return (
            <div className="row-actions">
              {!c.celulaId ? (
                <button
                  type="button"
                  className="btn btn-sm"
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
              <button
                type="button"
                className="btn btn-sm btn-primary"
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
                Promover
              </button>
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
            </div>
          );
        },
      },
    ],
    [busyId, handlePromote, openContact],
  );

  return (
    <div className="screen" key="ganhar">
      <div className="screen-head">
        <div className="titles">
          <h2>Painel do Ganhar</h2>
          <p>
            Quem fala com a igreja pelas redes ou WhatsApp vira contato. Quem já foi
            à célula ou a um evento vira visitante — e segue visitante até aceitar
            Jesus ou completar 3 presenças numa célula.
          </p>
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
          Base de entrada
          <div className="right">
            <div className="tabs">
              <button
                type="button"
                className={`tab${tab === "novos-contatos" ? " active" : ""}`}
                onClick={() => setTab("novos-contatos")}
              >
                Novos contatos <span className="num">{novos.length}</span>
              </button>
              <button
                type="button"
                className={`tab${tab === "visitantes" ? " active" : ""}`}
                onClick={() => setTab("visitantes")}
              >
                Visitantes <span className="num">{visitantes.length}</span>
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
        ) : (
          <DataTable
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
                  : "Visitantes da semana entram nesta lista automaticamente.",
            }}
            onRowClick={openContact}
          />
        )}
      </div>

      {linkTarget ? (
        <LinkCellModal
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
