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
import { useRef } from "react";

import { useTabStrip } from "@/components/ds/useTabStrip";
import { useAuth } from "@/lib/auth-context";
import {
  STAGE_ACCENT,
  journeyStageOf,
  journeyStages,
  type NavStage,
} from "@/lib/navigation";
import { usePermissions } from "@/lib/permissions-context";
import { useHashRoute } from "@/lib/use-hash-route";

import { firstVisibleTarget } from "./journey";

interface JourneyStep {
  stage: NavStage["stage"];
  label: string;
  /** Primeiro target navegável da etapa (head ou 1ª sub visível). */
  target: string;
}

export function JourneyStepper() {
  const { user } = useAuth();
  const { matrix } = usePermissions();
  const [route] = useHashRoute();
  const listRef = useRef<HTMLOListElement | null>(null);
  const wrapRef = useRef<HTMLElement | null>(null);

  // Base da rota (ignora param de deep-link, ex.: "contatos/<id>").
  const slash = route.indexOf("/");
  const base = slash === -1 ? route : route.slice(0, slash);

  // Gate 6.1: mesma faixa rolável da fundação (véu de continuidade que some no
  // fim + etapa atual revelada só com scrollLeft) — a scrollbar nativa some no
  // mobile (CSS .journey-scroll), o scroll real por toque/teclado fica.
  useTabStrip(listRef, wrapRef, base);

  if (!user) return null;

  const active = journeyStageOf(base);
  if (!active) return null;

  // Etapa visível = tem ≥1 target navegável (head ou sub). O chip navega para
  // esse target — ex.: Discipular com #g12 bloqueado e #central-celula visível
  // aparece e leva a #central-celula. Sem rota nova; permissões preservadas.
  const steps = journeyStages()
    .map((st): JourneyStep | null => {
      const target = firstVisibleTarget(st, user.roles, matrix);
      return target ? { stage: st.stage, label: st.head.label, target } : null;
    })
    .filter((s): s is JourneyStep => s !== null);

  if (steps.length <= 1) return null;
  // Defensivo: nunca renderizar a trilha sem a etapa atual representável.
  if (!steps.some((s) => s.stage === active)) return null;

  return (
    <nav ref={wrapRef} className="journey-stepper" aria-label="Etapas da Jornada G12">
      <div className="journey-scroll">
        <ol ref={listRef}>
          {steps.map((s, i) => {
            const isActive = s.stage === active;
            return (
              <li
                className="journey-step"
                key={s.stage}
                data-strip-active={isActive ? "true" : undefined}
              >
                {/* Gate 6.2: navegação por hash = LINK real (como ModuleTabs) —
                    destino/permissões idênticos, hashchange nativo. */}
                <a
                  href={`#${s.target}`}
                  className={`journey-step-btn${isActive ? " active" : ""}`}
                  data-accent={STAGE_ACCENT[s.stage]}
                  aria-current={isActive ? "step" : undefined}
                >
                  <span className="journey-step-num" aria-hidden="true">
                    {i + 1}
                  </span>
                  <span className="journey-step-lbl">{s.label}</span>
                </a>
              </li>
            );
          })}
        </ol>
      </div>
      {/* Affordances de continuação (par do véu): decorativas — fora da árvore
          de acessibilidade e sem interceptar toque. A direita some no fim
          (data-at-end); a esquerda só aparece com conteúdo cortado atrás
          (data-at-start="false" — Gate 6.3). */}
      <span className="journey-chevron journey-chevron--left" aria-hidden="true">
        ‹
      </span>
      <span className="journey-chevron" aria-hidden="true">
        ›
      </span>
    </nav>
  );
}
