/**
 * Cliente da API da matriz de permissões papel × tela (tela #permissoes).
 * Consome o backend (sprint-009 / delta-010):
 *
 *   GET /roles/permissions  -> { matriz: { papel: [telas] } }   (api-role-perms)
 *   PUT /roles/permissions  -> { matriz: { papel: [telas] } }
 *
 * role_permissions é a FONTE DE VERDADE do menu. `dashboard` é garantido a todo
 * papel e o backend o força mesmo se omitido (delta-010); `admin` tem acesso
 * implícito a tudo e não participa da matriz.
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";
import type { PermissionMatrix } from "./permissions";
import type { Role } from "./roles";

interface MatrixDto {
  matriz: Record<string, string[]>;
}

type MatrixRole = Exclude<Role, "admin">;

const MATRIX_ROLES: MatrixRole[] = [
  "pastor",
  "lider_g12",
  "lider_consol",
  "lider_celula",
  "lider_mult",
  "membro",
];

function toMatrix(dto: MatrixDto): PermissionMatrix {
  const matrix: PermissionMatrix = {};
  for (const role of MATRIX_ROLES) {
    matrix[role] = dto.matriz[role] ?? [];
  }
  return matrix;
}

export async function fetchPermissions(token: string): Promise<PermissionMatrix> {
  const res = await authedFetch(token, "/roles/permissions");
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar as permissões.");
  }
  return toMatrix((await res.json()) as MatrixDto);
}

export async function savePermissions(
  token: string,
  matrix: PermissionMatrix,
): Promise<PermissionMatrix> {
  const matriz: Record<string, string[]> = {};
  for (const role of MATRIX_ROLES) {
    matriz[role] = [...(matrix[role] ?? [])];
  }
  const res = await authedFetch(token, "/roles/permissions", {
    method: "PUT",
    body: JSON.stringify({ matriz }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível salvar as permissões.");
  }
  return toMatrix((await res.json()) as MatrixDto);
}
