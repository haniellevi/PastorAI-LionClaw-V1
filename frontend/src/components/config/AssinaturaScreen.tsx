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
 *  - a contratação cobra uma taxa de setup única (GET /subscription/planos) + mensalidade;
 *  - tela admin-only (gating de rota no AppShell).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import {
  changePlan,
  createCheckout,
  createSetupCharge,
  fetchPlanCatalog,
  fetchSubscription,
  isPlaceholderSubscription,
  NoSubscriptionError,
  planInfo,
  recoverInvoice,
  resumeSubscription,
  subscriptionUiState,
  type PlanCode,
  type PlanInfo,
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
  return limite == null ? "Ilimitado" : `${limite} membros`;
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
  const [catalog, setCatalog] = useState<PlanInfo[]>([]);
  const [setupFee, setSetupFee] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [checkoutPlan, setCheckoutPlan] = useState<PlanCode | null>(null);
  const [recovering, setRecovering] = useState<"invoice" | "setup" | null>(null);
  // Troca de plano de assinante: pendingPlanChange = aguardando confirmação
  // explícita do usuário; changingPlan = requisição em voo (trava duplo clique).
  const [pendingPlanChange, setPendingPlanChange] = useState<PlanInfo | null>(null);
  const [changingPlan, setChangingPlan] = useState(false);
  const [cpfCnpj, setCpfCnpj] = useState("");
  const [checkoutLinks, setCheckoutLinks] = useState<{
    monthly: string | null;
    setup: string | null;
  } | null>(null);

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
      const [subResult, catResult] = await Promise.allSettled([
        fetchSubscription(token),
        fetchPlanCatalog(token),
      ]);

      let nextError: string | null = null;

      if (subResult.status === "fulfilled") {
        const value = subResult.value;
        setSub(value);
        // Placeholder de checkout falho não é assinatura: a igreja ainda
        // precisa contratar, então a tela abre direto na contratação (mesmo
        // destino de quando o GET devolve 404).
        if (isPlaceholderSubscription(value)) {
          setTab("plans");
        }
        // Reconstrói o painel "Conclua as cobranças" a partir dos links
        // persistidos na assinatura — sobrevive a reload sem depender do
        // estado do checkout. Pendente sem link ainda mostra o painel com o
        // aviso de "links sendo preparados".
        if (value.status === "pendente" || value.invoiceUrl || value.setupInvoiceUrl) {
          setCheckoutLinks({ monthly: value.invoiceUrl, setup: value.setupInvoiceUrl });
        } else {
          setCheckoutLinks(null);
        }
      } else {
        const err = subResult.reason;
        if (handleSessionError(err)) return;
        if (err instanceof NoSubscriptionError) {
          setSub(null);
          setTab("plans"); // sem assinatura: vai direto para contratação
        } else {
          nextError =
            err instanceof ApiError ? err.message : "Não foi possível carregar a assinatura.";
        }
      }

      if (catResult.status === "fulfilled") {
        setCatalog(catResult.value.planos);
        setSetupFee(catResult.value.setupFee);
      } else if (!nextError) {
        const err = catResult.reason;
        if (handleSessionError(err)) return;
        nextError =
          err instanceof ApiError ? err.message : "Não foi possível carregar o catálogo de planos.";
      }

      setError(nextError);
      setLoaded(true);
      setLoading(false);
    },
    [token, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const uiState = useMemo(() => subscriptionUiState(sub), [sub]);
  const hasOutstandingRecovery = Boolean(
    sub?.recoveryInvoiceUrl || sub?.recoveryRequired,
  );

  const contract = useCallback(
    async (plano: PlanCode) => {
      if (!token || checkoutPlan) return;
      const billingDocument = cpfCnpj.replace(/\D/g, "");
      if (billingDocument.length !== 11 && billingDocument.length !== 14) {
        flashToast({ kind: "err", text: "Informe um CPF ou CNPJ válido para iniciar o checkout." });
        return;
      }
      setCheckoutPlan(plano);
      try {
        const result = await createCheckout(token, { plano, cpfCnpj: billingDocument });
        setCpfCnpj("");
        setCheckoutLinks({ monthly: result.invoiceUrl, setup: result.setupInvoiceUrl });
        flashToast({
          kind: "ok",
          text: "Checkout iniciado — use os links de pagamento abaixo. O acesso libera após a confirmação.",
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
    [token, checkoutPlan, cpfCnpj, flashToast, load, handleSessionError],
  );

  const resumeTrackedCheckout = useCallback(
    async (plano: PlanCode) => {
      if (!token || checkoutPlan) return;
      setCheckoutPlan(plano);
      try {
        const result = await resumeSubscription(token);
        setCheckoutLinks({ monthly: result.invoiceUrl, setup: result.setupInvoiceUrl });
        flashToast({ kind: "ok", text: "Cobrança atualizada — use o link de pagamento." });
        await load("retry");
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível atualizar a cobrança.",
        });
      } finally {
        setCheckoutPlan(null);
      }
    },
    [token, checkoutPlan, flashToast, load, handleSessionError],
  );

  // Recuperação da mensalidade REVERTIDA: ação específica do backend
  // (restore/cobrança avulsa) — nunca o checkout genérico, que criaria outra
  // assinatura recorrente no Asaas.
  const recoverReversedInvoice = useCallback(async () => {
    if (!token || recovering) return;
    setRecovering("invoice");
    try {
      await recoverInvoice(token);
      flashToast({ kind: "ok", text: "Cobrança de regularização atualizada." });
      await load("retry");
    } catch (err) {
      if (handleSessionError(err)) return;
      flashToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível recuperar a cobrança.",
      });
    } finally {
      setRecovering(null);
    }
  }, [token, recovering, flashToast, load, handleSessionError]);

  // Confirmação da troca de plano: PUT na assinatura existente (vigência no
  // próximo ciclo) — nunca um novo checkout, nunca pede CPF/CNPJ.
  const confirmPlanChange = useCallback(async () => {
    if (!token || !pendingPlanChange || changingPlan) return;
    setChangingPlan(true);
    try {
      await changePlan(token, { plano: pendingPlanChange.code });
      flashToast({
        kind: "ok",
        text: `Plano atualizado para ${pendingPlanChange.label} — válido a partir do próximo ciclo.`,
      });
      setPendingPlanChange(null);
      await load("retry");
    } catch (err) {
      if (handleSessionError(err)) return;
      flashToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível mudar o plano.",
      });
    } finally {
      setChangingPlan(false);
    }
  }, [token, pendingPlanChange, changingPlan, flashToast, load, handleSessionError]);

  // (Re)emissão da taxa de setup em aberto — cobrança avulsa; sem checkout.
  const emitSetupCharge = useCallback(async () => {
    if (!token || recovering) return;
    setRecovering("setup");
    try {
      await createSetupCharge(token);
      flashToast({ kind: "ok", text: "Taxa de setup emitida — use o link de pagamento." });
      await load("retry");
    } catch (err) {
      if (handleSessionError(err)) return;
      flashToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível emitir a taxa de setup.",
      });
    } finally {
      setRecovering(null);
    }
  }, [token, recovering, flashToast, load, handleSessionError]);

  const showSkeleton = loading && !loaded;

  // Contratação inicial INCOMPLETA: existe o registro local (placeholder
  // gravado antes do POST no Asaas), mas nenhuma recorrência rastreada. A tela
  // precisa continuar sendo a de contratação — com CPF/CNPJ e ação de
  // retomada —, nunca a de assinante.
  const placeholder = isPlaceholderSubscription(sub);
  const complimentary = Boolean(sub?.isComplimentary);
  // Assinatura Asaas rastreada OU cortesia concedida pelo master contam como
  // acesso ativo. Placeholder continua sendo contratação incompleta.
  const assinante = sub != null && !placeholder;
  // O plano salvo no placeholder pode ter saído do catálogo ativo: ainda
  // assim precisa existir uma ação de retomada (o backend reconcilia a
  // intenção congelada; sem intenção recuperável ele devolve 422 e o
  // assinante escolhe um plano ativo).
  const planoSalvoForaDoCatalogo =
    placeholder && sub != null && !catalog.some((p) => p.code === sub.plano);

  // Medidor de porte + upgrade automático (estado ativo).
  // `current` pode ficar undefined se o master desativou o plano do assinante
  // (grandfathering): a igreja continua com ele, só some do catálogo ativo.
  const current = assinante && sub ? planInfo(catalog, sub.plano) : undefined;
  // Troca de plano exige estado LIMPO: ativa, setup quitado, sem reversão.
  const planChangeBlocked =
    assinante &&
    sub != null &&
    (complimentary ||
      uiState !== "active" ||
      !sub.setupPago ||
      sub.invoiceReversal != null ||
      hasOutstandingRecovery);
  // ``pessoas`` é o nome legado da API; o backend envia membros faturáveis.
  const membros = sub?.pessoas ?? 0;
  const limite = sub?.limite ?? current?.limite ?? null;
  const pct = limite ? Math.min(100, Math.round((membros / limite) * 100)) : 0;
  const over = limite != null && membros >= limite;
  const currentIndex = current ? catalog.findIndex((p) => p.code === current.code) : -1;
  const nextPlan = complimentary
    ? null
    : currentIndex >= 0
      ? catalog[currentIndex + 1] ?? null
      : null;
  const frozenCheckoutRecovery = planoSalvoForaDoCatalogo && sub ? (
    <div className="card-pad" style={{ borderBottom: "1px solid var(--border)" }}>
      <p className="sub" style={{ color: "var(--muted)", marginTop: 0 }}>
        A contratação do plano <strong>{sub.plano}</strong> ficou incompleta e esse
        plano não está mais no catálogo. Você pode retomá-la
        {catalog.length > 0 ? " ou escolher um dos planos abaixo" : ""}.
      </p>
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => void contract(sub.plano)}
        disabled={checkoutPlan != null}
        aria-busy={checkoutPlan === sub.plano || undefined}
      >
        {checkoutPlan === sub.plano ? "Abrindo…" : "Retomar contratação"}
      </button>
    </div>
  ) : null;

  return (
    <div className="screen" key="assinatura">
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

      {/* A dívida de um ciclo anterior é uma barreira própria. O ciclo atual
          pode já estar ativo; ainda assim o link que destrava a igreja precisa
          permanecer visível e a troca de plano continua bloqueada. */}
      {hasOutstandingRecovery && sub ? (
        <div className="error-banner" role="alert" style={{ marginBottom: "var(--s4)" }}>
          <Icon name="alert" />
          <span>
            <strong>Regularização anterior pendente.</strong> Conclua essa cobrança
            para liberar o acesso da igreja.
          </span>
          {sub.recoveryInvoiceUrl ? (
            <a
              className="btn btn-sm btn-primary"
              href={sub.recoveryInvoiceUrl}
              target="_blank"
              rel="noreferrer"
            >
              Pagar cobrança de regularização
            </a>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => void recoverReversedInvoice()}
              disabled={recovering != null}
              aria-busy={recovering === "invoice" || undefined}
            >
              {recovering === "invoice" ? "Preparando…" : "Gerar cobrança de regularização"}
            </button>
          )}
        </div>
      ) : null}

      {/* Estado inadimplente: CTA de regularização. Com o link da fatura
          vencida persistido, regularizar é ABRIR a fatura atual — nunca um
          novo checkout, que criaria outra assinatura recorrente no Asaas. */}
      {uiState === "past-due" && sub ? (
        <div className="error-banner" role="alert" style={{ marginBottom: "var(--s4)" }}>
          <Icon name="alert" />
          <span>
            <strong>Pagamento em atraso.</strong> Regularize para manter o acesso da
            igreja ativo.
          </span>
          {sub.invoiceUrl ? (
            <a
              className="btn btn-sm btn-primary"
              href={sub.invoiceUrl}
              target="_blank"
              rel="noreferrer"
            >
              Regularizar pagamento
            </a>
          ) : sub.invoiceReversal && !hasOutstandingRecovery ? (
            // Cobrança estornada/excluída: recuperação ESPECÍFICA — nunca o
            // checkout genérico (criaria outra assinatura recorrente).
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => void recoverReversedInvoice()}
              disabled={recovering != null}
              aria-busy={recovering === "invoice" || undefined}
            >
              {recovering === "invoice" ? "Recuperando…" : "Recuperar cobrança"}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => void resumeTrackedCheckout(sub.plano)}
              disabled={checkoutPlan != null}
              aria-busy={checkoutPlan != null || undefined}
            >
              {checkoutPlan != null ? "Abrindo…" : "Regularizar pagamento"}
            </button>
          )}
        </div>
      ) : null}

      {checkoutLinks ? (
        <div className="card card-pad" style={{ marginBottom: "var(--s4)" }}>
          <h4 style={{ marginTop: 0 }}>Conclua as cobranças</h4>
          <p className="sub" style={{ color: "var(--muted)" }}>
            A mensalidade e a taxa inicial, quando aplicável, são cobranças separadas.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--s2)" }}>
            {checkoutLinks.monthly ? (
              <a
                className="btn btn-primary"
                href={checkoutLinks.monthly}
                target="_blank"
                rel="noreferrer"
              >
                Pagar mensalidade
              </a>
            ) : null}
            {checkoutLinks.setup ? (
              <a className="btn" href={checkoutLinks.setup} target="_blank" rel="noreferrer">
                Pagar taxa de setup
              </a>
            ) : null}
          </div>
          {!checkoutLinks.monthly && !checkoutLinks.setup ? (
            <p className="sub" style={{ color: "var(--muted)", marginBottom: 0 }}>
              Os links ainda estão sendo preparados pelo Asaas. Atualize esta tela em instantes.
            </p>
          ) : null}
        </div>
      ) : null}

      {/* Documento SÓ quando um checkout real pode acontecer: contratação
          inicial ou retomada de um placeholder não rastreado. Assinatura já
          rastreada e troca de plano não pedem CPF/CNPJ. */}
      {!showSkeleton && (sub === null || placeholder) ? (
        <div className="card card-pad" style={{ marginBottom: "var(--s4)" }}>
          <div className="field" style={{ margin: 0, maxWidth: 360 }}>
            <label htmlFor="subscription-cpf-cnpj">CPF ou CNPJ do responsável financeiro</label>
            <input
              id="subscription-cpf-cnpj"
              className="input"
              type="text"
              inputMode="numeric"
              autoComplete="off"
              placeholder="000.000.000-00 ou 00.000.000/0000-00"
              value={cpfCnpj}
              onChange={(event) => setCpfCnpj(event.target.value)}
              aria-describedby="subscription-cpf-cnpj-help"
              aria-invalid={cpfCnpj.length > 0 && cpfCnpj.replace(/\D/g, "").length !== 11 && cpfCnpj.replace(/\D/g, "").length !== 14 ? true : undefined}
            />
            <p id="subscription-cpf-cnpj-help" className="helper">
              Usado somente para criar a cobrança no Asaas; não fica salvo no painel.
            </p>
          </div>
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
        // Só assinatura RASTREADA renderiza o painel de assinante — um
        // placeholder cai no vazio de "nenhum plano contratado".
        assinante && sub ? (
          <div className="grid-2" style={{ alignItems: "start" }}>
            <div className="card card-pad">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h4>Plano {current?.label ?? sub.plano}</h4>
                  <div className="sub" style={{ color: "var(--muted)", marginTop: 3 }}>
                    {complimentary
                      ? "Cortesia da plataforma · sem cobrança"
                      : sub.setupPago
                        ? "Mensalidade ativa · setup quitado"
                        : "Setup pendente"}
                  </div>
                  {complimentary ? (
                    <p className="helper" style={{ margin: "var(--s2) 0 0" }}>
                      Este plano de cortesia é gerenciado pelo administrador da plataforma.
                    </p>
                  ) : null}
                </div>
                <SubscriptionPill state={uiState} />
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: "var(--s4)" }}>
                <span className="val num" style={{ fontSize: 30, fontWeight: 640 }}>
                  {complimentary ? BRL.format(0) : current ? BRL.format(current.preco) : "—"}
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
                  <span style={{ color: "var(--muted)" }}>Membros ativos</span>
                  <span className="num">
                    <strong>{membros}</strong> / {limite ?? "∞"}
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
                        : `Faltam ${limite - membros} membros para o upgrade automático ao plano ${nextPlan.label} (${BRL.format(nextPlan.preco)}).`}
                    </span>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="card card-pad">
              <h4 style={{ marginBottom: "var(--s4)" }}>Detalhes da assinatura</h4>
              <div className="config-row">
                <span style={{ color: "var(--muted)" }}>Próxima cobrança</span>
                <span className="mono num">
                  {complimentary ? "Sem cobrança" : formatDate(sub.proximaCobranca)}
                </span>
              </div>
              <div className="config-row">
                <span style={{ color: "var(--muted)" }}>Taxa de setup</span>
                {sub.setupPago ? (
                  <StatusPill tone="ok">{complimentary ? "Isento" : "Pago"}</StatusPill>
                ) : (
                  <span className="mono num">
                    {BRL.format(sub.setupFeeContracted ?? setupFee)}
                  </span>
                )}
              </div>
              {!complimentary && sub.setupRecoveryRequired ? (
                <div className="config-row">
                  <span style={{ color: "var(--muted)" }}>
                    Setup em aberto sem cobrança ativa
                  </span>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => void emitSetupCharge()}
                    disabled={recovering != null}
                    aria-busy={recovering === "setup" || undefined}
                  >
                    {recovering === "setup" ? "Emitindo…" : "Gerar nova taxa de setup"}
                  </button>
                </div>
              ) : null}
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
      ) : catalog.length === 0 ? (
        <>
          {frozenCheckoutRecovery ? (
            <div className="card" style={{ marginBottom: "var(--s4)" }}>
              {frozenCheckoutRecovery}
            </div>
          ) : null}
          <div className="empty-state" style={{ padding: "var(--s6)" }}>
            <Icon name="card" />
            <p>Nenhum plano disponível no momento.</p>
          </div>
        </>
      ) : (
        <div className="card">
          <div className="panel-title">Planos por porte da igreja</div>
          {pendingPlanChange && sub ? (
            <div className="card-pad" style={{ borderBottom: "1px solid var(--border)" }}>
              <p style={{ marginTop: 0 }}>
                <strong>Confirmar mudança de plano?</strong>
              </p>
              <p className="sub" style={{ color: "var(--muted)" }}>
                {`${current?.label ?? sub.plano} → ${pendingPlanChange.label} (${BRL.format(pendingPlanChange.preco)}/mês). `}
                Válido a partir do próximo ciclo — cobranças já emitidas não mudam.
              </p>
              <div style={{ display: "flex", gap: "var(--s2)" }}>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={() => void confirmPlanChange()}
                  disabled={changingPlan}
                  aria-busy={changingPlan || undefined}
                >
                  {changingPlan ? "Atualizando…" : "Confirmar mudança"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setPendingPlanChange(null)}
                  disabled={changingPlan}
                >
                  Cancelar
                </button>
              </div>
            </div>
          ) : null}
          {assinante && planChangeBlocked ? (
            <div className="card-pad" style={{ borderBottom: "1px solid var(--border)" }}>
              <p className="sub" style={{ color: "var(--muted)", margin: 0 }}>
                {complimentary
                  ? "Este plano de cortesia é gerenciado pelo administrador da plataforma."
                  : "Regularize as cobranças pendentes (mensalidade e taxa de setup) para poder mudar de plano."}
              </p>
            </div>
          ) : null}
          {frozenCheckoutRecovery}
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
              {catalog.map((plan) => {
                // "Plano atual" só existe com assinatura RASTREADA: o plano
                // gravado num placeholder de checkout falho não foi contratado.
                const isCurrent = assinante && sub?.plano === plan.code;
                // O plano do placeholder é o de RETOMADA — todos os outros
                // continuam contratáveis (o backend substitui a intenção
                // `prepared` com segurança, ou devolve 409 se for ambígua).
                const retomar = placeholder && sub?.plano === plan.code;
                return (
                  <tr key={plan.code}>
                    <td className="nm">{plan.label}</td>
                    <td className="num">{formatLimit(plan.limite)}</td>
                    <td className="num">{BRL.format(plan.preco)}</td>
                    <td className="num">{BRL.format(setupFee)}</td>
                    <td>
                      {isCurrent ? (
                        <StatusPill tone="accent">Plano atual</StatusPill>
                      ) : assinante ? (
                        // Assinante: troca ATUALIZA a assinatura existente
                        // (sem CPF, sem checkout) após confirmação explícita.
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => setPendingPlanChange(plan)}
                          disabled={changingPlan || planChangeBlocked}
                          title={
                            planChangeBlocked
                              ? "Regularize as cobranças pendentes para mudar de plano."
                              : undefined
                          }
                        >
                          Mudar plano
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => void contract(plan.code)}
                          disabled={checkoutPlan != null}
                          aria-busy={checkoutPlan === plan.code || undefined}
                        >
                          {checkoutPlan === plan.code
                            ? "Abrindo…"
                            : retomar
                              ? "Retomar contratação"
                              : "Contratar"}
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
