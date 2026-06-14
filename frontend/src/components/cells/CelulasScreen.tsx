"use client";

/**
 * Tela #celulas (legada, deep-link fora do menu — delta-012).
 *
 * Estrutura G12 da igreja: grid de células (data como cards), detalhe lateral
 * com membros/visitantes e alertas, e criar/editar célula (api-cells) exigindo
 * cobertura_espiritual. Edição é restrita ao líder da célula ou a um superior
 * na hierarquia (delta-007): papéis de liderança veem a ação; o backend ainda
 * valida e devolve 403 quando o líder não cobre aquela célula específica.
 * Alertas sobre liderados podem ser marcados como tratados no detalhe.
 *
 * Estados: loading (skeleton) · empty (sem células) · detail (célula aberta).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  baixarAlert,
  fetchCellDetail,
  fetchCellsFull,
  upsertCell,
  type CellAlert,
  type CellDetail,
  type CellSummary,
  type UpsertCellInput,
} from "@/lib/cells-api";
import { fetchContacts, tipoLabel, tipoTone, type Contact } from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon, type IconKey } from "@/lib/icons";
import { isLeader, type Role } from "@/lib/roles";

import { CellFormModal } from "./CellFormModal";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

/** Papéis que podem criar células (espelha CELL_CREATE_ROLES + admin). */
function canCreateCells(roles: readonly Role[]): boolean {
  return roles.some((r) => r === "admin" || r === "pastor" || r === "lider_g12");
}

