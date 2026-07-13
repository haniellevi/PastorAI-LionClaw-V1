/**
 * Gate 6.1 (P2 — coerência da navegação contextual do bottom-nav):
 * texto e destino do atalho "Jornada" coincidem SEMPRE, e o atalho não some
 * para papéis sem #ganhar mas com outra etapa acessível (lider_mult → #g12).
 */
import { describe, expect, it } from "vitest";

import { deriveTabs, journeyNavItem } from "@/components/shell/journey";
import { journeyStageOf } from "@/lib/navigation";
import { DEFAULT_PERMISSIONS } from "@/lib/permissions";

const M = DEFAULT_PERMISSIONS;

describe("journeyNavItem (atalho contextual do bottom-nav)", () => {
  it("fora da Jornada: 'Jornada' aponta para a primeira etapa acessível", () => {
    const item = journeyNavItem("dashboard", ["pastor"], M);
    expect(item).toEqual({ target: "ganhar", label: "Jornada", icon: "ganhar", active: false });
  });

  it("dentro de uma etapa: label da etapa e destino NA etapa (nunca #ganhar)", () => {
    const item = journeyNavItem("consol-individual", ["pastor"], M);
    expect(item).not.toBeNull();
    expect(item!.active).toBe(true);
    expect(item!.label).toBe("Consolidar");
    expect(item!.target).toBe("consolidar");
    // Coerência texto↔destino: o destino pertence à MESMA etapa exibida.
    expect(journeyStageOf(item!.target)).toBe(journeyStageOf("consol-individual"));
  });

  it("lider_mult (sem #ganhar): o atalho não some — destino = #g12", () => {
    const fora = journeyNavItem("dashboard", ["lider_mult"], M);
    expect(fora).toEqual({ target: "g12", label: "Jornada", icon: "ganhar", active: false });

    const dentro = journeyNavItem("g12", ["lider_mult"], M);
    expect(dentro).not.toBeNull();
    expect(dentro!.label).toBe("Discipular");
    expect(dentro!.target).toBe("g12");
    expect(dentro!.active).toBe(true);
  });

  it("papel sem nenhuma etapa acessível: atalho some (null)", () => {
    expect(journeyNavItem("dashboard", ["membro"], M)).toBeNull();
  });

  it("nunca devolve destino que o papel não pode ver nem tela locked", () => {
    for (const roles of [["pastor"], ["lider_mult"], ["lider_celula"], ["operador"]] as const) {
      for (const base of ["dashboard", "g12", "consolidar", "minha-celula"]) {
        const item = journeyNavItem(base, [...roles], M);
        if (!item) continue;
        expect(M[roles[0]]).toContain(item.target);
      }
    }
  });
});

describe("deriveTabs (ModuleTabs — derivação de NAV_SECTIONS)", () => {
  it("consolidar: head primeiro + subs, sem target repetido", () => {
    const tabs = deriveTabs("consolidar")!;
    expect(tabs.map((t) => t.target)).toEqual([
      "consolidar",
      "consol-individual",
      "universidade-vida",
    ]);
  });

  it("discipular: dedup do head repetido nas subs (g12 aparece uma vez)", () => {
    const tabs = deriveTabs("discipular")!;
    const targets = tabs.map((t) => t.target);
    expect(new Set(targets).size).toBe(targets.length);
    expect(targets[0]).toBe("g12");
  });
});
