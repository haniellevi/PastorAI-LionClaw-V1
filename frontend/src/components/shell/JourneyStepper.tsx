"use client";

/**
 * Stepper da Jornada G12 (F2 — navegação). Trilha horizontal in-content que
 * mostra as 4 etapas ganhar → consolidar → discipular → enviar como sequência,
 * com a etapa atual destacada (aria-current="step"). Aparece acima do conteúdo
 * das telas da Jornada (e acima das ModuleTabs em Consolidar/Discipular).
 *
 * Fonte única com Sidebar/ModuleTabs (lib/navigation.ts): deriva de
 * NAV_SECTIONS e navega por #hash para os head.target JÁ EXISTENTES — não cria
 * rota nova. Regras de visibilidade espelham a Sidebar:
 *  - etapa sem permissão (canSee=false) NÃO aparece;
 *  - sub-telas mapeiam para a etapa pai via journeyStageOf;
 *  - fora da Jornada (journeyStageOf=null) não renderiza nada.
 */
import type { SessionUser } from "@/lib/auth-context";
import { useAuth } from "@/lib/auth-context";
import {
  STAGE_ACCENT,
  journeyStageOf,
  journeyStages,
  type NavStage,
} from "@/lib/navigation";
import { canSee, type PermissionMatrix } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { useHashRoute } from "@/lib/use-hash-route";

interface JourneyStep {
  stage: NavStage["stage"];
  label: string;
  /** Primeiro target navegável da etapa (head ou 1ª sub visível). */
  target: string;
}

/** Primeiro target navegável da etapa: o head se acessível, senão a primeira
 *  sub visível (pulando telas bloqueadas/sem permissão). null = etapa sem
 *  nenhuma tela acessível ao usuário. Mantém permissões: nunca devolve um
 *  target que o usuário não pode ver (e nunca uma tela locked). */
function firstVisibleTarget(
  stage: NavStage,
  user: SessionUser,
  matrix: PermissionMatrix,
): string | null {
  for (const item of [stage.head, ...(stage.subs ?? [])]) {
    if (!item.locked && canSee(item.target, user.roles, matrix)) return item.target;
  }
  return null;
}

export function JourneyStepper() {
  const { user } = useAuth();
  const { matrix } = usePermissions();
  const [route, navigate] = useHashRoute();

  if (!user) return null;

  // Base da rota (ignora param de deep-link, ex.: "contatos/<id>").
  const slash = route.indexOf("/");
  const base = slash === -1 ? route : route.slice(0, slash);

  const active = journeyStageOf(base);
  if (!active) return null;

  // Etapa visível = tem ≥1 target navegável (head ou sub). O chip navega para
  // esse target — ex.: Discipular com #g12 bloqueado e #central-celula visível
  // aparece e leva a #central-celula. Sem rota nova; permissões preservadas.
  const steps = journeyStages()
    .map((st): JourneyStep | null => {
      const target = firstVisibleTarget(st, user, matrix);
      return target ? { stage: st.stage, label: st.head.label, target } : null;
    })
    .filter((s): s is JourneyStep => s !== null);

  if (steps.length <= 1) return null;
  // Defensivo: nunca renderizar a trilha sem a etapa atual representável.
  if (!steps.some((s) => s.stage === active)) return null;

  return (
    <nav className="journey-stepper" aria-label="Etapas da Jornada G12">
      <ol>
        {steps.map((s, i) => {
          const isActive = s.stage === active;
          return (
            <li className="journey-step" key={s.stage}>
              <button
                type="button"
                className={`journey-step-btn${isActive ? " active" : ""}`}
                data-accent={STAGE_ACCENT[s.stage]}
                aria-current={isActive ? "step" : undefined}
                onClick={() => navigate(s.target)}
              >
                <span className="journey-step-num" aria-hidden="true">
                  {i + 1}
                </span>
                <span className="journey-step-lbl">{s.label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