export function CelulasScreen() {
  const { token, user, expireSession } = useAuth();

  const [cells, setCells] = useState<CellSummary[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CellDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<CellSummary | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [busyAlert, setBusyAlert] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  const roles = user?.roles ?? [];
  const canManage = isLeader(roles);
  const canCreate = canCreateCells(roles);

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
        const [cellPage, contactPage] = await Promise.all([
          fetchCellsFull(token),
          fetchContacts(token),
        ]);
        setCells(cellPage.items);
        setContacts(contactPage.items);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar as células.");
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

  const openDetail = useCallback(
    async (cellId: string) => {
      if (!token) return;
      setSelectedId(cellId);
      setDetailLoading(true);
      setDetailError(null);
      setDetail(null);
      try {
        const d = await fetchCellDetail(token, cellId);
        setDetail(d);
      } catch (err) {
        if (handleSessionError(err)) return;
        setDetailError(err instanceof ApiError ? err.message : "Não foi possível abrir a célula.");
      } finally {
        setDetailLoading(false);
      }
    },
    [token, handleSessionError],
  );

  const handleSave = useCallback(
    async (input: UpsertCellInput) => {
      if (!token) return;
      setSaving(true);
      setFormError(null);
      try {
        const saved = await upsertCell(token, input);
        setCells((prev) => {
          const exists = prev.some((c) => c.id === saved.id);
          return exists ? prev.map((c) => (c.id === saved.id ? saved : c)) : [saved, ...prev];
        });
        setShowForm(false);
        setEditing(null);
        flashToast({
          kind: "ok",
          text: input.id ? `Célula ${saved.nome} atualizada.` : `Célula ${saved.nome} criada.`,
        });
        if (selectedId === saved.id) void openDetail(saved.id);
      } catch (err) {
        if (handleSessionError(err)) return;
        setFormError(err instanceof ApiError ? err.message : "Não foi possível salvar a célula.");
      } finally {
        setSaving(false);
      }
    },
    [token, flashToast, handleSessionError, selectedId, openDetail],
  );

  const handleBaixarAlert = useCallback(
    async (alert: CellAlert) => {
      if (!token || !detail) return;
      setBusyAlert(alert.id);
      try {
        await baixarAlert(token, detail.id, alert.id);
        setDetail((prev) =>
          prev ? { ...prev, alerts: prev.alerts.filter((a) => a.id !== alert.id) } : prev,
        );
        flashToast({ kind: "ok", text: "Alerta marcado como tratado." });
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível tratar o alerta.",
        });
      } finally {
        setBusyAlert(null);
      }
    },
    [token, detail, flashToast, handleSessionError],
  );

  // Membros e visitantes da célula selecionada (derivados de api-contacts).
  const { membros, visitantes } = useMemo(() => {
    if (!detail) return { membros: [] as Contact[], visitantes: [] as Contact[] };
    const linked = contacts.filter((c) => c.celulaId === detail.id);
    return {
      membros: linked.filter((c) => c.tipo !== "visitante"),
      visitantes: linked.filter((c) => c.tipo === "visitante"),
    };
  }, [detail, contacts]);

  const stats: Array<{ icon: IconKey; label: string; value: string | number; delta: string; alert?: boolean }> =
    useMemo(() => {
      const ativas = cells.filter((c) => c.ativo).length;
      const semLider = cells.filter((c) => !c.liderId).length;
      const totalMembros = contacts.filter((c) => c.celulaId).length;
      return [
        { icon: "central-celula", label: "Células ativas", value: ativas, delta: `${cells.length} no total` },
        {
          icon: "alert",
          label: "Células sem líder",
          value: semLider,
          delta: "definir cobertura",
          alert: semLider > 0,
        },
        { icon: "user", label: "Pessoas em células", value: totalMembros, delta: "membros e visitantes" },
        { icon: "g12", label: "Cobertura G12", value: cells.length, delta: "estrutura de células" },
      ];
    }, [cells, contacts]);

  const leaderName = useCallback(
    (id: string | null) => (id ? contacts.find((c) => c.id === id)?.nome ?? "—" : "—"),
    [contacts],
  );

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="celulas">
      <div className="screen-head">
        <div className="titles">
          <h2>Células</h2>
          <p>
            Estrutura G12 da igreja. Acompanhe membros, visitantes e alertas de cada célula.
            Apenas o líder da célula ou um superior na hierarquia pode editá-la.
          </p>
        </div>
        <div className="actions">
          {canCreate ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setEditing(null);
                setFormError(null);
                setShowForm(true);
              }}
            >
              <Icon name="ganhar" />
              <span>Nova célula</span>
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

      <p className="lock-note">
        <Icon name="lock" />
        Clique na célula para abrir. Apenas o líder da célula ou um superior na hierarquia
        ministerial pode abrir e editar.
      </p>

      <div className="dash-grid">
        <div>
          {showSkeleton ? (
            <div className="grid-cells">
              {Array.from({ length: 4 }).map((_, i) => (
                <div className="card cell-card skeleton" key={i} aria-hidden="true">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              ))}
            </div>
          ) : cells.length === 0 ? (
            <div className="card">
              <div className="empty-state" style={{ padding: "var(--s6)" }}>
                <Icon name="central-celula" />
                <p>
                  <strong>Nenhuma célula cadastrada.</strong>{" "}
                  {canCreate ? "Crie a primeira célula para estruturar a Visão G12." : "Aguarde a liderança cadastrar as células."}
                </p>
              </div>
            </div>
          ) : (
            <div className="grid-cells">
              {cells.map((c) => {
                const selected = c.id === selectedId;
                return (
                  <button
                    type="button"
                    key={c.id}
                    className={`card cell-card${selected ? " sel" : ""}`}
                    onClick={() => void openDetail(c.id)}
                  >
                    <div className="cell-card-head">
                      <div>
                        <h4>{c.nome}</h4>
                        <div className="sub">Líder: {leaderName(c.liderId)}</div>
                      </div>
                      <StatusPill tone={c.ativo ? "ok" : "muted"}>
                        {c.ativo ? "Ativa" : "Inativa"}
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
                    {!c.liderId ? (
                      <div className="alertline">
                        <Icon name="alert" />
                        <span>Sem líder definido</span>
                      </div>
                    ) : null}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="dash-side">
          <CellDetailPanel
            cell={cells.find((c) => c.id === selectedId) ?? null}
            detail={detail}
            loading={detailLoading}
            error={detailError}
            membros={membros}
            visitantes={visitantes}
            leaderName={leaderName(detail?.liderId ?? null)}
            canEdit={canManage}
            busyAlert={busyAlert}
            onEdit={() => {
              const target = cells.find((c) => c.id === selectedId);
              if (!target) return;
              setEditing(target);
              setFormError(null);
              setShowForm(true);
            }}
            onTreatAlert={(a) => void handleBaixarAlert(a)}
            onRetry={() => selectedId && void openDetail(selectedId)}
          />
        </div>
      </div>

      {showForm ? (
        <CellFormModal
          cell={editing}
          leaders={contacts}
          busy={saving}
          error={formError}
          onClose={() => {
            setShowForm(false);
            setEditing(null);
            setFormError(null);
          }}
          onSubmit={(input) => void handleSave(input)}
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
// Painel de detalhe da célula
// ---------------------------------------------------------------------------
function CellDetailPanel({
  cell,
  detail,
  loading,
  error,
  membros,
  visitantes,
  leaderName,
  canEdit,
  busyAlert,
  onEdit,
  onTreatAlert,
  onRetry,
}: {
  cell: CellSummary | null;
  detail: CellDetail | null;
  loading: boolean;
  error: string | null;
  membros: Contact[];
  visitantes: Contact[];
  leaderName: string;
  canEdit: boolean;
  busyAlert: string | null;
  onEdit: () => void;
  onTreatAlert: (alert: CellAlert) => void;
  onRetry: () => void;
}) {
  if (!cell) {
    return (
      <div className="card card-pad">
        <div className="empty-state" style={{ padding: "var(--s5)" }}>
          <Icon name="central-celula" />
          <p>
            <strong>Selecione uma célula</strong> para ver membros, visitantes e alertas.
          </p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="card card-pad">
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
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="card card-pad">
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error ?? "Não foi possível abrir a célula."}</span>
          <button type="button" className="btn btn-sm" onClick={onRetry}>
            Tentar novamente
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="card card-pad">
      <div className="detail-head">
        <div>
          <h3>{detail.nome}</h3>
          <div className="sub">Líder: {leaderName}</div>
        </div>
        <StatusPill tone={detail.ativo ? "ok" : "muted"}>
          {detail.ativo ? "Ativa" : "Inativa"}
        </StatusPill>
      </div>

      <dl className="detail-list">
        <div>
          <dt>Cobertura espiritual</dt>
          <dd>{detail.coberturaEspiritual}</dd>
        </div>
        <div>
          <dt>Dia de reunião</dt>
          <dd>{detail.diaReuniao ?? "—"}</dd>
        </div>
        <div>
          <dt>Membros</dt>
          <dd className="num">{membros.length}</dd>
        </div>
        <div>
          <dt>Visitantes</dt>
          <dd className="num">{visitantes.length}</dd>
        </div>
      </dl>

      {canEdit ? (
        <button type="button" className="btn btn-block" onClick={onEdit} style={{ marginBottom: "var(--s4)" }}>
          <Icon name="document" />
          <span>Editar célula</span>
        </button>
      ) : null}

      <div className="panel-title" style={{ padding: "0 0 var(--s2)", borderBottom: "none" }}>
        Membros e visitantes
      </div>
      {membros.length === 0 && visitantes.length === 0 ? (
        <p className="sub" style={{ color: "var(--muted)" }}>Nenhuma pessoa vinculada ainda.</p>
      ) : (
        <div>
          {membros.map((p) => (
            <div className="list-row" key={p.id}>
              <div style={{ flex: 1 }}>
                <div className="nm">{p.nome}</div>
                <div className="sub">{tipoLabel(p.tipo)}</div>
              </div>
              <StatusPill tone={tipoTone(p.tipo)}>{tipoLabel(p.tipo)}</StatusPill>
            </div>
          ))}
          {visitantes.map((p) => (
            <div className="list-row" key={p.id}>
              <div style={{ flex: 1 }}>
                <div className="nm">{p.nome}</div>
                <div className="sub">Visitante</div>
              </div>
              <StatusPill tone="accent">Visitante</StatusPill>
            </div>
          ))}
        </div>
      )}

      <div
        className="panel-title"
        style={{ padding: "var(--s3) 0 var(--s2)", borderBottom: "none", color: detail.alerts.length ? "var(--warn)" : undefined }}
      >
        <Icon name="alert" />
        Alertas
        {detail.alerts.length ? <span className="count">· {detail.alerts.length}</span> : null}
      </div>
      {detail.alerts.length === 0 ? (
        <p className="sub" style={{ color: "var(--muted)" }}>Nenhum alerta em aberto sobre liderados.</p>
      ) : (
        <div>
          {detail.alerts.map((a) => (
            <div className="list-row" key={a.id}>
              <div style={{ flex: 1 }}>
                <div className="nm">{a.gatilho ?? "Alerta"}</div>
                {a.acaoEsperada ? <div className="sub">{a.acaoEsperada}</div> : null}
              </div>
              {canEdit ? (
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={busyAlert === a.id}
                  onClick={() => onTreatAlert(a)}
                >
                  {busyAlert === a.id ? "…" : "Tratar"}
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
