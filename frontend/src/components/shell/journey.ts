/**
 * Derivações puras da Jornada G12 para o shell (Gate 6.1). Fonte única:
 * lib/navigation.ts + canSee — nada aqui cria rota, estado ou persistência.
 * Puro (sem DOM/React) para permitir regressão em vitest (journey.test.ts).
 */
import type { IconKey } from "@/lib/icons";
import {
  NAV_SECTIONS,
  journeyStageOf,
  journeyStages,
  type NavItem,
  type NavStage,
} from "@/lib/navigation";
import { canSee, type PermissionMatrix } from "@/lib/permissions";
import type { Role } from "@/lib/roles";

export type ModuleGroup = "consolidar" | "discipular";

/** Abas do ModuleTabs = head + subs do estágio em NAV_SECTIONS, sem target
 *  repetido. Pura (extraída do componente) para regressão em vitest. */
export function deriveTabs(group: ModuleGroup): NavItem[] | null {
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

/** Primeiro target navegável da etapa: o head se acessível, senão a primeira
 *  sub visível (pulando telas bloqueadas/sem permissão). null = etapa sem
 *  nenhuma tela acessível ao usuário. Nunca devolve tela locked/sem canSee. */
export function firstVisibleTarget(
  stage: NavStage,
  roles: Role[],
  matrix: PermissionMatrix,
): string | null {
  for (const item of [stage.head, ...(stage.subs ?? [])]) {
    if (!item.locked && canSee(item.target, roles, matrix)) return item.target;
  }
  return null;
}

export interface JourneyNavItem {
  /** screenId existente para onde o clique navega (texto e destino coincidem). */
  target: string;
  label: string;
  icon: IconKey;
  active: boolean;
}

/**
 * Item "Jornada" contextual do bottom-nav. Coerência texto↔destino (Gate 6.1):
 * - dentro de uma etapa (journeyStageOf): label/ícone da etapa e destino = a
 *   PRÓPRIA etapa (primeiro target visível dela) — nunca mostra "Consolidar"
 *   levando para #ganhar;
 * - fora da Jornada: "Jornada" apontando para a primeira etapa acessível — um
 *   lider_mult sem #ganhar mas com #g12 continua vendo o atalho (destino #g12);
 * - nenhuma etapa acessível → null (o atalho some, como canSee manda).
 */
export function journeyNavItem(
  baseRoute: string,
  roles: Role[],
  matrix: PermissionMatrix,
): JourneyNavItem | null {
  const stages = journeyStages();
  const current = journeyStageOf(baseRoute);
  if (current) {
    const st = stages.find((s) => s.stage === current);
    const target = st ? firstVisibleTarget(st, roles, matrix) : null;
    if (st && target) {
      return { target, label: st.head.label, icon: st.head.icon, active: true };
    }
  }
  for (const st of stages) {
    const target = firstVisibleTarget(st, roles, matrix);
    if (target) return { target, label: "Jornada", icon: "ganhar", active: false };
  }
  return null;
}
