"use client";

/**
 * Abas de módulo (F2 — navegação). No topo dos módulos Consolidar e Discipular,
 * expõe as sub-telas do estágio como abas que navegam por #hash para os
 * screenIds JÁ EXISTENTES — preserva canSee/locked/deep-link, sem rota nova.
 *
 * A lista de abas é DERIVADA de NAV_SECTIONS (lib/navigation.ts): head + subs do
 * estágio, sem duplicar target. Fonte única com a Sidebar — não há rota
 * hardcoded aqui. Regras (delta-010 / contrato 4.2):
 *  - tela em LOCKED/futuro (NavItem.locked): aba desabilitada com cadeado, não navega;
 *  - tela sem permissão (canSee=false): NÃO renderiza;
 *  - aba ativa = rota vigente.
 * Se o grupo não for derivável de NAV_SECTIONS, não renderiza nada (sem fallback
 * hardcoded).
 */
import { useAuth } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import { NAV_SECTIONS, SCREEN_META, type NavItem } from "@/lib/navigation";
import { canSee } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { useHashRoute } from "@/lib/use-hash-route";

type ModuleGroup = "consolidar" | "discipular";

/** Abas do grupo = head + subs do estágio em NAV_SECTIONS, sem target repetido. */
function deriveTabs(group: ModuleGroup): NavItem[] | null {
  for (const section of NAV_SECTIONS) {
    const stage = section.stages?.find((st) => st.stage === group);
    if (!stage) continue;
    const seen = new Set<string>();
    const tabs: NavItem[] = [];
    for (const item of [stage.head, ...(stage.subs ?? [])]) {
      if (seen.has(item.target)) continue;
      seen.add(item.target);
      tabs.push(item);
    }
    return tabs;
  }
  return null;
}

export function ModuleTabs({ group }: { group: ModuleGroup }) {
  const { user } = useAuth();
  const { matrix } = usePermissions();
  const [route, navigate] = useHashRoute();

  const tabs = deriveTabs(group);
  if (!tabs || !user) return null;

  // Locked sempre aparece (cadeado); sem permissão some.
  const visible = tabs.filter(
    (t) => t.locked || canSee(t.target, user.roles, matrix),
  );
  if (visible.length <= 1) return null;

  return (
    <div className="tabs module-tabs" role="tablist">
      {visible.map((t) => {
        const label = SCREEN_META[t.target]?.title ?? t.label;
        if (t.locked) {
          return (
            <button
              key={t.target}
              type="button"
              role="tab"
              className="tab locked"
              disabled
              title="Disponível em breve"
            >
              {label} <Icon name="lock" />
            </button>
          );
        }
        const active = route === t.target;
        return (
          <button
            key={t.target}
            type="button"
            role="tab"
            aria-selected={active}
            className={`tab${active ? " active" : ""}`}
            onClick={() => navigate(t.target)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
