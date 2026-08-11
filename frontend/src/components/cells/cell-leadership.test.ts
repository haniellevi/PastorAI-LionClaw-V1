import { describe, expect, it } from "vitest";

import type { Contact } from "@/lib/contacts-api";
import type { TeamMember } from "@/lib/dashboard-api";

import { buildCellLeaderOptions, hasActivePanelAccess } from "./cell-leadership";

function contact(id: string, overrides: Partial<Contact> = {}): Contact {
  return {
    id,
    nome: `Pessoa ${id}`,
    telefone: "55999999999",
    email: null,
    genero: null,
    tipo: "membro",
    etapa: null,
    subetapa: null,
    acompanhamento: null,
    semInteresse: false,
    semInteresseMotivo: null,
    presencasCelula: 0,
    aceitouJesus: false,
    celulaId: null,
    liderId: null,
    aptoLider: true,
    liderDeCelula: false,
    ...overrides,
  };
}

function member(
  pessoaId: string,
  status: string | null,
  suffix = "",
): TeamMember {
  return {
    usuarioId: `u-${pessoaId}${suffix}`,
    pessoaId,
    nome: `Pessoa ${pessoaId}`,
    email: `${pessoaId}${suffix}@example.com`,
    status,
    papeis: ["membro"],
  };
}

describe("buildCellLeaderOptions", () => {
  it("aceita exatamente um acesso ativo, inclusive o legado status NULL", () => {
    expect(hasActivePanelAccess("ativo")).toBe(true);
    expect(hasActivePanelAccess(null)).toBe(true);
    expect(hasActivePanelAccess(undefined)).toBe(false);

    const options = buildCellLeaderOptions(
      [contact("ativo"), contact("legado")],
      [member("ativo", "ativo"), member("legado", null)],
      null,
    );

    expect(options.map(({ id, selectable }) => ({ id, selectable }))).toEqual([
      { id: "ativo", selectable: true },
      { id: "legado", selectable: true },
    ]);
  });

  it("mantém convidado, revogado, sem acesso e acesso duplicado visíveis com motivo", () => {
    const options = buildCellLeaderOptions(
      [
        contact("convidado"),
        contact("revogado"),
        contact("sem-acesso"),
        contact("duplicado"),
      ],
      [
        member("convidado", "convidado"),
        member("revogado", "revogado"),
        member("duplicado", "ativo", "-1"),
        member("duplicado", null, "-2"),
      ],
      null,
    );

    const byId = Object.fromEntries(options.map((option) => [option.id, option]));
    expect(byId.convidado).toMatchObject({ selectable: false, reason: "Acesso ainda não ativado" });
    expect(byId.revogado).toMatchObject({ selectable: false, reason: "Acesso revogado" });
    expect(byId["sem-acesso"]).toMatchObject({ selectable: false, reason: "Sem acesso ao painel" });
    expect(byId.duplicado).toMatchObject({ selectable: false, reason: "Mais de um acesso ativo" });
  });

  it("mantém o líder atual visível, mas trata irregularidade como bloqueante", () => {
    const current = contact("atual", {
      aptoLider: false,
      liderDeCelula: true,
    });
    const [option] = buildCellLeaderOptions(
      [current],
      [member("atual", "revogado")],
      "atual",
    );

    expect(option).toMatchObject({
      id: "atual",
      current: true,
      selectable: false,
      blocksSave: true,
    });
    expect(option?.reason).toContain("Pendência bloqueante no acesso do líder atual");
    expect(option?.reason).toContain("acesso revogado");
    expect(option?.reason).toContain("Regularize o acesso ou escolha outro líder");
    expect(option?.reason).toContain("Aviso cadastral não bloqueante");
    expect(option?.reason).not.toContain("preservado");
  });

  it("não bloqueia o líder atual apenas por aptidão ou CSIM históricos", () => {
    const current = contact("atual", {
      aptoLider: false,
      liderDeCelula: true,
      semInteresse: true,
    });
    const [option] = buildCellLeaderOptions(
      [current],
      [member("atual", "ativo")],
      "atual",
    );

    expect(option).toMatchObject({
      id: "atual",
      current: true,
      selectable: true,
      blocksSave: false,
    });
    expect(option?.reason).toContain("Aviso cadastral não bloqueante");
    expect(option?.reason).toContain("não atende aos critérios atuais");
    expect(option?.reason).toContain("sem interesse ministerial");
    expect(option?.reason).not.toContain("Pendência bloqueante");
  });
});
