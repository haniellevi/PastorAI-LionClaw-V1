/**
 * role_permissions (matriz papel x tela — delta-010) como FONTE DE VERDADE
 * dos acessos. Aqui modelamos o default de seed (SPEC 2.4 / artifact PERMS);
 * uma futura API de permissões pode substituir `DEFAULT_PERMISSIONS` sem mudar
 * a lógica de união. Regras (SPEC 2.1 / 4.2):
 *  - `admin` tem acesso implícito a tudo;
 *  - `dashboard` é garantido a todos os papéis;
 *  - telas de Configuração (ADMIN_ONLY) só aparecem para admin;
 *  - o menu é a UNIÃO dos acessos de todos os papéis acumulados.
 */

import type { Role } from "./roles";

/** Telas operacionais que podem aparecer no menu. */
export const MENU_SCREENS = [
  "dashboard",
  "inbox",
  "ganhar",
  "consolidar",
  "consol-individual",
  "universidade-vida",
  "capacitacao",
  "g12",
  "central-celula",
  "minha-celula",
  "enviar",
  "calendario",
] as const;

/** Telas exclusivas de admin (superfície administrativa — /gestao). */
export const ADMIN_ONLY = [
  "setup",
  "contatos",
  "comunicados",
  "identidade",
  "equipe",
  "permissoes",
  "integracoes",
  "whatsapp",
  "agente",
  "assinatura",
] as const;

/** Telas legadas: deep-link válido, fora do menu (delta-012). */
export const LEGACY = ["celulas", "relatorios"] as const;

/**
 * Telas CENTRAL-ONLY: só `pastor` (e `admin`, implícito) — NUNCA outro papel,
 * mesmo que a matriz PERSISTIDA do tenant conceda. Igual ao ADMIN_ONLY, a regra
 * é aplicada ANTES da matriz, não depois; linhas já salvas em `role_permissions`
 * não são apagadas, apenas ignoradas para estas telas.
 *
 * `relatorios` lista relatórios de TODAS as células com oferta e observações;
 * GET /reports exige a Central (`require_central`), então oferecer a tela a
 * outro papel só renderizaria um 403. Espelha CENTRAL_ONLY de
 * `backend/app/domain/permissions.py`.
 */
export const CENTRAL_ONLY = ["relatorios"] as const;

/** Papel que enxerga as telas CENTRAL_ONLY (espelha CENTRAL_ROLE do backend). */
export const CENTRAL_ROLE = "pastor";

export const ALL_SCREENS: readonly string[] = [
  ...MENU_SCREENS,
  ...LEGACY,
  ...ADMIN_ONLY,
];

const ADMIN_ONLY_SET = new Set<string>(ADMIN_ONLY);
const CENTRAL_ONLY_SET = new Set<string>(CENTRAL_ONLY);

/**
 * Matriz default papel -> telas liberadas (seed role_permissions).
 * `dashboard` é sempre garantido (reforçado em runtime).
 */
export const DEFAULT_PERMISSIONS: Record<Exclude<Role, "admin">, readonly string[]> = {
  pastor: [
    "dashboard",
    "inbox",
    "ganhar",
    "consolidar",
    "consol-individual",
    "universidade-vida",
    "capacitacao",
    "g12",
    "central-celula",
    "enviar",
    "calendario",
    "celulas",
    "relatorios",
  ],
  // Central de Célula = pastor/admin no MVP (decisão 3.1 / contrato UX §4).
  // Os papéis de líder NÃO veem 'central-celula' (o menu abriria uma tela de
  // "Acesso restrito"); o líder gere sua célula por 'minha-celula'.
  // 'relatorios' segue a mesma regra: a listagem é tenant-wide e expõe oferta e
  // observações de TODAS as células (GET /reports exige pastor/admin). O líder
  // lê o relatório da própria célula por 'minha-celula'.
  lider_g12: [
    "dashboard",
    "inbox",
    "ganhar",
    "consolidar",
    "consol-individual",
    "universidade-vida",
    "capacitacao",
    "g12",
    "minha-celula",
    "enviar",
    "calendario",
    "celulas",
  ],
  lider_consol: [
    "dashboard",
    "inbox",
    "ganhar",
    "consolidar",
    "consol-individual",
    "universidade-vida",
    "calendario",
  ],
  lider_celula: [
    "dashboard",
    "inbox",
    "ganhar",
    "minha-celula",
    "capacitacao",
    "calendario",
    "celulas",
  ],
  lider_mult: [
    "dashboard",
    "g12",
    "minha-celula",
    "enviar",
    "calendario",
    "celulas",
  ],
  operador: [
    "dashboard",
    "inbox",
    "ganhar",
    "celulas",
  ],
  membro: ["dashboard", "minha-celula", "calendario"],
};

export type PermissionMatrix = Partial<Record<Exclude<Role, "admin">, readonly string[]>>;

/**
 * Telas visíveis no menu para um conjunto de papéis acumulados.
 * Admin vê tudo; demais papéis somam suas telas (sem ADMIN_ONLY).
 *
 * CENTRAL_ONLY é filtrado POR PAPEL, antes da união — mesmo ponto de aplicação
 * de `screens_for_role` no backend. Filtrar depois, olhando só o ator, deixaria
 * a concessão de um papel não-Central passar por carona: com
 * `{ pastor: ["inbox"], operador: ["relatorios"] }`, o usuário pastor+operador
 * herdaria `relatorios` do operador mesmo com a concessão do pastor removida.
 */
export function allowedScreens(
  roles: readonly Role[],
  perms: PermissionMatrix = DEFAULT_PERMISSIONS,
): string[] {
  if (roles.includes("admin")) {
    return [...ALL_SCREENS];
  }

  const set = new Set<string>(["dashboard"]);

  for (const role of roles) {
    if (role === "admin") continue;
    const isCentral = role === CENTRAL_ROLE;

    for (const screen of perms[role] ?? []) {
      // Só o papel `pastor` pode contribuir com uma tela Central-only.
      if (!isCentral && CENTRAL_ONLY_SET.has(screen)) continue;
      set.add(screen);
    }
  }

  return ALL_SCREENS.filter(
    (screen) => set.has(screen) && !ADMIN_ONLY_SET.has(screen),
  );
}

/** Indica se o usuário pode acessar uma tela específica (inclui legadas/admin). */
export function canSee(
  screenId: string,
  roles: readonly Role[],
  perms: PermissionMatrix = DEFAULT_PERMISSIONS,
): boolean {
  if (roles.includes("admin")) {
    return ALL_SCREENS.includes(screenId);
  }

  if (ADMIN_ONLY_SET.has(screenId)) {
    return false;
  }

  return allowedScreens(roles, perms).includes(screenId);
}
