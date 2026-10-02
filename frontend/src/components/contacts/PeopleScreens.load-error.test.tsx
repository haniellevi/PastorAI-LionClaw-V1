// @vitest-environment jsdom
import { act, createElement as h, type ComponentType } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Contact } from "@/lib/contacts-api";

const auth = vi.hoisted(() => ({ token: "tok-initial", expireSession: vi.fn() }));
const api = vi.hoisted(() => ({
  fetchContactsPage: vi.fn(), fetchContactDetail: vi.fn(), fetchContacts: vi.fn(),
  fetchPipeline: vi.fn(), fetchCells: vi.fn(), fetchCellsFull: vi.fn(), fetchWorkQueue: vi.fn(),
}));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: auth.token, user: { appUserId: "actor-example", roles: ["admin", "pastor"] }, expireSession: auth.expireSession }),
}));
vi.mock("@/lib/contacts-api", async (original) => ({
  ...await original<typeof import("@/lib/contacts-api")>(),
  fetchContactsPage: api.fetchContactsPage, fetchContactDetail: api.fetchContactDetail,
  fetchContacts: api.fetchContacts, fetchPipeline: api.fetchPipeline,
  fetchGanharPage: async (token: string) => {const page = await api.fetchPipeline(token,"ganhar"); return {...page, summary: {total:page.items.length,novosContatos:page.items.length,visitantesSemCelula:0,visitantesComDecisao:0}};},
}));
vi.mock("@/lib/dashboard-api", async (original) => ({
  ...await original<typeof import("@/lib/dashboard-api")>(),
  fetchCells: api.fetchCells, fetchWorkQueue: api.fetchWorkQueue,
}));
vi.mock("@/lib/cells-api", async (original) => ({
  ...await original<typeof import("@/lib/cells-api")>(), fetchCellsFull: api.fetchCellsFull,
}));

const { ApiError } = await import("@/lib/dashboard-api");
const { ContatosScreen } = await import("./ContatosScreen");
const { GanharScreen } = await import("./GanharScreen");
const { ConsolidarScreen } = await import("../consolidacao/ConsolidarScreen");
const { ConsolIndividualScreen } = await import("../consolidacao/ConsolIndividualScreen");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const person: Contact = {
  id: "person-load-example", nome: "Pessoa fictícia da leitura", telefone: "5500000000000",
  email: null, genero: null, tipo: "contato", etapa: "ganhar", subetapa: "novo_contato",
  acompanhamento: null, semInteresse: false, semInteresseMotivo: null,
  presencasCelula: 0, aceitouJesus: false, celulaId: null, liderId: null,
  aptoLider: false, liderDeCelula: false,
};
function page(items: Contact[] = []) { return { items, page: 1, pageSize: 50, total: items.length }; }
const screens: Array<{ name: string; Component: ComponentType; read: typeof api.fetchPipeline; empty: string }> = [
  { name: "Pessoas", Component: ContatosScreen, read: api.fetchContactsPage, empty: "Nenhum contato ainda." },
  { name: "Ganhar", Component: GanharScreen, read: api.fetchPipeline, empty: "Nenhum novo contato por aqui." },
  { name: "Consolidar", Component: ConsolidarScreen, read: api.fetchPipeline, empty: "Nenhum acompanhamento pendente nesta lista." },
  { name: "Consolidação individual", Component: ConsolIndividualScreen, read: api.fetchPipeline, empty: "Nenhuma consolidação em andamento." },
];
let container: HTMLDivElement;
let root: Root;
async function settle() {
  for (let n = 0; n < 3; n++) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
}
async function render(Component: ComponentType) {
  act(() => root.render(h(Component)));
  await settle();
}
function retry() {
  const button = [...container.querySelectorAll("button")].find((item) => item.textContent?.trim() === "Tentar novamente");
  expect(button).toBeDefined();
  expect(button!.disabled).toBe(false);
  act(() => button!.click());
}
beforeEach(() => {
  auth.token = "tok-initial";
  auth.expireSession.mockClear();
  Object.values(api).forEach((mock) => mock.mockReset());
  api.fetchContactsPage.mockResolvedValue(page());
  api.fetchContacts.mockResolvedValue(page());
  api.fetchPipeline.mockResolvedValue(page());
  api.fetchCells.mockResolvedValue(page());
  api.fetchCellsFull.mockResolvedValue(page());
  api.fetchWorkQueue.mockResolvedValue(page());
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe.each(screens)("$name, erro de leitura", ({ Component, read, empty }) => {
  it("falha inicial oferece retry e só declara vazio depois de leitura confirmada", async () => {
    read.mockRejectedValueOnce(new ApiError(500, "Leitura fictícia falhou."));
    await render(Component);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Leitura fictícia falhou.");
    expect(container.textContent).not.toMatch(/Nenhum/);
    expect(container.querySelector(".stat .val, .people-filter-group .num, .fcount, nav[aria-label='Paginação de contatos']")).toBeNull();
    expect(container.textContent).not.toContain("0 pessoas na lista");
    retry();
    await settle();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.textContent).toContain(empty);
    expect(auth.expireSession).not.toHaveBeenCalled();
  });

  it("revalidação que falha mantém a última lista confirmada e permite tentar novamente", async () => {
    read.mockResolvedValueOnce(page([person]));
    await render(Component);
    expect(container.textContent).toContain(person.nome);
    read.mockRejectedValueOnce(new ApiError(500, "Atualização fictícia falhou."));
    auth.token = "tok-refreshed";
    await render(Component);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Atualização fictícia falhou.");
    expect(container.textContent).toContain(person.nome);
    read.mockResolvedValueOnce(page([person]));
    retry();
    await settle();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.textContent).toContain(person.nome);
  });
});

it("Pessoas não mistura a página anterior quando a leitura do novo filtro falha", async () => {
  api.fetchContactsPage.mockResolvedValueOnce(page([person]));
  await render(ContatosScreen);
  api.fetchContactsPage.mockRejectedValueOnce(new ApiError(500, "Filtro fictício indisponível."));
  const filter = container.querySelector<HTMLSelectElement>("#people-filter")!;
  act(() => {
    filter.value = "visitante";
    filter.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
  expect(filter.value).toBe("visitante");
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("Filtro fictício indisponível.");
  expect(container.textContent).not.toContain(person.nome);
  expect(container.textContent).not.toMatch(/Nenhum/);
  expect(container.querySelector("nav[aria-label='Paginação de contatos']")).toBeNull();
  retry();
  await settle();
  expect(filter.value).toBe("visitante");
  expect(api.fetchContactsPage).toHaveBeenLastCalledWith("tok-initial", { page: 1, pageSize: 50, view: "visitante", signal: expect.any(AbortSignal) });
  expect(container.textContent).toContain("Nenhum contato neste filtro.");
});
