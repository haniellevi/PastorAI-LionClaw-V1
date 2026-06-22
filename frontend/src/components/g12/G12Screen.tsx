"use client";

/**
 * Tela #g12 — Painel do Discipular / organograma de descendências (Visão G12).
 *
 * Renderiza a árvore ministerial a partir de pessoas.lider_id (api-descendencias):
 * cada pessoa é um nó com seus liderados diretos. O usuário começa pela sua
 * liderança e faz drill-down clicando num ramo que já tem time (abrir
 * descendência), navegando pelo breadcrumb. Descendência sem liderados mostra
 * empty-state.
 *
 * Estados: loading · empty · organograma · descendencia (ramo aberto).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import {
  countDescendants,
  fetchDescendencias,
  initials,
  type TreeNode,
} from "@/lib/g12-api";
import { Icon } from "@/lib/icons";
import { tipoLabel } from "@/lib/contacts-api";

type VTab = "arvore" | "indicadores";

const SYNTHETIC_ROOT = "__root__";

export function G12Screen() {
  const { token, expireSession } = useAuth();

  const [roots, setRoots] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [tab, setTab] = useState<VTab>("arvore");
  // Caminho de drill-down (índices de filhos a partir da raiz).
  const [path, setPath] = useState<number[]>([]);

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
        const tree = await fetchDescendencias(token);
        setRoots(tree);
        setPath([]);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar o organograma.");
      } finally {
        setLoading(false);
      }
    },
    [token, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  // Raiz lógica: o único líder de topo, ou um nó sintético sobre a "floresta".
  const rootNode: TreeNode | null = useMemo(() => {
    if (roots.length === 0) return null;
    if (roots.length === 1) return roots[0] ?? null;
    return { id: SYNTHETIC_ROOT, nome: "Liderança principal", tipo: null, children: roots };
  }, [roots]);

  // Sequência de nós do breadcrumb seguindo o path (índices).
  const trail: TreeNode[] = useMemo(() => {
    if (!rootNode) return [];
    const out: TreeNode[] = [rootNode];
    let node = rootNode;
    for (const idx of path) {
      const next = node.children[idx];
      if (!next) break;
      out.push(next);
      node = next;
    }
    return out;
  }, [rootNode, path]);

  const current = trail[trail.length - 1] ?? null;

  const openBranch = useCallback((childIdx: number) => {
    setPath((prev) => [...prev, childIdx]);
  }, []);

  const goToCrumb = useCallback((level: number) => {
    setPath((prev) => prev.slice(0, level));
  }, []);

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="g12">
      <div className="screen-head">
        <div className="actions">
          <button type="button" className="btn btn-sm" onClick={() => void load("retry")} disabled={loading}>
            <Icon name="refresh" />
            <span>Atualizar</span>
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

      <div className="card">
        <div className="panel-title">
          Liderança
          <div className="right">
            <div className="tabs">
              <button
                type="button"
                className={`tab${tab === "arvore" ? " active" : ""}`}
                onClick={() => setTab("arvore")}
              >
                Descendências
              </button>
              <button
                type="button"
                className={`tab${tab === "indicadores" ? " active" : ""}`}
                onClick={() => setTab("indicadores")}
              >
                Indicadores
              </button>
            </div>
          </div>
        </div>

        {showSkeleton ? (
          <div className="org-grid">
            {Array.from({ length: 4 }).map((_, i) => (
              <div className="slot skeleton" key={i}>
                <span className="qicon sk-icon" />
                <div className="qbody">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        ) : !rootNode || !current ? (
          <div className="empty-state" style={{ padding: "var(--s6)" }}>
            <Icon name="g12" />
            <p>
              <strong>Sem descendências para exibir.</strong> Quando houver liderados vinculados
              pela hierarquia, o organograma aparece aqui.
            </p>
          </div>
        ) : tab === "arvore" ? (
          <>
            <div className="org-bar">
              <nav className="org-bc" aria-label="Descendência atual">
                {trail.map((node, i) => {
                  const isLast = i === trail.length - 1;
                  return (
                    <span key={node.id + i} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      {i > 0 ? <span className="sep">/</span> : null}
                      <button
                        type="button"
                        className={`crumb-b${isLast ? " cur" : ""}`}
                        disabled={isLast}
                        onClick={() => goToCrumb(i)}
                      >
                        {node.id === SYNTHETIC_ROOT ? "Liderança principal" : node.nome}
                      </button>
                    </span>
                  );
                })}
              </nav>
            </div>

            {current.id !== SYNTHETIC_ROOT ? (
              <div className="org-leader">
                <span className="av">{initials(current.nome)}</span>
                <div className="ol-body">
                  <h4>{current.nome}</h4>
                  <div className="sub">
                    {tipoLabel(current.tipo)}
                    {trail.length > 1 ? " · descendência aberta" : ""}
                  </div>
                </div>
                <div className="ol-count">
                  <div className="big num">{countDescendants(current)}</div>
                  <div className="cap">liderados</div>
                </div>
              </div>
            ) : null}

            {current.children.length === 0 ? (
              <div className="empty-state" style={{ padding: "var(--s6)" }}>
                <Icon name="user" />
                <p>
                  <strong>Descendência vazia.</strong> {current.id === SYNTHETIC_ROOT ? "Esta pessoa" : current.nome}{" "}
                  ainda não tem liderados no organograma.
                </p>
              </div>
            ) : (
              <div className="org-grid">
                {current.children.map((child, idx) => {
                  const team = countDescendants(child);
                  const hasTeam = child.children.length > 0;
                  return (
                    <button
                      type="button"
                      key={child.id}
                      className={`slot filled${hasTeam ? " has-team" : ""}`}
                      disabled={!hasTeam}
                      aria-disabled={!hasTeam || undefined}
                      onClick={() => hasTeam && openBranch(idx)}
                      title={hasTeam ? "Abrir descendência" : undefined}
                    >
                      <span className="s-av">{initials(child.nome)}</span>
                      <div className="s-body">
                        <div className="nm">{child.nome}</div>
                        <div className="rl">{tipoLabel(child.tipo)}</div>
                        {hasTeam ? <div className="team-n">{team} no time</div> : null}
                      </div>
                      {hasTeam ? <Icon name="caret" className="s-go" /> : null}
                    </button>
                  );
                })}
              </div>
            )}

            <p className="org-hint">
              <Icon name="g12" />
              Clique num card que já tem time para abrir o próximo nível da descendência. Você vê a
              sua linha descendente.
            </p>
          </>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Descendência (G12)</th>
                  <th className="num">Liderados</th>
                  <th>Cargo</th>
                </tr>
              </thead>
              <tbody>
                {(rootNode.id === SYNTHETIC_ROOT ? rootNode.children : [rootNode]).map((node) => (
                  <tr key={node.id}>
                    <td className="nm">{node.nome}</td>
                    <td className="num">{countDescendants(node)}</td>
                    <td className="sub">{tipoLabel(node.tipo)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
