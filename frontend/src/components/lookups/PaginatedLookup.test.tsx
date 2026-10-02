// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PaginatedLookup } from "./PaginatedLookup";
import type { LookupLoader } from "./useLookupPage";
import type { Page } from "@/lib/dashboard-api";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
type Item = { id: string; nome: string; blocked?: boolean };
const batch = (item: Item, page = 1): Page<Item> => ({ items: [item], page, pageSize: 25, total: 301 });
let container: HTMLDivElement;
let root: Root;
function Harness({ loadPage }: { loadPage: LookupLoader<Item> }) {
  const [selected, setSelected] = useState<Item | null>(null);
  return <PaginatedLookup label="Pessoa" inputId="person-search" loadPage={loadPage} selected={selected} onSelect={setSelected} getLabel={(person) => person.nome} isDisabled={(person) => !!person.blocked} />;
}
beforeEach(() => {
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.useRealTimers(); });
const button = (label: string) => [...container.querySelectorAll("button")].find((item) => item.textContent === label)!;

describe("PaginatedLookup", () => {
  it("alcança página seguinte e mantém nome selecionado ao paginar", async () => {
    const load = vi.fn<LookupLoader<Item>>().mockResolvedValueOnce(batch({ id: "p-201", nome: "Pessoa além200" }))
      .mockResolvedValueOnce(batch({ id: "p-250", nome: "Outra pessoa" }, 2));
    await act(async () => root.render(<Harness loadPage={load} />));
    act(() => button("Pessoa além200").click());
    await act(async () => button("Próxima página").click());
    expect(load.mock.calls[1]!.slice(0, 2)).toEqual(["", 2]);
    expect(container.textContent).toContain("Selecionada: Pessoa além200");
    expect(container.textContent).toContain("301 resultados");
    expect(container.textContent).toContain("Página 2 de 13");
  });
  it("ignora resposta anterior e espera250ms antes de buscar outro nome", async () => {
    vi.useFakeTimers();
    let resolveOld!: (page: Page<Item>) => void;
    const load = vi.fn<LookupLoader<Item>>().mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(batch({ id: "new", nome: "Resultado novo" }));
    await act(async () => root.render(<Harness loadPage={load} />));
    const input = container.querySelector("input")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, "Ana");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => { resolveOld(batch({ id: "old", nome: "Resultado antigo" })); await vi.advanceTimersByTimeAsync(250); });
    expect(load.mock.calls[1]![0]).toBe("Ana");
    expect(load.mock.calls[0]![2].aborted).toBe(true);
    expect(container.textContent).toContain("Resultado novo");
    expect(container.textContent).not.toContain("Resultado antigo");
  });
  it("mantém bloqueio de opção e permite retry de erro visível", async () => {
    const load = vi.fn<LookupLoader<Item>>().mockRejectedValueOnce(new Error("Indisponível"))
      .mockResolvedValueOnce(batch({ id: "blocked", nome: "Sem acesso", blocked: true }));
    await act(async () => root.render(<Harness loadPage={load} />));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Indisponível");
    await act(async () => button("Tentar novamente").click());
    expect(button("Sem acesso").disabled).toBe(true);
    expect(container.textContent).not.toContain("Selecionada:");
  });
});
