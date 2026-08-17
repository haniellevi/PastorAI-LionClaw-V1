import { describe, expect, it } from "vitest";

import { resolveDashboardResponsibilities } from "./dashboard-responsibilities";

describe("resolveDashboardResponsibilities", () => {
  it.each([
    ["admin", "igreja", true, true, "Ações da igreja"],
    ["pastor", "igreja", true, true, "Fila pastoral da igreja"],
    ["lider_g12", "igreja", true, false, "Ações da igreja sob sua responsabilidade"],
    ["lider_consol", "igreja", true, false, "Ações de consolidação"],
    ["lider_celula", "celula", false, false, "Ações sob seus cuidados"],
    ["lider_mult", null, false, false, "Ações sob sua responsabilidade"],
    ["operador", null, false, false, "Ações sob sua responsabilidade"],
    ["membro", null, false, false, "Ações sob sua responsabilidade"],
  ] as const)(
    "compõe capacidades de %s sem ampliar o contrato",
    (role, queueScope, canAssign, canLinkCell, queueTitle) => {
      const result = resolveDashboardResponsibilities([role]);

      expect(result.queueScope).toBe(queueScope);
      expect(result.hasWorkQueue).toBe(queueScope !== null);
      expect(result.canAssignQueue).toBe(canAssign);
      expect(result.canLinkCell).toBe(canLinkCell);
      expect(result.showOverview).toBe(queueScope !== null);
      expect(result.queueTitle).toBe(queueTitle);
      if (role !== "pastor") expect(result.queueTitle.toLowerCase()).not.toContain("pastor");
    },
  );

  it("faz o papel amplo vencer sem perder os atalhos acumulados", () => {
    const result = resolveDashboardResponsibilities([
      "membro",
      "lider_celula",
      "lider_consol",
    ]);

    expect(result.queueScope).toBe("igreja");
    expect(result.canAssignQueue).toBe(true);
    expect(result.canLinkCell).toBe(false);
    expect(result.shortcutCandidates).toEqual([
      "minha-celula",
      "inbox",
      "consolidar",
      "ganhar",
      "calendario",
    ]);
  });

  it("não transforma multiplicação ou operação em fila global", () => {
    const result = resolveDashboardResponsibilities(["lider_mult", "operador"]);

    expect(result.hasWorkQueue).toBe(false);
    expect(result.homeTitle).toBe("Seus espaços de atuação");
    expect(result.prioritizeShortcuts).toBe(true);
    expect(result.shortcutCandidates).toEqual([
      "inbox",
      "ganhar",
      "calendario",
      "minha-celula",
      "g12",
      "enviar",
    ]);
  });

  it("prioriza o caminho de multiplicação quando não há operação acumulada", () => {
    const result = resolveDashboardResponsibilities(["membro", "lider_mult"]);

    expect(result.prioritizeShortcuts).toBe(true);
    expect(result.shortcutCandidates).toEqual([
      "enviar",
      "g12",
      "minha-celula",
      "calendario",
    ]);
  });

  it("mantém a palavra pastoral exclusiva de quem possui papel pastor", () => {
    const admin = resolveDashboardResponsibilities(["admin"]);
    const leader = resolveDashboardResponsibilities(["lider_celula"]);
    const pastor = resolveDashboardResponsibilities(["admin", "pastor"]);

    expect(admin.emptyQueueText.toLowerCase()).not.toContain("pastoral");
    expect(leader.emptyQueueText.toLowerCase()).not.toContain("pastoral");
    expect(pastor.queueTitle).toBe("Fila pastoral da igreja");
  });
});
