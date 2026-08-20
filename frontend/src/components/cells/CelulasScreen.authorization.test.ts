import { describe, expect, it } from "vitest";

import { canAddMemberInLegacy } from "./CelulasScreen";

describe("ações de célula na tela legada", () => {
  it.each([
    ["admin", true],
    ["pastor", true],
    ["lider_g12", false],
    ["lider_celula", false],
    ["membro", false],
  ] as const)("%s pode adicionar Pessoa: %s", (role, expected) => {
    expect(canAddMemberInLegacy([role])).toBe(expected);
  });
});
