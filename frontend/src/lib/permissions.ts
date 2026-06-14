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
  "enviar",
  "calendario",
  "comunicados",
  "equipe",
] as const;

/** Telas exclusivas de admin (grupo Configuração). */
export const ADMIN_ONLY = [
  "agente",
  "whatsapp",
  "assinatura",
  "gerentes",
  "permissoes",
] as const;

/** Telas legadas: deep-link válido, fora do menu (delta-012). */
export const LEGACY = ["contatos", "celulas", "relatorios"] as const;

export const ALL_SCREENS: readonly string[] = [
  ...MENU_SCREENS,
  ...LEGACY,
  ...ADMIN_ONLY,
];

const ADMIN_ONLY_SET = new Set<string>(ADMIN_ONLY);

/**
 * Matriz default papel -> telas liberadas (seed role_permissions).
 * `dashboard` é sempre garantido (reforçado em runtime).
 */
export const DEFAULT_PERMISSIONS: Record<Exclude<Role, "admin">, readonly string[]> = {
  pastor: [
    "dashboard", "inbox", "ganhar", "consolidar", "consol-individual",
    "universidade-vida", "capacitacao", "g12", "central-celula", "enviar",
    "calendario", "comunicados", "equipe", "contatos", "celulas", "relatorios",
  ],
  lider_g12: [
    "dashboard", "inbox", "ganhar", "consolidar", "consol-individual",
    "universidade-vida", "capacitacao", "g12", "central-celula", "enviar",
    "calendario", "comunicados", "equipe", "contatos", "celulas", "relatorios",
  ],
  lider_consol: [
    "dashboard", "inbox", "ganhar", "consolidar", "consol-individual",
    "universidade-vida", "calendario", "comunicados", "contatos",
  ],
  lider_celula: [
    "dashboard", "ganhar", "central-celula", "capacitacao", "calendario",
    "celulas", "relatorios",
  ],
  lider_mult: [
    "dashboard", "g12", "central-celula", "enviar", "calendario", "celulas",
    "relatorios",
  ],
  membro: ["dashboard", "calendario"],
};

export type PermissionMatrix = Partial<Record<Exclude<Role, "admin">, readonly string[]>>;

/**
 * Telas visíveis no menu para um conjunto de papéis acumulados.
 * Admin vê tudo; demais papéis somam suas telas (sem ADMIN_ONLY).
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
    for (const screen of perms[role] ?? []) {
      set.add(screen);
    }
  }
  return ALL_SCREENS.filter((s) => set.has(s) && !ADMIN_ONLY_SET.has(s));
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
