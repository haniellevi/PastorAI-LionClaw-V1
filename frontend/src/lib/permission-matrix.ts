import type { PermissionMatrix } from "./permissions";

/** Parse only the server-confirmed authority envelope. Never substitute defaults. */
export function parsePermissionMatrix(value: unknown): PermissionMatrix | null {
  if (!value || typeof value !== "object" || !("matriz" in value)) return null;
  const dto = value.matriz;
  if (!dto || typeof dto !== "object" || Array.isArray(dto)) return null;
  const matrix: PermissionMatrix = {};
  for (const role of ["pastor", "lider_g12", "lider_consol", "lider_celula", "lider_mult", "operador", "membro"] as const) {
    const screens = (dto as Record<string, unknown>)[role];
    if (screens !== undefined && (!Array.isArray(screens) || !screens.every((screen) => typeof screen === "string"))) return null;
    matrix[role] = screens === undefined ? [] : [...screens as string[]];
  }
  return matrix;
}
