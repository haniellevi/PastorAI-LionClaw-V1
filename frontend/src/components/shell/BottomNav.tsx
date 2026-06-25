"use client";

/**
 * Bottom-nav mobile (F3 — mobile-first). Aparece só em telas estreitas (CSS,
 * @media max-width:860px). Atalhos navegam por #hash para os screenIds JÁ
 * EXISTENTES — não cria rota nova. "Mais" abre o drawer da sidebar existente
 * (onMore → mobileOpen do AppShell).
 *
 * Regras (espelham a ModuleTabs / contrato de navegação):
 *  - cada atalho de tela é filtrado por canSee — sem permissão, some;
 *  - "Mais" é ação (não é screen), sempre visível;
 *  - item ativo = rota vigente.
 * Labels são as do design mobile (Hoje/Jornada), apenas cosméticas; o target/
 * screenId é preservado.
 */
import { useAuth } from "@/lib/auth-context";
import { Icon, type IconKey } from "@/lib/icons";
import { canSee } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { useHashRoute } from "@/lib/use-hash-route";

interface BottomNavItem {
  /** screenId existente (não cria rota nova). */
  target: string;
  /** Label do design mobile (cosmético; screenId preservado). */
  label: string;
  icon: IconKey;
}

const ITEMS: BottomNavItem[] = [
  { target: "dashboard", label: "Hoje", icon: "dashboard" },
  { target: "inbox", label: "Conversas", icon: "chat" },
  { target: "ganhar", label: "Jornada", icon: "ganhar" },
];

export function BottomNav({ onMore }: { onMore: () => void }) {
  const { user } = useAuth();
  const { matrix } = usePermissions();
  const [route, navigate] = useHashRoute();

  if (!user) return null;

  // Sem permissão de ver a tela → atalho some.
  const visible = ITEMS.filter((it) => canSee(it.target, user.roles, matrix));

  return (
    <nav className="bottom-nav" aria-label="Navegação rápida">
      {visible.map((it) => {
        const active = route === it.target;
        return (
          <button
            key={it.target}
            type="button"
            className={`bn-item${active ? " active" : ""}`}
            aria-current={active ? "page" : undefined}
            onClick={() => navigate(it.target)}
          >
            <Icon name={it.icon} />
            <span>{it.label}</span>
          </button>
        );
      })}
      <button type="button" className="bn-item" aria-label="Mais — abrir menu" onClick={onMore}>
        <Icon name="menu" />
        <span>Mais</span>
      </button>
    </nav>
  );
}
