"use client";

/**
 * Abas de módulo (F2 — navegação; repaginadas no Gate 6 com a fundação
 * Diamante Lapidado). No topo dos módulos Consolidar e Discipular, expõe as
 * sub-telas do estágio como NAVEGAÇÃO por #hash para screenIds JÁ EXISTENTES —
 * preserva canSee/locked/deep-link, sem rota nova.
 *
 * Semântica (Gate 6): isto é navegação entre ROTAS, não tabs de conteúdo —
 * portanto <nav> + aria-current="page", sem role=tab apontando para tabpanel
 * inexistente. Visual e comportamento de rolagem vêm da fundação (classes
 * ds-tabs-* + useTabStrip): scroll real sem scrollbar visual, véu/chevron de
 * continuidade que somem no fim, item ativo revelado só com scrollLeft.
 *
 * A lista de abas é DERIVADA de NAV_SECTIONS (lib/navigation.ts): head + subs
 * do estágio, sem duplicar target. Fonte única com a Sidebar — não há rota
 * hardcoded aqui. Regras (delta-010 / contrato 4.2):
 *  - tela em LOCKED/futuro (NavItem.locked): aba desabilitada com cadeado, não navega;
 *  - tela sem permissão (canSee=false): NÃO renderiza;
 *  - aba ativa = rota vigente.
 * Se o grupo não for derivável de NAV_SECTIONS, não renderiza nada (sem fallback
 * hardcoded).
 */
import { useRef } from "react";

import { useTabStrip } from "@/components/ds/useTabStrip";
import { useAuth } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import { SCREEN_META } from "@/lib/navigation";
import { canSee } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { useHashRoute } from "@/lib/use-hash-route";

import { deriveTabs, type ModuleGroup } from "./journey";

const GROUP_LABEL: Record<ModuleGroup, string> = {
  consolidar: "Vistas do módulo Consolidar",
  discipular: "Vistas do módulo Discipular",
};

export function ModuleTabs({ group }: { group: ModuleGroup }) {
  const { user } = useAuth();
  const { matrix } = usePermissions();
  const [route] = useHashRoute();
  const listRef = useRef<HTMLDivElement | null>(null);
  const wrapRef = useRef<HTMLElement | null>(null);

  // Base da rota (ignora param de deep-link).
  const slash = route.indexOf("/");
  const base = slash === -1 ? route : route.slice(0, slash);

  useTabStrip(listRef, wrapRef, base);

  const tabs = deriveTabs(group);
  if (!tabs || !user) return null;

  // Locked sempre aparece (cadeado); sem permissão some.
  const visible = tabs.filter(
    (t) => t.locked || canSee(t.target, user.roles, matrix),
  );
  if (visible.length <= 1) return null;

  return (
    <nav
      ref={wrapRef}
      className="ds-tabs-wrap module-tabs"
      aria-label={GROUP_LABEL[group]}
    >
      <div className="ds-tabs-scroll">
        <div ref={listRef} className="ds-tabs">
          {visible.map((t) => {
            const label = SCREEN_META[t.target]?.title ?? t.label;
            if (t.locked) {
              return (
                <button
                  key={`${t.target}-locked`}
                  type="button"
                  className="ds-tab ds-tab--locked"
                  disabled
                  title="Disponível em breve"
                >
                  {label}
                  <Icon name="lock" />
                  {/* Gate 6.1: "em breve" audível — title não é nome acessível. */}
                  <span className="sr-only"> — disponível em breve</span>
                </button>
              );
            }
            const active = base === t.target;
            // Gate 6.1: navegação entre hashes = LINK real (href="#…") — o
            // hashchange nativo alimenta o useHashRoute; permissões/locked/
            // deep-link inalterados.
            return (
              <a
                key={t.target}
                href={`#${t.target}`}
                aria-current={active ? "page" : undefined}
                data-strip-active={active ? "true" : undefined}
                className={active ? "ds-tab ds-tab--active" : "ds-tab"}
              >
                {label}
              </a>
            );
          })}
        </div>
      </div>
      <span className="ds-tabs-chevron" aria-hidden="true">
        ›
      </span>
    </nav>
  );
}
