// @vitest-environment jsdom
/**
 * FECH-06 — REATIVAR-1: desarquivar Pessoa na tela #contatos.
 *  - a aba "Arquivadas" exibe SÓ as pessoas arquivadas (que ficam fora das
 *    listas normais enquanto arquivadas);
 *  - o botão "Reativar" abre confirmação no ds/Dialog (nunca window.confirm)
 *    e, ao confirmar, dispara POST /contacts/{id}/unarchive; a pessoa sai de
 *    "Arquivadas" e volta às listas normais;
 *  - cancelar nunca chama a API;
 *  - papéis sem admin/pastor não veem o botão (espelho do RBAC do backend);
 *  - erro da API aparece no diálogo sem fechá-lo nem alterar a lista.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Contact } from "@/lib/contacts-api";

const authState = vi.hoisted(() => ({
  roles: ["admin"] as string[],
  // Referências ESTÁVEIS entre renders (ver ContatosScreen.test.ts): um objeto
  // novo a cada useAuth() recriaria handleSessionError -> load -> loop de fetch.
  expireSession: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    token: "tok-1",
    user: { roles: authState.roles },
    expireSession: authState.expireSession,
  }),
}));

const apiMock = vi.hoisted(() => ({
  fetchContacts: vi.fn(),
  unarchiveContact: vi.fn(),
}));

vi.mock("@/lib/contacts-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/contacts-api")>();
  return {
    ...actual,
    fetchContacts: apiMock.fetchContacts,
    unarchiveContact: apiMock.unarchiveContact,
    fetchOffboardingPreflight: vi.fn(),
    archiveContact: vi.fn(),
    createContact: vi.fn(),
    linkContactCell: vi.fn(),
    updateContact: vi.fn(),
  };
});

vi.mock("@/lib/dashboard-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dashboard-api")>();
  return {
    ...actual,
    fetchCells: vi.fn().mockResolvedValue({ items: [], page: 1, pageSize: 100, total: 0 }),
  };
});

const { ApiError } = await import("@/lib/dashboard-api");
const { ContatosScreen } = await import("./ContatosScreen");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const arquivada: Contact = {
  id: "p1",
  nome: "Aristides Arquivado",
  telefone: "5589999990008",
  email: null,
  genero: null,
  tipo: "membro",
  etapa: "discipular",
  subetapa: null,
  acompanhamento: null,
  semInteresse: false,
  semInteresseMotivo: null,
  presencasCelula: 2,
  aceitouJesus: true,
  celulaId: null,
  liderId: null,
  aptoLider: false,
  liderDeCelula: false,
  arquivada: true,
};

const ativa: Contact = {
  ...arquivada,
  id: "p2",
  nome: "Beatriz Ativa",
  telefone: "5511999998888",
  arquivada: false,
};

let container: HTMLDivElement;
let root: Root;

async function flush(times = 3) {
  for (let i = 0; i < times; i++) {
    // eslint-disable-next-line no-await-in-loop
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

function findButton(label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((b) => b.textContent!.includes(label));
}

function tableText(): string {
  return container.querySelector(".data-table")?.textContent ?? "";
}

/** Aba de filtro (role="tab") pelo rótulo — não confundir com botões de ação. */
function clickTab(label: string) {
  const tab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((b) =>
    b.textContent!.includes(label),
  );
  if (!tab) throw new Error(`aba não encontrada: ${label}`);
  act(() => {
    tab.click();
  });
}

/** Botão DENTRO do diálogo (o "Reativar" da linha fica fora dele). */
function dialogButton(label: string): HTMLButtonElement | undefined {
  const dialog = container.querySelector('[role="dialog"]');
  if (!dialog) return undefined;
  return [...dialog.querySelectorAll("button")].find((b) => b.textContent === label);
}

async function renderScreen(items: Contact[] = [arquivada, ativa]) {
  apiMock.fetchContacts.mockResolvedValue({
    items,
    page: 1,
    pageSize: 200,
    total: items.length,
  });
  act(() => {
    root.render(h(ContatosScreen, {}));
  });
  await flush();
}

