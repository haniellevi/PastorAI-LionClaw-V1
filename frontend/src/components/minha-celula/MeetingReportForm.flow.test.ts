// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReportOut } from "@/lib/cell-meetings-api";

const apiMock = vi.hoisted(() => ({
  getReport: vi.fn(),
  getVisitorExpectations: vi.fn(),
}));

vi.mock("@/lib/cell-meetings-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/cell-meetings-api")>();
  return {
    ...actual,
    getReport: apiMock.getReport,
    getVisitorExpectations: apiMock.getVisitorExpectations,
  };
});

const { MeetingReportForm } = await import("./MeetingReportForm");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const baseReport: ReportOut = {
  meeting_id: "meeting-1",
  data: "2026-08-26",
  tema: "Ouvir a voz de Deus",
  relatorio_status: "rascunho",
  oferta_valor: null,
  observacoes: null,
  presencas: [
    { pessoa_id: "person-1", estado: "compareceu", origem: "lider" },
    { pessoa_id: "person-2", estado: "faltou", origem: "lider" },
  ],
  visitantes: [],
  records: [],
};

let container: HTMLDivElement;
let root: Root;

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function renderReport(report: ReportOut = baseReport) {
  apiMock.getReport.mockResolvedValue(report);
  apiMock.getVisitorExpectations.mockResolvedValue({ expectations: [] });
  act(() => {
    root.render(
      h(MeetingReportForm, {
        token: "token-1",
        reuniaoId: "meeting-1",
        members: [
          { pessoa_id: "person-1", nome: "Ana Carolina", ativo: true },
          { pessoa_id: "person-2", nome: "5511997906490", ativo: true },
        ],
        onToast: vi.fn(),
      }),
    );
  });
  await flush();
}

beforeEach(() => {
  apiMock.getReport.mockReset();
  apiMock.getVisitorExpectations.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("MeetingReportForm, fluxo guiado", () => {
  it("abre apenas uma etapa, informa o progresso e preserva pessoas sem nome", async () => {
    await renderReport();

    const triggers = [...container.querySelectorAll<HTMLButtonElement>("[aria-expanded]")];
    expect(triggers).toHaveLength(4);
    expect(triggers.map((button) => button.getAttribute("aria-expanded"))).toEqual([
      "true",
      "false",
      "false",
      "false",
    ]);
    expect(container.textContent).toContain("Relatório em andamento");
    expect(container.textContent).toContain("1 de 2 presentes");
    expect(container.textContent).toContain("Contato sem nome");
    expect(container.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow")).toBe("1");

    act(() => triggers[1]!.click());

    expect(triggers[0]!.getAttribute("aria-expanded")).toBe("false");
    expect(triggers[1]!.getAttribute("aria-expanded")).toBe("true");
    expect(container.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow")).toBe("2");
  });

  it("mostra o estado enviado sem ação de envio ou alerta de pendência", async () => {
    await renderReport({ ...baseReport, relatorio_status: "enviado" });

    expect(container.textContent).toContain("Relatório enviado e bloqueado para edição.");
    expect(container.textContent).not.toContain("Relatório em andamento");
    expect(
      [...container.querySelectorAll("button")].some((button) =>
        button.textContent?.includes("Enviar relatório"),
      ),
    ).toBe(false);
  });

  it.each([
    { presentes: 10, visitantes: 2, decisoes: 1, oferta: 30 },
    { presentes: 0, visitantes: 0, decisoes: 0, oferta: 0 },
  ])("mostra os totais confirmados sem atribuir dados a pessoas: %j", async (totals) => {
    const { oferta, ...counts } = totals;
    const report = {
      ...baseReport,
      schema: "cell-report/v2" as const,
      relatorio_status: "enviado",
      oferta_valor: oferta,
      presencas: [],
      visitantes: [],
      records: [],
      totals: counts,
    };
    await renderReport(report);

    const text = container.textContent?.replace(/\s+/g, " ");
    expect(text).toContain(`${totals.presentes} presentes`);
    expect(text).toContain(`${totals.visitantes} visitantes`);
    expect(text).toContain(`${totals.decisoes} ${totals.decisoes === 1 ? "decisão" : "decisões"}`);
    expect(text).toContain(`R$ ${totals.oferta.toFixed(2).replace(".", ",")}`);
    expect(text).toContain("Relatório enviado e bloqueado para edição.");
    expect(text).toContain("Os totais foram informados sem identificação individual.");
    expect(text).not.toContain("de 2 presentes");
    expect(text).not.toContain("Sem visitantes registrados");
    expect(text).not.toContain("Sem registros");
    expect(text).not.toContain("Ana Carolina");
    expect(text).not.toContain("Contato sem nome");
    expect(container.querySelector('input, textarea, select, [role="switch"]')).toBeNull();
    expect(container.querySelector("[aria-expanded]")).toBeNull();
    expect([...container.querySelectorAll("button")].some((button) =>
      button.textContent?.includes("Enviar relatório"),
    )).toBe(false);
  });
});
