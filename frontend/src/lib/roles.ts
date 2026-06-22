/**
 * Papéis acumulados (user_roles — F3) e seus rótulos.
 * Espelha ROLE_DEFS/ROLE_ORDER do artifact travado e o enum de `user_roles`
 * da seção 2.1 do SPEC. Papéis são a base do menu montado pela UNIÃO de acessos.
 */

export type Role =
  | "admin"
  | "pastor"
  | "lider_g12"
  | "lider_consol"
  | "lider_celula"
  | "lider_mult"
  | "operador"
  | "membro";

export interface RoleDef {
  label: string;
  short: string;
  /** Papel de liderança (libera blocos de gestão no dashboard). */
  lead: boolean;
}

export const ROLE_DEFS: Record<Role, RoleDef> = {
  admin: { label: "Administrador", short: "Admin", lead: true },
  pastor: { label: "Pastor", short: "Pastor", lead: true },
  lider_g12: { label: "Líder G12", short: "G12", lead: true },
  lider_consol: { label: "Líder de Consolidação", short: "Consolidação", lead: true },
  lider_celula: { label: "Líder de Célula", short: "Célula", lead: true },
  lider_mult: { label: "Líder de Multiplicação", short: "Multiplicação", lead: true },
  operador: { label: "Operador", short: "Operador", lead: false },
  membro: { label: "Membro", short: "Membro", lead: false },
};

export const ROLE_ORDER: Role[] = [
  "admin",
  "pastor",
  "lider_g12",
  "lider_consol",
  "lider_celula",
  "lider_mult",
  "operador",
  "membro",
];

/** Mantém apenas papéis conhecidos (resiliência a dados externos). */
export function normalizeRoles(roles: readonly string[]): Role[] {
  return roles.filter((r): r is Role => r in ROLE_DEFS);
}

/** Papéis ordenados pela hierarquia de exibição. */
export function sortedRoles(roles: readonly Role[]): Role[] {
  return [...roles].sort((a, b) => ROLE_ORDER.indexOf(a) - ROLE_ORDER.indexOf(b));
}

export function isAdmin(roles: readonly Role[]): boolean {
  return roles.includes("admin");
}

export function isLeader(roles: readonly Role[]): boolean {
  return roles.some((r) => ROLE_DEFS[r]?.lead);
}

/** Rótulo do papel de maior precedência (para saudações/identidade). */
export function primaryRoleLabel(roles: readonly Role[]): string {
  const [first] = sortedRoles(roles);
  return first ? ROLE_DEFS[first].label : ROLE_DEFS.membro.label;
}
