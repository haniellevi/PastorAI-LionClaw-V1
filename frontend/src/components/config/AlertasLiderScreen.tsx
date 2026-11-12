"use client";

import "@/components/config/administration-ux-v2.css";

/**
 * Tela "Alertas ao líder" da superfície admin (RF-26 / US-23).
 * O admin liga, desliga e ajusta as regras que geram alertas para o líder de
 * célula. A geração roda no servidor, por estado do banco, só para igrejas
 * liberadas pela operação; esta tela não abre esse gate, apenas o informa.
 * O líder vê e baixa os alertas em Hoje e no detalhe da célula.
 */
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Toggle } from "@/components/ui/Toggle";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import {
  getAlertRules,
  saveAlertRule,
  type AlertRule,
  type AlertRules,
} from "@/lib/cell-alerts-api";
import { isAdmin } from "@/lib/roles";

type Drafts = Record<string, { ativo: boolean; valores: Record<string, string> }>;

function draftOf(rule: AlertRule) {
  return {
    ativo: rule.ativo,
    valores: Object.fromEntries(rule.parametros.map((p) => [p.nome, String(p.valor)])),
  };
}

export function AlertasLiderScreen() {
  const { token, user, expireSession } = useAuth();
  const [reload, setReload] = useState(0);
  const scope = useMemo(
    () => ({ token, appUserId: user?.appUserId, churchId: user?.churchId, reload }),
    [token, user?.appUserId, user?.churchId, reload],
  );
  const currentScope = useRef<typeof scope | null>(scope);
  currentScope.current = scope;
  const [data, setData] = useState<AlertRules | null>(null);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [ruleError, setRuleError] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<string | null>(null);
  const allowed = Boolean(token && user && isAdmin(user.roles));

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setDrafts({});
    setLoading(allowed);
    setLoadError(null);
    setRuleError({});
    setSaved(null);
    if (allowed && token) {
      void (async () => {
        try {
          const result = await getAlertRules(token, controller.signal);
          if (currentScope.current !== scope || controller.signal.aborted) return;
          setData(result);
          setDrafts(Object.fromEntries(result.regras.map((r) => [r.tipo, draftOf(r)])));
        } catch (reason) {
          if (currentScope.current !== scope || controller.signal.aborted) return;
          if (reason instanceof SessionExpiredError) expireSession();
          else setLoadError("Não foi possível carregar as regras de alerta.");
        } finally {
          if (currentScope.current === scope && !controller.signal.aborted) setLoading(false);
        }
      })();
    }
    return () => {
      controller.abort();
    };
  }, [scope, allowed, token, expireSession]);

  function update(tipo: string, change: Partial<Drafts[string]>) {
    setDrafts((current) => {
      const base = current[tipo];
      if (!base) return current;
      return { ...current, [tipo]: { ...base, ...change } };
    });
    setSaved((value) => (value === tipo ? null : value));
  }

  async function submit(event: FormEvent<HTMLFormElement>, rule: AlertRule) {
    event.preventDefault();
    const draft = drafts[rule.tipo];
    if (!token || !draft || saving) return;
    const parametros: Record<string, number> = {};
    for (const p of rule.parametros) {
      const value = Number(draft.valores[p.nome]);
      if (!Number.isInteger(value) || value < p.minimo || value > p.maximo) {
        setRuleError((current) => ({
          ...current,
          [rule.tipo]: `${p.rotulo}: use um número inteiro entre ${p.minimo} e ${p.maximo} ${p.unidade}.`,
        }));
        return;
      }
      parametros[p.nome] = value;
    }
    setSaving(rule.tipo);
    setSaved(null);
    setRuleError((current) => ({ ...current, [rule.tipo]: "" }));
    try {
      const result = await saveAlertRule(token, rule.tipo, draft.ativo, parametros);
      if (currentScope.current !== scope) return;
      setData((current) =>
        current
          ? {
              ...current,
              regras: current.regras.map((r) => (r.tipo === result.tipo ? result : r)),
            }
          : current,
      );
      setDrafts((current) => ({ ...current, [result.tipo]: draftOf(result) }));
      setSaved(result.tipo);
    } catch (reason) {
      if (currentScope.current !== scope) return;
      if (reason instanceof SessionExpiredError) expireSession();
      else
        setRuleError((current) => ({
          ...current,
          [rule.tipo]:
            reason instanceof ApiError && reason.status === 422
              ? reason.message
              : "Não foi possível salvar a regra.",
        }));
    } finally {
      if (currentScope.current === scope) setSaving(null);
    }
  }

  return (
    <div className="screen admin-screen administration-ux" key="alertas-lider">
      <div className="screen-head">
        <div className="titles">
          <h2>Alertas ao líder</h2>
          <p>Escolha quais situações geram alerta para o líder de célula e quando.</p>
        </div>
      </div>
      {!allowed ? <p role="alert">Somente administradores podem editar estas regras.</p> : null}
      {allowed && loading ? <p role="status">Carregando regras…</p> : null}
      {allowed && !loading && loadError ? (
        <div className="card card-pad">
          <p role="alert">{loadError}</p>
          <DsButton variant="secondary" onClick={() => setReload((value) => value + 1)}>
            Tentar novamente
          </DsButton>
        </div>
      ) : null}
      {allowed && !loading && data ? (
        <>
          {!data.processamentoLiberado ? (
            <DsBanner kind="info">
              A geração de alertas ainda não foi liberada para esta igreja. Você pode deixar as
              regras prontas; nada é gerado até a liberação.
            </DsBanner>
          ) : null}
          {data.regras.map((rule) => {
            const draft = drafts[rule.tipo] ?? draftOf(rule);
            const busy = saving === rule.tipo;
            return (
              <form
                key={rule.tipo}
                className="card card-pad"
                aria-labelledby={`alert-rule-${rule.tipo}`}
                onSubmit={(event) => {
                  void submit(event, rule);
                }}
              >
                <div className="panel-title" id={`alert-rule-${rule.tipo}`}>
                  {rule.titulo}
                </div>
                <p className="sub">{rule.descricao}</p>
                <div className="seg-toggle-row ds-mb-3">
                  <span>{draft.ativo ? "Regra ligada" : "Regra desligada"}</span>
                  <Toggle
                    checked={draft.ativo}
                    onChange={(on) => update(rule.tipo, { ativo: on })}
                    label={`Ligar regra: ${rule.titulo}`}
                    disabled={busy}
                  />
                </div>
                {rule.parametros.map((p) => (
                  <div className="field" key={p.nome}>
                    <label htmlFor={`alert-rule-${rule.tipo}-${p.nome}`}>
                      {p.rotulo} ({p.unidade})
                    </label>
                    <input
                      id={`alert-rule-${rule.tipo}-${p.nome}`}
                      type="number"
                      inputMode="numeric"
                      min={p.minimo}
                      max={p.maximo}
                      step={1}
                      value={draft.valores[p.nome] ?? ""}
                      disabled={busy}
                      onChange={(event) =>
                        update(rule.tipo, {
                          valores: { ...draft.valores, [p.nome]: event.target.value },
                        })
                      }
                    />
                  </div>
                ))}
                {ruleError[rule.tipo] ? <p role="alert">{ruleError[rule.tipo]}</p> : null}
                {saved === rule.tipo ? <p role="status">Regra salva.</p> : null}
                <DsButton type="submit" loading={busy} disabled={Boolean(saving) && !busy}>
                  {busy ? "Salvando…" : "Salvar regra"}
                </DsButton>
              </form>
            );
          })}
        </>
      ) : null}
    </div>
  );
}
