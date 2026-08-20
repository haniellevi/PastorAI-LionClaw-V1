import { describe, expect, it } from "vitest";

import { editableRoles, EDITABLE_ROLE_ORDER } from "./roles";

describe("papéis derivados", () => {
  it("não oferece nem envia lider_celula, preservando os demais papéis acumulados", () => {
    expect(EDITABLE_ROLE_ORDER).not.toContain("lider_celula");
    expect(editableRoles(["membro", "lider_celula", "pastor", "operador"])).toEqual([
      "membro",
      "pastor",
      "operador",
    ]);
    expect(editableRoles(["lider_celula"])).toEqual([]);
  });
});
