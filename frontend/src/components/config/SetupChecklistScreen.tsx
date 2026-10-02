"use client";

import "@/components/config/administration-ux-v2.css";

/**
 * Tela #setup — checklist de configuração inicial da igreja (Missão 7B-7).
 * Landing padrão da superfície admin (primeiro item de ADMIN_NAV_SECTIONS).
 *
 * Consome GET /setup/checklist: o backend calcula o estado real de cada item
 * (identidade, equipe, células, whatsapp, agente e, só para o dono, plano);
 * aqui só o rótulo/descrição/atalho de navegação — não há bloqueio de tela ou
 * ação em nenhum lugar do sistema, é só um mapa das pendências reais.
 */
import { useCallback, useEffect, useState } from "react";

import { MineralBackdrop } from "@/components/brand/MineralBackdrop";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { Icon, type IconKey } from "@/lib/icons";
import { fetchSetupChecklist, type SetupItem, type SetupItemId } from "@/lib/setup-api";
import { resolveSetupNavAction } from "@/lib/setup-nav";
import { useHashRoute } from "@/lib/use-hash-route";

const ITEM_COPY: Record<
  SetupItemId,
  { label: string; done: string; pending: string; icon: IconKey; cta: string }
> = {
  identidade: {
    label: "Identidade da igreja",
    done: "Logo da igreja configurada.",
    pending: "Sem logo ainda — o sistema mostra o nome da igreja no lugar (opcional).",
    icon: "image",
    cta: "Configurar",
  },
  equipe: {
    label: "Pessoas com acesso",
    done: "Já há mais gente da equipe com acesso além de você.",
    pending: "Só você tem acesso até agora — convide pastores e líderes.",
    icon: "team",
    cta: "Convidar",
  },
  celulas: {
    label: "Células",
    done: "Pelo menos uma célula já está cadastrada.",
    pending: "Nenhuma célula cadastrada ainda.",
    icon: "central-celula",
    cta: "Cadastrar",
  },
  whatsapp: {
    label: "WhatsApp",
    done: "Número oficial conectado.",
    pending: "Número oficial da igreja ainda não conectado.",
    icon: "whatsapp",
    cta: "Conectar",
  },
  agente: {
    label: "Credencial do assistente",
    done: "Credencial do modelo (BYO) configurada. Confira o estado do assistente na configuração.",
    pending: "Credencial do modelo de IA ainda não configurada.",
    icon: "agent",
    cta: "Configurar",
  },
  assinatura: {
    label: "Plano e Assinatura",
    done: "Assinatura ativa.",
    pending: "Assinatura ainda não está ativa.",
    icon: "card",
    cta: "Ver plano",
  },
};

export function SetupChecklistScreen() {
  const { token, expireSession } = useAuth();
  const [, navigate] = useHashRoute();

  const [items, setItems] = useState<SetupItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const checklist = await fetchSetupChecklist(token);
      setItems(checklist.items);
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setError(
        err instanceof ApiError
          ? err.message
          : "Não foi possível carregar o checklist de configuração.",
      );
    } finally {
      setLoading(false);
    }
  }, [token, expireSession]);

  useEffect(() => {
    void load();
  }, [load]);

  const pending = items?.filter((i) => !i.done).length ?? 0;
  const nextItem = items?.find((item) => !item.done && item.id !== "identidade")
    ?? items?.find((item) => !item.done);

  return (
    <div className="screen admin-screen setup-screen administration-ux" key="setup">
      <header className="screen-head admin-overview mineral-surface" data-mineral-surface>
        <MineralBackdrop compact />
        <div className="titles">
          <p className="admin-eyebrow">Primeiros passos</p>
          <h2>Gestão da igreja</h2>
          <p>Confira o cadastro e os acessos da equipe.</p>
        </div>
      </header>
      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load()}
            disabled={loading}
          >
            Tentar novamente
          </button>
        </div>
      ) : null}

      <div className="card">
        <div className="panel-title">
          <h2>Primeiros passos</h2>
          <span className="count">
            {items
              ? pending === 0
                ? "· itens configurados"
                : `· ${pending} pendente${pending > 1 ? "s" : ""}`
              : ""}
          </span>
        </div>

        {loading && !items ? (
          <div className="queue">
            {Array.from({ length: 5 }).map((_, i) => (
              <div className="qitem skeleton" key={i}>
                <span className="qicon sk-icon" />
                <div className="qbody">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        ) : items && items.length > 0 ? (
          <ul className="queue setup-list" aria-label="Tarefas de configuração">
            {items.map((item) => {
              const copy = ITEM_COPY[item.id];
              return (
                <li className="qitem" key={item.id}>
                  <span className={`qicon ${item.done ? "v" : "h"}`}>
                    <Icon name={item.done ? "check" : copy.icon} />
                  </span>
                  <div className="qbody">
                    <strong>{copy.label}</strong>
                    <div className="sub">{item.done ? "Configurado" : item.id === "identidade" ? "Opcional" : "Pendente"}</div>
                    <div className="meta">{item.done ? copy.done : copy.pending}</div>
                  </div>
                  <div className="qactions">
                    <button
                      type="button"
                      className={`btn btn-sm${item.id === nextItem?.id ? " btn-primary" : ""}`}
                      aria-label={`${item.done ? "Ver" : copy.cta}: ${copy.label}`}
                      onClick={() => {
                        const action = resolveSetupNavAction(item);
                        if (action.kind === "external") {
                          window.location.href = action.href;
                        } else {
                          navigate(action.screen);
                        }
                      }}
                    >
                      {item.done ? "Ver" : copy.cta}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
      <p className="sub admin-context">Configurar credencial ou conectar o WhatsApp não ativa o assistente. O estado do agente aparece na sua própria configuração.</p>
    </div>
  );
}
