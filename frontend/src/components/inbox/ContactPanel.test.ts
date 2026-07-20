// @vitest-environment jsdom
/**
 * FECH-05/OPTIN-1 — botão "Reativar comunicações" no painel de dados do contato:
 *  - o botão aparece SOMENTE quando a pessoa está em opt-out (e some sem);
 *  - a confirmação é via ds/Dialog (role="dialog", nunca window.confirm);
 *  - confirmar dispara o endpoint de reativação e mostra feedback de sucesso;
 *  - papel sem admin/pastor não vê o botão (RBAC real fica no backend).
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ContactDetail, ReactivateCommunicationsResult } from "@/lib/contacts-api";

const authState = vi.hoisted(() => ({
  roles: ["admin"] as string[],
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
  fetchContactDetail: vi.fn(),
  reactivateCommunications: vi.fn(),
  updateContact: vi.fn(),
}));

vi.mock("@/lib/contacts-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/contacts-api")>();
  return {
    ...actual,
    fetchContactDetail: apiMock.fetchContactDetail,
    reactivateCommunications: apiMock.reactivateCommunications,
    updateContact: apiMock.updateContact,
  };
});

const { ContactPanel } = await import("./ContactPanel");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function detail(over: Partial<ContactDetail> = {}): ContactDetail {
  return {
    id: "p1",
    nome: "Otília Optout",
    telefone: "5511987654321",
    email: null,
    genero: null,
    faixaEtaria: null,
    endereco: null,
    tipo: "membro",
    etapa: null,
    subetapa: null,
    acompanhamento: null,
    semInteresse: false,
    semInteresseMotivo: null,
    presencasCelula: 0,
    aceitouJesus: false,
    celulaId: null,
    celulaNome: null,
    liderId: null,
    liderNome: null,
    aptoLider: false,
    liderDeCelula: false,
    consentimento: true,
    optout: true,
    origem: null,
    primeiroContato: null,
    criadoEm: null,
    ...over,
  };
}

function reactivateResult(
  over: Partial<ReactivateCommunicationsResult> = {},
): ReactivateCommunicationsResult {
  return {
    pessoa_id: "p1",
    optout: false,
    termo_versao: "reoptin:v1",
    reativada_por: "admin-1",
    ja_ativa: false,
    ...over,
  };
}

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
  return [...container.querySelectorAll("button")].find((b) =>
    b.textContent!.includes(label),
  );
}

async function renderPanel() {
  act(() => {
    root.render(
      h(ContactPanel, {
        pessoaId: "p1",
        telefone: "5511987654321",
        onClose: () => {},
      }),
    );
  });
  await flush();
}

beforeEach(() => {
  authState.roles = ["admin"];
  authState.expireSession.mockClear();
  apiMock.fetchContactDetail.mockReset();
  apiMock.reactivateCommunications.mockReset();
  apiMock.updateContact.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ContactPanel — reativar comunicações (FECH-05/OPTIN-1)", () => {
  it("mostra o botão apenas quando a pessoa está em opt-out", async () => {
    apiMock.fetchContactDetail.mockResolvedValue(detail({ optout: true }));
    await renderPanel();
    expect(findButton("Reativar comunicações")).toBeDefined();
    expect(container.textContent).toContain("Opt-out (pausadas)");
  });

  it("NÃO mostra o botão quando a pessoa não está em opt-out", async () => {
    apiMock.fetchContactDetail.mockResolvedValue(detail({ optout: false }));
    await renderPanel();
    expect(findButton("Reativar comunicações")).toBeUndefined();
  });

  it("NÃO mostra o botão para papel sem admin/pastor (mesmo em opt-out)", async () => {
    authState.roles = ["operador"];
    apiMock.fetchContactDetail.mockResolvedValue(detail({ optout: true }));
    await renderPanel();
    expect(findButton("Reativar comunicações")).toBeUndefined();
  });

  it("confirmar no ds/Dialog chama o endpoint e mostra feedback de sucesso", async () => {
    apiMock.fetchContactDetail.mockResolvedValue(detail({ optout: true }));
    await renderPanel();

    // Abre a confirmação (ds/Dialog — nunca window.confirm).
    act(() => {
      findButton("Reativar comunicações")!.click();
    });
    await flush();
    const dialog = container.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.textContent).toContain("Reativar comunicações");

    // Após a reativação, o detalhe recarrega já sem opt-out.
    apiMock.reactivateCommunications.mockResolvedValue(reactivateResult());
    apiMock.fetchContactDetail.mockResolvedValue(detail({ optout: false }));

    // Botão de confirmação DENTRO do diálogo.
    const confirm = [...dialog!.querySelectorAll("button")].find((b) =>
      b.textContent!.includes("Reativar comunicações"),
    );
    expect(confirm).toBeDefined();
    act(() => {
      confirm!.click();
    });
    await flush();

    expect(apiMock.reactivateCommunications).toHaveBeenCalledWith("tok-1", "p1");
    // Diálogo fechou, feedback de sucesso visível e botão sumiu (optout=false).
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.querySelector('[role="status"]')?.textContent).toContain(
      "Comunicações reativadas",
    );
    expect(findButton("Reativar comunicações")).toBeUndefined();
  });

  it("cancelar no ds/Dialog fecha sem chamar o endpoint", async () => {
    apiMock.fetchContactDetail.mockResolvedValue(detail({ optout: true }));
    await renderPanel();
    act(() => {
      findButton("Reativar comunicações")!.click();
    });
    await flush();
    const dialog = container.querySelector<HTMLElement>('[role="dialog"]')!;
    const cancel = [...dialog.querySelectorAll("button")].find((b) =>
      b.textContent!.includes("Cancelar"),
    )!;
    act(() => {
      cancel.click();
    });
    await flush();
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(apiMock.reactivateCommunications).not.toHaveBeenCalled();
    // Botão continua lá (pessoa segue em opt-out).
    expect(findButton("Reativar comunicações")).toBeDefined();
  });
});
