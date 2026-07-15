"use client";

/**
 * Bottom-nav mobile (F3 — mobile-first). Aparece só em telas estreitas (CSS,
 * @media max-width:860px). Atalhos navegam por #hash para os screenIds JÁ
 * EXISTENTES — não cria rota nova. "Mais" abre o drawer da sidebar existente
 * (onMore → mobileOpen do AppShell), com aria-expanded/aria-controls.
 *
 * Regras (espelham a ModuleTabs / contrato de navegação):
 *  - cada atalho de tela é filtrado por canSee — sem permissão, some;
 *  - "Mais" é ação (não é screen), sempre visível;
 *  - item ativo = rota vigente.
 *
 * `route` vem JÁ RESOLVIDA do AppShell (mesma prop que a Sidebar/Topbar
 * recebem — revisão externa M7B-Visual-W1 achado #2): o BottomNav NÃO lê o
 * hash cru por conta própria. Antes recalculava via useHashRoute() interno, o
 * que podia mostrar item ativo divergente da Sidebar por um instante quando o
 * deep-link pedido era bloqueado/sem permissão (o AppShell já resolveu pra
 * #dashboard antes de renderizar; o BottomNav via o hash cru até o
 * hashchange do redirect chegar).
 *
 * "Jornada" é contextual (Gate 6.1 — derivação em journey.ts): dentro de uma
 * etapa G12 o atalho mostra a etapa E navega para ela (texto e destino
 * coincidem); fora, mostra "Jornada" apontando para a primeira etapa acessível
 * — cobre lider_mult (sem #ganhar, com #g12). Sem persistência nem rota nova.
 */
import { useAuth } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import { canSee } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";

import { journeyNavItem } from "./journey";
import { SHELL_DRAWER_ID } from "./useDrawerA11y";

const SHORTCUTS = [
  { target: "dashboard", label: "Hoje", icon: "dashboard" as const },
  { target: "inbox", label: "Conversas", icon: "chat" as const },
];

export function BottomNav({
  route,
  onMore,
  menuOpen,
}: {
  /** Rota já resolvida pelo AppShell (mesma fonte que Sidebar/Topbar). */
  route: string;
  onMore: () => void;
  menuOpen: boolean;
}) {
  const { user } = useAuth();
  const { matrix } = usePermissions();

  if (!user) return null;

  // Sem permissão de ver a tela → atalho some.
  const visible = SHORTCUTS.filter((it) => canSee(it.target, user.roles, matrix));

  const journey = journeyNavItem(route, user.roles, matrix);

  return (
    <nav className="bottom-nav" aria-label="Navegação rápida">
      {/* Gate 6.2: navegação por hash = LINKS reais (como ModuleTabs); "Mais"
          continua botão — é ação (abre o drawer), não rota. */}
      {visible.map((it) => {
        const active = route === it.target;
        return (
          <a
            key={it.target}
            href={`#${it.target}`}
            className={`bn-item${active ? " active" : ""}`}
            aria-current={active ? "page" : undefined}
          >
            <Icon name={it.icon} />
            <span>{it.label}</span>
          </a>
        );
      })}
      {journey ? (
        <a
          href={`#${journey.target}`}
          className={`bn-item${journey.active || route === journey.target ? " active" : ""}`}
          aria-current={journey.active || route === journey.target ? "page" : undefined}
        >
          <Icon name={journey.icon} />
          <span>{journey.label}</span>
        </a>
      ) : null}
      <button
        type="button"
        className="bn-item"
        aria-label="Mais — abrir menu"
        aria-expanded={menuOpen}
        aria-controls={SHELL_DRAWER_ID}
        onClick={onMore}
      >
        <Icon name="menu" />
        <span>Mais</span>
      </button>
    </nav>
  );
}
