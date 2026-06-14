"use client";

/**
 * Tela #assinatura — plano e faturamento (Asaas / US-34..36).
 * Consome api-subscription (GET /subscription) e o checkout (POST /subscription).
 *
 * Regras refletidas na UI (garantidas no backend):
 *  - estado `ativa`   => plano vigente + medidor de porte + upgrade automático;
 *  - estado `pendente`=> "aguardando confirmação" — NÃO libera acesso;
 *  - estado `inadimplente` => CTA de regularização;
 *  - sem assinatura (404) => somente a tabela de planos para contratar;
 *  - o upgrade por porte é automático (trigger no backend, refletido no GET);
 *  - a contratação cobra uma taxa de setup única (SETUP_FEE) + mensalidade;
 *  - tela admin-only (gating de rota no AppShell).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import {
  createCheckout,
  fetchSubscription,
  NoSubscriptionError,
  PLAN_CATALOG,
  planInfo,
  SETUP_FEE,
  subscriptionUiState,
  type PlanCode,
  type Subscription,
} from "@/lib/subscription-api";

type Tab = "overview" | "plans";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

const BRL = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  maximumFractionDigits: 0,
});

function formatLimit(limite: number | null): string {
  return limite == null ? "Ilimitado" : `${limite} pessoas`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function AssinaturaScreen() {
  const { token, expireSession } = useAuth();

  const [sub, setSub] = useState<Subscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [checkoutPlan, setCheckoutPlan] = useState<PlanCode | null>(null);

  const [toast, setToast] = useState<Toast | null>(null);
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
        const data = await fetchSubscription(token);
        setSub(data);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        if (err instanceof NoSubscriptionError) {
          setSub(null);
          setLoaded(true);
          setTab("plans"); // sem assinatura: vai direto para contratação
          return;
        }
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar a assinatura.",
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

  const uiState = useMemo(() => subscriptionUiState(sub), [sub]);

  const contract = useCallback(
    async (plano: PlanCode) => {
      if (!token || checkoutPlan) return;
      setCheckoutPlan(plano);
      try {
        const result = await createCheckout(token, { plano });
        if (result.invoiceUrl) {
          window.open(result.invoiceUrl, "_blank", "noopener,noreferrer");
        }
        flashToast({
          kind: "ok",
          text: "Checkout iniciado — conclua o pagamento. O acesso libera após a confirmação.",
        });
        await load("retry");
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível iniciar o checkout.",
        });
      } finally {
        setCheckoutPlan(null);
      }
    },
    [token, checkoutPlan, flashToast, load, handleSessionError],
  );

  const showSkeleton = loading && !loaded;

  // Medidor de porte + upgrade automático (estado ativo).
  const current = sub ? planInfo(sub.plano) : null;
  const pessoas = sub?.pessoas ?? 0;
  const limite = sub?.limite ?? current?.limite ?? null;
  const pct = limite ? Math.min(100, Math.round((pessoas / limite) * 100)) : 0;
  const over = limite != null && pessoas >= limite;
  const nextPlan = current
    ? PLAN_CATALOG[PLAN_CATALOG.findIndex((p) => p.code === current.code) + 1] ?? null
    : null;

  return (
    <div className="screen" key="assinatura">
      <div className="screen-head">
        <div className="titles">
          <h2>Assinatura</h2>
          <p>
            Status do plano da igreja. O plano sobe automaticamente quando o
            número de pessoas ultrapassa o limite.
          </p>
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

      {/* Estado pendente: aguardando confirmação, sem liberar acesso. */}
      {uiState === "pending" ? (
        <div className="error-banner" role="status" style={{ marginBottom: "var(--s4)" }}>
          <Icon name="clock" />
          <span>
            <strong>Aguardando confirmação do pagamento.</strong> O acesso completo
            é liberado assim que o Asaas confirmar a cobrança.
          </span>
        </div>
      ) : null}

      {/* Estado inadimplente: CTA de regularização. */}
      {uiState === "past-due" && sub ? (
        <div className="error-banner" role="alert" style={{ marginBottom: "var(--s4)" }}>
          <Icon name="alert" />
          <span>
            <strong>Pagamento em atraso.</strong> Regularize para manter o acesso da
            igreja ativo.
          </span>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => void contract(sub.plano)}
            disabled={checkoutPlan != null}
            aria-busy={checkoutPlan != null || undefined}
          >
            {checkoutPlan != null ? "Abrindo…" : "Regularizar pagamento"}
          </button>
        </div>
      ) : null}

      {!showSkeleton ? (
        <div className="tabs" style={{ marginBottom: "var(--s4)" }}>
          <button
            type="button"
            className={`tab${tab === "overview" ? " active" : ""}`}
            onClick={() => setTab("overview")}
          >
            Visão geral
          </button>
          <button
            type="button"
            className={`tab${tab === "plans" ? " active" : ""}`}
            onClick={() => setTab("plans")}
          >
            Planos por porte
          </button>
        </div>
      ) : null}

      {showSkeleton ? (
        <div className="card card-pad">
          <div className="queue">
            {Array.from({ length: 3 }).map((_, i) => (
              <div className="qitem skeleton" key={i}>
                <div className="qbody">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : tab === "overview" ? (
        sub && current ? (
          <div className="grid-2" style={{ alignItems: "start" }}>
            <div className="card card-pad">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h4>Plano {current.label}</h4>
                  <div className="sub" style={{ color: "var(--muted)", marginTop: 3 }}>
                    {sub.setupPago ? "Mensalidade ativa · setup quitado" : "Setup pendente"}
                  </div>
                </div>
                <SubscriptionPill state={uiState} />
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: "var(--s4)" }}>
                <span className="val num" style={{ fontSize: 30, fontWeight: 640 }}>
                  {BRL.format(current.preco)}
                </span>
                <span style={{ color: "var(--muted)" }}>/mês</span>
              </div>
              <div style={{ marginTop: "var(--s4)" }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 13,
                    marginBottom: 6,
                  }}
                >
                  <span style={{ color: "var(--muted)" }}>Pessoas cadastradas</span>
                  <span className="num">
                    <strong>{pessoas}</strong> / {limite ?? "∞"}
                  </span>
                </div>
                <div className={`meter${over ? " over" : ""}`}>
                  <span style={{ width: `${pct}%` }} />
                </div>
                {nextPlan && limite != null ? (
                  <div
                    className="sub"
                    style={{
                      color: over ? "var(--warn)" : "var(--muted)",
                      marginTop: 8,
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    <Icon name="alert" />
                    <span>
                      {over
                        ? `Limite atingido — upgrade automático ao plano ${nextPlan.label} (${BRL.format(nextPlan.preco)}).`
                        : `Faltam ${limite - pessoas} pessoas para o upgrade automático ao plano ${nextPlan.label} (${BRL.format(nextPlan.preco)}).`}
                    </span>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="card card-pad">
              <h4 style={{ marginBottom: "var(--s4)" }}>Detalhes da assinatura</h4>
              <div className="config-row">
                <span style={{ color: "var(--muted)" }}>Próxima cobrança</span>
                <span className="mono num">{formatDate(sub.proximaCobranca)}</span>
              </div>
              <div className="config-row">
                <span style={{ color: "var(--muted)" }}>Taxa de setup</span>
                {sub.setupPago ? (
                  <StatusPill tone="ok">Pago</StatusPill>
                ) : (
                  <span className="mono num">{BRL.format(SETUP_FEE)}</span>
                )}
              </div>
              <div className="config-row">
                <span style={{ color: "var(--muted)" }}>Custo de LLM</span>
                <span style={{ color: "var(--muted)" }}>Por conta da igreja (BYO)</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="empty-state" style={{ padding: "var(--s6)" }}>
            <Icon name="card" />
            <p>
              <strong>Nenhum plano contratado.</strong> Escolha um plano em
              “Planos por porte” para ativar a igreja.
            </p>
          </div>
        )
      ) : (
        <div className="card">
          <div className="panel-title">Planos por porte da igreja</div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Plano</th>
                <th className="num">Até</th>
                <th className="num">Mensalidade</th>
                <th className="num">Setup</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {PLAN_CATALOG.map((plan) => {
                const isCurrent = sub?.plano === plan.code;
                return (
                  <tr key={plan.code}>
                    <td className="nm">{plan.label}</td>
                    <td className="num">{formatLimit(plan.limite)}</td>
                    <td className="num">{BRL.format(plan.preco)}</td>
                    <td className="num">{BRL.format(SETUP_FEE)}</td>
                    <td>
                      {isCurrent ? (
                        <StatusPill tone="accent">Plano atual</StatusPill>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => void contract(plan.code)}
                          disabled={checkoutPlan != null}
                          aria-busy={checkoutPlan === plan.code || undefined}
                        >
                          {checkoutPlan === plan.code ? "Abrindo…" : "Contratar"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}

function SubscriptionPill({ state }: { state: ReturnType<typeof subscriptionUiState> }) {
  const map: Record<typeof state, { tone: PillTone; label: string }> = {
    active: { tone: "ok", label: "Ativa" },
    pending: { tone: "warn", label: "Aguardando confirmação" },
    "past-due": { tone: "danger", label: "Em atraso" },
    plans: { tone: "muted", label: "Sem plano" },
  };
  const { tone, label } = map[state];
  return <StatusPill tone={tone}>{label}</StatusPill>;
}
