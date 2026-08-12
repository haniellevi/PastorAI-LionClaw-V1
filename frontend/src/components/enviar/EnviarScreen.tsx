"use client";

/**
 * Tela #enviar — panorama de multiplicações (somente leitura).
 *
 * O fluxo de multiplicação foi unificado no módulo Células (PR3–PR9): a
 * multiplicação NASCE como solicitação na tela "Minha Célula" (líder) e é
 * DECIDIDA na "Central de Célula" (pastor/admin). Esta tela do estágio Enviar
 * mostra o panorama consolidado — pendentes (solicitações aguardando) e
 * registradas (já efetivadas) — sem ações de escrita.
 *
 * GET /multiplicacoes é superfície da Central; para papéis sem esse acesso a
 * tela mostra um aviso apontando para onde a multiplicação acontece.
 */
import { useCallback, useEffect, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import {
  getMultiplicacoesList,
  type MultiplicacaoPendente,
  type MultiplicacaoRegistrada,
  type MultiplicacoesListOut,
} from "@/lib/multiplicacoes-api";

function formatDate(iso: string | null): string {
  if (!iso) return "Sem data";
  const datePart = iso.split("T")[0] ?? iso;
  const [y, m, d] = datePart.split("-");
  if (!y || !m || !d) return iso;
  return `${d}/${m}/${y}`;
}

function payloadName(p: MultiplicacaoPendente): string {
  const nome = p.payload_proposto?.["nome_nova_celula"];
  return typeof nome === "string" && nome ? nome : "Nova célula";
}

export function EnviarScreen() {
  const { token, expireSession } = useAuth();

  const [data, setData] = useState<MultiplicacoesListOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [restricted, setRestricted] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    setRestricted(false);
    try {
      setData(await getMultiplicacoesList(token));
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setRestricted(true);
      } else {
        setError(
          err instanceof ApiError
            ? err.message
            : "Não foi possível carregar as multiplicações.",
        );
      }
    } finally {
      setLoading(false);
    }
  }, [token, expireSession]);

  useEffect(() => {
    void load();
  }, [load]);

  const pendentes = data?.pendentes ?? [];
  const registradas = data?.registradas ?? [];

  return (
    <div className="screen journey-screen journey-screen--enviar" key="enviar">
      <div className="screen-head">
        <div className="titles">
          <h2>Multiplicações</h2>
          <p>Acompanhe pedidos e registros que fortalecem a próxima geração.</p>
        </div>
      </div>
      <div className="info-banner" role="note">
        <Icon name="info" />
        <span>
          A multiplicação é <strong>solicitada</strong> pelo líder em{" "}
          <em>Minha Célula</em> e <strong>decidida</strong> pela Central em{" "}
          <em>Central de Célula</em>. Aqui você acompanha o panorama.
        </span>
      </div>

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

      {restricted ? (
        <div className="card">
          <div className="empty-state" style={{ padding: "var(--s6)" }}>
            <Icon name="lock" />
            <p>
              <strong>Panorama restrito à Central de Célula.</strong> A
              multiplicação da sua célula é solicitada em <em>Minha Célula</em>.
            </p>
          </div>
        </div>
      ) : loading ? (
        <div className="card">
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
        </div>
      ) : (
        <>
          <div className="card">
            <div className="panel-title">
              Pendentes
              {pendentes.length ? (
                <span className="count">· {pendentes.length}</span>
              ) : null}
            </div>
            {pendentes.length === 0 ? (
              <div className="empty-state" style={{ padding: "var(--s6)" }}>
                <Icon name="send" />
                <p>
                  <strong>Nenhuma multiplicação aguardando decisão.</strong>
                </p>
              </div>
            ) : (
              <div className="queue">
                {pendentes.map((p: MultiplicacaoPendente) => (
                  <div className="qitem" key={p.id}>
                    <span className="qicon h">
                      <Icon name="user" />
                    </span>
                    <div className="qbody">
                      <strong>{payloadName(p)}</strong>
                      <div className="meta">
                        Solicitada em {formatDate(p.created_at)}
                      </div>
                    </div>
                    <StatusPill tone="warn">Aguardando</StatusPill>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card">
            <div className="panel-title">
              Registradas
              {registradas.length ? (
                <span className="count">· {registradas.length}</span>
              ) : null}
            </div>
            {registradas.length === 0 ? (
              <div className="empty-state" style={{ padding: "var(--s6)" }}>
                <Icon name="check" />
                <p>
                  <strong>Nenhuma multiplicação registrada ainda.</strong>
                </p>
              </div>
            ) : (
              <div className="queue">
                {registradas.map((m: MultiplicacaoRegistrada) => (
                  <div className="qitem" key={m.id}>
                    <span className="qicon v">
                      <Icon name="check" />
                    </span>
                    <div className="qbody">
                      <strong>Multiplicação concluída</strong>
                      <div className="meta">
                        {m.data_prevista
                          ? `Data prevista ${formatDate(m.data_prevista)}`
                          : "Sem data prevista"}
                        {m.descendencia ? ` · descendência ${m.descendencia}` : ""}
                      </div>
                    </div>
                    <StatusPill tone="ok">Registrada</StatusPill>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
