/**
 * Telas CENTRAL_ONLY vencem a matriz PERSISTIDA (REPORT-SOT-REMEDIATION-1).
 *
 * Antes, tirar `relatorios` só de DEFAULT_PERMISSIONS não bastava: um tenant que
 * já tivesse salvo `operador -> relatorios` continuava com `canSee` true, o
 * AppShell renderizava #relatorios e o GET /reports respondia 403.
 *
 * Espelha backend/tests/test_permissions_central_only.py.
 */
import { describe, expect, it } from "vitest";

import {
  allowedScreens,
  canSee,
  CENTRAL_ONLY,
  CENTRAL_ROLE,
  type PermissionMatrix,
} from "./permissions";
import type { Role } from "./roles";

const RELATORIOS = "relatorios";

const NAO_CENTRAL: Role[] = [
  "operador",
  "lider_celula",
  "lider_g12",
  "lider_mult",
  "lider_consol",
  "membro",
];

describe("CENTRAL_ONLY — matriz customizada não reabre a tela", () => {
  it("declara relatorios como Central-only e pastor como papel Central", () => {
    expect(CENTRAL_ONLY).toContain(RELATORIOS);
    expect(CENTRAL_ROLE).toBe("pastor");
  });

  it.each(NAO_CENTRAL)("matriz persistida concedendo relatorios a %s é ignorada", (papel) => {
    const matrix: PermissionMatrix = { [papel]: ["dashboard", RELATORIOS] };
    expect(canSee(RELATORIOS, [papel], matrix)).toBe(false);
    expect(allowedScreens([papel], matrix)).not.toContain(RELATORIOS);
  });

  it.each(NAO_CENTRAL)("default também nega relatorios a %s", (papel) => {
    expect(canSee(RELATORIOS, [papel])).toBe(false);
  });

  it("somar papéis não-Central não desbloqueia", () => {
    const matrix: PermissionMatrix = {
      operador: [RELATORIOS],
      lider_celula: [RELATORIOS],
    };
    expect(canSee(RELATORIOS, ["operador", "lider_celula"], matrix)).toBe(false);
  });
});

describe("CENTRAL_ONLY — pastor e admin continuam permitidos", () => {
  it("pastor vê relatorios pelo default", () => {
    expect(canSee(RELATORIOS, ["pastor"])).toBe(true);
    expect(allowedScreens(["pastor"])).toContain(RELATORIOS);
  });

  it("pastor vê relatorios com matriz customizada", () => {
    const matrix: PermissionMatrix = { pastor: ["dashboard", RELATORIOS] };
    expect(canSee(RELATORIOS, ["pastor"], matrix)).toBe(true);
  });

  it("pastor acumulado com papel não-Central mantém a tela", () => {
    const matrix: PermissionMatrix = { pastor: [RELATORIOS], operador: ["inbox"] };
    expect(canSee(RELATORIOS, ["pastor", "operador"], matrix)).toBe(true);
  });

  it("admin mantém acesso implícito", () => {
    expect(canSee(RELATORIOS, ["admin"], { operador: [] })).toBe(true);
  });

  it("a regra só REMOVE: pastor sem a tela na matriz não entra", () => {
    expect(canSee(RELATORIOS, ["pastor"], { pastor: ["inbox"] })).toBe(false);
  });
});

describe("CENTRAL_ONLY — sem regressão nas demais telas", () => {
  it("matriz customizada preserva as outras telas do operador", () => {
    const matrix: PermissionMatrix = {
      operador: ["inbox", "ganhar", "celulas", RELATORIOS],
    };
    for (const tela of ["inbox", "ganhar", "celulas", "dashboard"]) {
      expect(canSee(tela, ["operador"], matrix)).toBe(true);
    }
    expect(canSee(RELATORIOS, ["operador"], matrix)).toBe(false);
  });

  it("allowedScreens remove só a Central-only", () => {
    const matrix: PermissionMatrix = {
      lider_celula: ["inbox", "minha-celula", RELATORIOS],
    };
    expect(allowedScreens(["lider_celula"], matrix).sort()).toEqual(
      ["dashboard", "inbox", "minha-celula"].sort(),
    );
  });

  it("dashboard continua garantido a todos", () => {
    expect(canSee("dashboard", ["membro"], { membro: [] })).toBe(true);
  });
});

describe("CENTRAL_ONLY — filtro POR PAPEL, não por ator", () => {
  // Com o filtro no ATOR ("o usuário tem pastor?"), a concessão de um papel
  // não-Central passava por carona: pastor + operador herdava `relatorios` do
  // operador mesmo com a concessão do pastor removida de propósito. Espelha
  // backend/tests/test_permissions_central_only.py.
  const FINDING: PermissionMatrix = { pastor: ["inbox"], operador: [RELATORIOS] };
  const POSITIVA: PermissionMatrix = { pastor: [RELATORIOS], operador: ["inbox"] };

  it("concessão de papel não-Central não pega carona no pastor", () => {
    expect(canSee(RELATORIOS, ["pastor", "operador"], FINDING)).toBe(false);
    expect(allowedScreens(["pastor", "operador"], FINDING)).not.toContain(RELATORIOS);
  });

  it("a ordem dos papéis não muda o veredito", () => {
    expect(canSee(RELATORIOS, ["operador", "pastor"], FINDING)).toBe(false);
    expect(canSee(RELATORIOS, ["operador", "pastor"], POSITIVA)).toBe(true);
  });

  it("caso positivo: a tela vinda do PRÓPRIO pastor é aceita", () => {
    expect(canSee(RELATORIOS, ["pastor", "operador"], POSITIVA)).toBe(true);
    expect(allowedScreens(["pastor", "operador"], POSITIVA)).toContain(RELATORIOS);
  });

  it("as demais telas dos dois papéis continuam sendo unidas", () => {
    const matrix: PermissionMatrix = {
      pastor: ["inbox", "celulas"],
      operador: ["ganhar", RELATORIOS],
    };
    const telas = allowedScreens(["pastor", "operador"], matrix);
    for (const tela of ["inbox", "celulas", "ganhar", "dashboard"]) {
      expect(telas).toContain(tela);
    }
    expect(telas).not.toContain(RELATORIOS);
  });

  it("admin acumulado mantém acesso implícito", () => {
    expect(canSee(RELATORIOS, ["admin", "operador"], FINDING)).toBe(true);
  });
});
