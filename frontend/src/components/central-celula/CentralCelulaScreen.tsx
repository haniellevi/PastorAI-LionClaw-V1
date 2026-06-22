"use client";

/**
 * Tela #central-celula (grupo Discipular). Dashboard de células com três visões
 * (data-vtab): Células (cards), Relatórios da semana (recebidos/pendentes,
 * api-reports) e Líderes (tabela). Comunicar líderes em massa usa api-broadcasts
 * (segmento `lider`); o envio individual de material é otimista, fiel ao artifact.
 *
 * Estados: loading (skeleton) · empty (sem células) · populated · detail (modal).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CommunicateLeadersModal } from "@/components/central-celula/CommunicateLeadersModal";
import { StatusPill } from "@/components/dashboard/StatusPill";
import { ReportDetailModal } from "@/components/reports/ReportDetailModal";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { fetchCellsFull, type CellSummary } from "@/lib/cells-api";
import { fetchContacts, type Contact } from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon, type IconKey } from "@/lib/icons";
import {
  fetchReports,
  reportSla,
  splitReports,
  type ReportItem,
} from "@/lib/reports-api";

type Vtab = "celulas" | "relatorios" | "lideres";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

export function CentralCelulaScreen() {
  const { token, expireSession } = useAuth();

  const [cells, setCells] = useState<CellSummary[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [vtab, setVtab] = useState<Vtab>("celulas");
  const [detail, setDetail] = useState<ReportItem | null>(null);
  const [showCommunicate, setShowCommunicate] = useState(false);
  const [chargedIds, setChargedIds] = useState<Set<string>>(new Set());
  const [busyCharge, setBusyCharge] = useState<string | null>(null);
  const [sentMaterial, setSentMaterial] = useState<Set<string>>(new Set());
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
        const [cellPage, contactPage, reportPage] = await Promise.all([
          fetchCellsFull(token),
          fetchContacts(token),
          fetchReports(token),
        ]);
        setCells(cellPage.items);
        setContacts(contactPage.items);
        setReports(reportPage.items);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar a central de célula.");
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
    toastTimer.current = window.setTimeout(() => setToast(null), 3600);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  const leaderName = useCallback(
    (id: string | null) => (id ? contacts.find((c) => c.id === id)?.nome ?? "—" : "—"),
    [contacts],
  );

  const { recebidos, pendentes } = useMemo(() => splitReports(reports), [reports]);
  const pendingByCell = useMemo(
    () => new Set(pendentes.map((p) => p.celulaId)),
    [pendentes],
  );

  const stats: Array<{ icon: IconKey; label: string; value: string; delta: string; alert?: boolean }> =
    useMemo(() => {
      const ativas = cells.filter((c) => c.ativo).length;
      const totalLed = cells.filter((c) => c.ativo && c.liderId).length;
      const presentesSum = recebidos.reduce((acc, r) => acc + (r.presentes ?? 0), 0);
      const freq = recebidos.length ? (presentesSum / recebidos.length) : 0;
      return [
        { icon: "user", label: "Células ativas", value: String(ativas), delta: `${cells.length} no total` },
        {
          icon: "check",
          label: "Relatórios recebidos",
          value: `${recebidos.length} / ${totalLed}`,
          delta: "semana atual",
        },
        {
          icon: "alert",
          label: "Relatórios pendentes",
          value: String(pendentes.length),
          delta: "cobrar líderes",
          alert: pendentes.length > 0,
        },
        {
          icon: "document",
          label: "Frequência média",
          value: freq ? freq.toFixed(1).replace(".", ",") : "—",
          delta: "presentes por célula",
        },
      ];
    }, [cells, recebidos, pendentes.length]);

  const leaders = useMemo(
    () => cells.filter((c) => c.liderId).map((c) => ({ cell: c, name: leaderName(c.liderId) })),
    [cells, leaderName],
  );

  const handleCharge = useCallback(
    async (item: ReportItem) => {
      setBusyCharge(item.celulaId);
      try {
        await new Promise((resolve) => setTimeout(resolve, 350));
        setChargedIds((prev) => new Set(prev).add(item.celulaId));
        flashToast({
          kind: "ok",
          text: `Cobrança enviada por WhatsApp à liderança de ${item.celulaNome ?? "célula"}.`,
        });
      } finally {
        setBusyCharge(null);
      }
    },
    [flashToast],
  );

  const sendMaterialIndividual = useCallback(
    (cellId: string, name: string) => {
      setSentMaterial((prev) => new Set(prev).add(cellId));
      flashToast({ kind: "ok", text: `Material enviado a ${name} pelo WhatsApp oficial.` });
    },
    [flashToast],
  );

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="central-celula">
      <div className="screen-head">
        <div className="actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setShowCommunicate(true)}
          >
            <Icon name="broadcast" />
            <span>Enviar material aos líderes</span>
          </button>
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

      {showSkeleton ? null : cells.length === 0 ? (
        <div className="card">
          <div className="empty-state" style={{ padding: "var(--s6)" }}>
            <Icon name="central-celula" />
            <p>
              <strong>Nenhuma célula cadastrada.</strong> Estruture a Visão G12
              para acompanhar líderes e relatórios.
            </p>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="panel-title">
            Central
            <div className="right">
              <div className="tabs">
                <button
                  type="button"
                  className={`tab${vtab === "celulas" ? " active" : ""}`}
                  onClick={() => setVtab("celulas")}
                >
                  Células
                </button>
                <button
                  type="button"
                  className={`tab${vtab === "relatorios" ? " active" : ""}`}
                  onClick={() => setVtab("relatorios")}
                >
                  Relatórios <span className="num">{pendentes.length}</span>
                </button>
                <button
                  type="button"
                  className={`tab${vtab === "lideres" ? " active" : ""}`}
                  onClick={() => setVtab("lideres")}
                >
                  Líderes
                </button>
              </div>
            </div>
          </div>

          {vtab === "celulas" ? (
            <div style={{ padding: "var(--s4)" }}>
              <div className="grid-cells">
                {cells.map((c) => {
                  const atrasado = pendingByCell.has(c.id);
                  return (
                    <div className="card cell-card" key={c.id}>
                      <div className="cell-card-head">
                        <div>
                          <h4>{c.nome}</h4>
                          <div className="sub">Líder: {leaderName(c.liderId)}</div>
                        </div>
                        <StatusPill tone={atrasado ? "danger" : "ok"}>
                          {atrasado ? "Atrasado" : "Em dia"}
                        </StatusPill>
                      </div>
                      <div className="cell-meta-row">
                        <div>
                          <div className="cell-stat num">
                            {contacts.filter((p) => p.celulaId === c.id && p.tipo !== "visitante").length}
                          </div>
                          <div className="sub">membros</div>
                        </div>
                        <div>
                          <div className="cell-stat num">
                            {contacts.filter((p) => p.celulaId === c.id && p.tipo === "visitante").length}
                          </div>
                          <div className="sub">visitantes</div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {vtab === "relatorios" ? (
            <div className="grid-2" style={{ alignItems: "start", padding: "var(--s4)" }}>
              <div>
                <div className="panel-title" style={{ padding: "0 0 var(--s3)" }}>
                  <Icon name="check" /> Recebidos
                  <span className="count">· {recebidos.length}</span>
                </div>
                {recebidos.length === 0 ? (
                  <div className="empty-state" style={{ padding: "var(--s5)" }}>
                    <Icon name="document" />
                    <p><strong>Nenhum relatório recebido ainda.</strong></p>
                  </div>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Célula</th>
                        <th className="num">Presentes</th>
                        <th className="num">Visitantes</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {recebidos.map((r) => (
                        <tr key={r.id ?? r.celulaId}>
                          <td className="nm">{r.celulaNome ?? "—"}</td>
                          <td className="num">{r.presentes ?? "—"}</td>
                          <td className="num">{r.visitantes ?? "—"}</td>
                          <td>
                            <button type="button" className="btn btn-sm" onClick={() => setDetail(r)}>
                              Ver
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div>
                <div
                  className="panel-title"
                  style={{ padding: "0 0 var(--s3)", color: pendentes.length ? "var(--warn)" : undefined }}
                >
                  <Icon name="alert" /> Pendentes
                  <span className="count">· {pendentes.length}</span>
                </div>
                {pendentes.length === 0 ? (
                  <div className="empty-state" style={{ padding: "var(--s5)" }}>
                    <Icon name="check" />
                    <p><strong>Tudo em dia!</strong> Nenhum relatório pendente.</p>
                  </div>
                ) : (
                  pendentes.map((r) => {
                    const sla = reportSla(r);
                    const charged = chargedIds.has(r.celulaId);
                    return (
                      <div className={`list-row${sla.overdue && !charged ? " overdue" : ""}`} key={r.celulaId}>
                        <div style={{ flex: 1 }}>
                          <div className="nm">{r.celulaNome ?? "—"}</div>
                          <div className="sub">Líder: {leaderName(cells.find((c) => c.id === r.celulaId)?.liderId ?? null)}</div>
                        </div>
                        <StatusPill tone={charged ? "accent" : sla.tone}>
                          {charged ? "Cobrança enviada" : sla.label}
                        </StatusPill>
                        <button
                          type="button"
                          className="btn btn-sm btn-primary"
                          disabled={charged || busyCharge === r.celulaId}
                          onClick={() => void handleCharge(r)}
                        >
                          {busyCharge === r.celulaId ? "…" : charged ? "Cobrado" : "Cobrar"}
                        </button>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          ) : null}

          {vtab === "lideres" ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Líder</th>
                  <th>Célula</th>
                  <th>Cobertura</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {leaders.length === 0 ? (
                  <tr>
                    <td colSpan={4}>
                      <div className="empty-state" style={{ padding: "var(--s5)" }}>
                        <Icon name="user" />
                        <p><strong>Nenhuma célula com líder definido.</strong></p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  leaders.map(({ cell, name }) => {
                    const sent = sentMaterial.has(cell.id);
                    return (
                      <tr key={cell.id}>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <span className="avatar">{name.slice(0, 2).toUpperCase()}</span>
                            <span className="nm">{name}</span>
                          </div>
                        </td>
                        <td className="sub">{cell.nome}</td>
                        <td className="sub">{cell.coberturaEspiritual}</td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={sent}
                            onClick={() => sendMaterialIndividual(cell.id, name)}
                          >
                            {sent ? "Enviado" : "Enviar material"}
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          ) : null}
        </div>
      )}

      {detail ? <ReportDetailModal report={detail} onClose={() => setDetail(null)} /> : null}

      {showCommunicate && token ? (
        <CommunicateLeadersModal
          token={token}
          leaderCount={leaders.length}
          onClose={() => setShowCommunicate(false)}
          onSent={(result) => {
            setShowCommunicate(false);
            if (result.status === "bloqueado") {
              flashToast({
                kind: "err",
                text: `Envio bloqueado: ninguém apto. ${result.ignoradosOptout} ignorado(s) por opt-out.`,
              });
            } else {
              flashToast({
                kind: "ok",
                text: `Material enviado a ${result.enviados} líder(es). ${result.ignoradosOptout} ignorado(s) por opt-out.`,
              });
            }
          }}
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