beforeEach(() => {
  authState.roles = ["admin"];
  authState.expireSession.mockClear();
  apiMock.fetchContacts.mockReset();
  apiMock.unarchiveContact.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ContatosScreen — reativação de Pessoa arquivada (FECH-06/REATIVAR-1)", () => {
  it('aba "Arquivadas" exibe só as arquivadas; nas listas normais elas ficam de fora', async () => {
    await renderScreen();

    // Aba "Todos": a arquivada NÃO aparece (só volta ao ser reativada).
    expect(tableText()).toContain("Beatriz Ativa");
    expect(tableText()).not.toContain("Aristides Arquivado");

    clickTab("Arquivadas");
    expect(tableText()).toContain("Aristides Arquivado");
    expect(tableText()).not.toContain("Beatriz Ativa");
    expect(findButton("Reativar")).toBeDefined();
  });

  it("Reativar: confirmação no ds/Dialog dispara o endpoint; pessoa sai de Arquivadas e volta às listas", async () => {
    await renderScreen();
    clickTab("Arquivadas");

    act(() => {
      findButton("Reativar")!.click();
    });
    // Confirmação obrigatória via ds/Dialog (nunca window.confirm) e nada de
    // API antes do confirmar.
    const dialog = container.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.textContent).toContain("Reativar pessoa");
    expect(dialog!.textContent).toContain("Aristides Arquivado");
    expect(apiMock.unarchiveContact).not.toHaveBeenCalled();

    apiMock.unarchiveContact.mockResolvedValue({
      pessoa_id: "p1",
      arquivada: false,
      reativada_por: "admin-1",
    });
    act(() => {
      dialogButton("Reativar")!.click();
    });
    await flush();

    expect(apiMock.unarchiveContact).toHaveBeenCalledWith("tok-1", "p1");
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector(".toast")?.textContent).toContain("foi reativada");
    // Saiu de "Arquivadas"...
    expect(tableText()).not.toContain("Aristides Arquivado");
    // ...e voltou às listas normais.
    clickTab("Todos");
    expect(tableText()).toContain("Aristides Arquivado");
    expect(tableText()).toContain("Beatriz Ativa");
  });

  it("Cancelar fecha o diálogo sem chamar a API; pessoa continua arquivada", async () => {
    await renderScreen();
    clickTab("Arquivadas");
    act(() => {
      findButton("Reativar")!.click();
    });
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();

    act(() => {
      dialogButton("Cancelar")!.click();
    });
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(apiMock.unarchiveContact).not.toHaveBeenCalled();
    expect(tableText()).toContain("Aristides Arquivado");
  });

  it("pessoa já arquivada no fetch (pós-reload): detalhe mostra 'Arquivada' e esconde 'Arquivar pessoa'", async () => {
    // Estado PERSISTENTE: fetchContacts já devolve arquivada=true (backend) —
    // nenhum arquivamento aconteceu nesta sessão (archivedInfo vazio).
    await renderScreen();
    clickTab("Arquivadas");

    const row = [...container.querySelectorAll("tr")].find((r) =>
      r.textContent!.includes("Aristides Arquivado"),
    );
    expect(row).toBeDefined();
    act(() => {
      (row as HTMLElement).click();
    });
    await flush();

    const side = container.querySelector(".dash-side")!;
    expect(side.textContent).toContain("Arquivada");
    expect(
      [...side.querySelectorAll("button")].find((b) =>
        b.textContent!.includes("Arquivar pessoa"),
      ),
    ).toBeUndefined();
  });

  it("papel sem admin/pastor não vê o botão Reativar (espelho do RBAC do backend)", async () => {
    authState.roles = ["lider_celula"];
    await renderScreen();
    clickTab("Arquivadas");
    expect(tableText()).toContain("Aristides Arquivado");
    expect(findButton("Reativar")).toBeUndefined();
  });

  it("pastor (sem admin) vê e usa o Reativar — o backend aceita admin/pastor", async () => {
    authState.roles = ["pastor"];
    await renderScreen();
    clickTab("Arquivadas");
    act(() => {
      findButton("Reativar")!.click();
    });
    apiMock.unarchiveContact.mockResolvedValue({
      pessoa_id: "p1",
      arquivada: false,
      reativada_por: "pastor-1",
    });
    act(() => {
      dialogButton("Reativar")!.click();
    });
    await flush();
    expect(apiMock.unarchiveContact).toHaveBeenCalledWith("tok-1", "p1");
  });

  it("erro da API aparece no diálogo sem fechá-lo; pessoa segue arquivada", async () => {
    await renderScreen();
    clickTab("Arquivadas");
    act(() => {
      findButton("Reativar")!.click();
    });

    apiMock.unarchiveContact.mockRejectedValue(
      new ApiError(409, "Pessoa não está arquivada"),
    );
    act(() => {
      dialogButton("Reativar")!.click();
    });
    await flush();

    const dialog = container.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.textContent).toContain("Pessoa não está arquivada");
    expect(container.querySelector(".toast")).toBeNull();
    expect(tableText()).toContain("Aristides Arquivado");
  });
});
