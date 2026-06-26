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
import { useAuth } from "@/lib/auth-context";
import {
  STAGE_ACCENT,
  journeyStageOf,
  journeyStages,
} from "@/lib/navigation";
import { canSee } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { useHashRoute } from "@/lib/use-hash-route";

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

  // Visibilidade igual à Sidebar: etapa sem canSee no head some.
  const stages = journeyStages().filter((st) =>
    canSee(st.head.target, user.roles, matrix),
  );
  if (stages.length <= 1) return null;

  return (
    <nav className="journey-stepper" aria-label="Etapas da Jornada G12">
      <ol>
        {stages.map((st, i) => {
          const isActive = st.stage === active;
          return (
            <li className="journey-step" key={st.stage}>
              <button
                type="button"
                className={`journey-step-btn${isActive ? " active" : ""}`}
                data-accent={STAGE_ACCENT[st.stage]}
                aria-current={isActive ? "step" : undefined}
                onClick={() => navigate(st.head.target)}
              >
                <span className="journey-step-num" aria-hidden="true">
                  {i + 1}
                </span>
                <span className="journey-step-lbl">{st.head.label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
