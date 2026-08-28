// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AdminRequestError,
  AdminSessionExpiredError,
  type AdminConsentGovernanceState,
  type ConsentGovernanceDecisionPayload,
  type ConsentGovernancePurpose,
} from "@/lib/admin-api";

import { ConsentGovernanceDraftTab } from "./ConsentGovernanceDraftTab";

const api = vi.hoisted(() => ({
  fetchIgrejaConsentGovernance: vi.fn(),
  initializeIgrejaConsentGovernance: vi.fn(),
  updateIgrejaConsentGovernancePurpose: vi.fn(),
}));

vi.mock("@/lib/admin-api", () => {
  class MockAdminRequestError extends Error {
    readonly status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "AdminRequestError";
      this.status = status;
    }
  }
  class MockAdminSessionExpiredError extends Error {}
  return {
    ...api,
    AdminRequestError: MockAdminRequestError,
    AdminSessionExpiredError: MockAdminSessionExpiredError,
    CONSENT_GOVERNANCE_PURPOSES: [
      "atendimento_solicitado",
      "cuidado_pastoral",
      "tarefas_operacionais",
      "comunicados",
    ],
  };
});

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const PURPOSES: ConsentGovernancePurpose[] = [
  "atendimento_solicitado",
  "cuidado_pastoral",
  "tarefas_operacionais",
  "comunicados",
];

const EMPTY_PAYLOAD: ConsentGovernanceDecisionPayload = {
  realProcessingAgents: null,
  operationsAndMinimumData: null,
  dataSensitivityAssessment: null,
  operationalNeed: null,
  systemsAndRecipients: null,
  retentionAndDisposalInventory: null,
  operatorInstructions: null,
  openQuestions: null,
};

function makeState(
  overrides: Partial<AdminConsentGovernanceState> = {},
): AdminConsentGovernanceState {
  return {
    enabled: true,
    initialized: true,
    schemaVersion: "d2b2b3a/governance-draft/v1",
    revision: 1,
    purposes: PURPOSES.map((purpose) => ({
      purpose,
      purposeLabel: purpose.replaceAll("_", " "),
      revision: 1,
      purposeStatus: "DRAFT_NOT_APPROVED" as const,
      decisionPayload: { ...EMPTY_PAYLOAD },
      controllerApproved: false as const,
      humanPacketComplete: false as const,
      catalogReady: false as const,
      writerEligible: false as const,
    })),
    ...overrides,
  };
}

let container: HTMLDivElement;
let root: Root;

function flush() {
  return act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function render(
  state = makeState(),
  props: Partial<Parameters<typeof ConsentGovernanceDraftTab>[0]> = {},
) {
  act(() => {
    root.render(
      h(ConsentGovernanceDraftTab, {
        token: "tok",
        igrejaId: "igreja-1",
        initialState: state,
        onExpired: () => {},
        ...props,
      }),
    );
  });
}

function findButton(label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((button) =>
    button.textContent?.includes(label),
  );
}

function setValue(element: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )!.set!;
  act(() => {
    setter.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  api.fetchIgrejaConsentGovernance.mockReset();
  api.initializeIgrejaConsentGovernance.mockReset();
  api.updateIgrejaConsentGovernancePurpose.mockReset();
  vi.restoreAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe("ConsentGovernanceDraftTab", () => {
  it("mantém o aviso permanente, renderiza exatamente quatro cards e não oferece gates", () => {
    render();

    expect(container.querySelector("[data-testid='draft-only-banner']")?.textContent).toContain(
      "Rascunho, não aprovado",
    );
    expect(container.querySelector("[data-testid='draft-only-banner']")?.textContent).toContain(
      "Não inclua dados pessoais",
    );
    expect(container.querySelectorAll("[data-testid='governance-purpose-card']")).toHaveLength(
      4,
    );
    const buttonLabels = [...container.querySelectorAll("button")].map(
      (button) => button.textContent ?? "",
    );
    expect(buttonLabels.some((label) => /^Aprovar/i.test(label))).toBe(false);
    expect(buttonLabels.some((label) => /Assinar|Catalogar|Ativar/i.test(label))).toBe(false);
  });

  it("mantém orientação contra PII visível antes de inicializar e dentro do editor", () => {
    render(makeState({ initialized: false, purposes: [] }));
    expect(container.textContent).toContain(
      "nomes, telefones, e-mails, documentos, mensagens, relatos",
    );

    act(() => root.unmount());
    root = createRoot(container);
    render();
    act(() => findButton("Editar rascunho")!.click());

    expect(container.textContent).toContain(
      "Liste somente funções, equipes e tipos de fornecedor, sem identificar pessoas.",
    );
    expect(container.textContent).toContain(
      "categorias de dados, sem exemplos, valores ou registros reais.",
    );
  });

  it("não renderiza conteúdo quando o backend desabilita a função", () => {
    render(makeState({ enabled: false }));
    expect(container.innerHTML).toBe("");
  });

  it("inicializa somente depois de confirmação explícita", async () => {
    const initial = makeState({ initialized: false, purposes: [] });
    const initialized = makeState({ revision: 2 });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    api.initializeIgrejaConsentGovernance.mockResolvedValue(initialized);
    render(initial);

    act(() => findButton("Iniciar quatro rascunhos")!.click());
    expect(api.initializeIgrejaConsentGovernance).not.toHaveBeenCalled();

    act(() => findButton("Iniciar quatro rascunhos")!.click());
    await flush();

    expect(confirm).toHaveBeenCalledTimes(2);
    expect(api.initializeIgrejaConsentGovernance).toHaveBeenCalledWith("tok", "igreja-1");
    expect(container.querySelectorAll("[data-testid='governance-purpose-card']")).toHaveLength(
      4,
    );
  });

  it("salva apenas os oito campos operacionais com revisão esperada", async () => {
    const initial = makeState();
    const saved = makeState({
      revision: 2,
      purposes: initial.purposes.map((purpose) =>
        purpose.purpose === "atendimento_solicitado"
          ? {
              ...purpose,
              revision: 2,
              decisionPayload: {
                ...EMPTY_PAYLOAD,
                realProcessingAgents: "Equipe pastoral",
              },
            }
          : purpose,
      ),
    });
    api.updateIgrejaConsentGovernancePurpose.mockResolvedValue(saved);
    render(initial);

    act(() => findButton("Editar rascunho")!.click());
    const textarea = container.querySelector<HTMLTextAreaElement>(
      "#governance-atendimento_solicitado-realProcessingAgents",
    )!;
    setValue(textarea, "  Equipe pastoral  ");
    act(() => {
      container
        .querySelector<HTMLFormElement>("#governance-draft-editor")!
        .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await flush();

    expect(api.updateIgrejaConsentGovernancePurpose).toHaveBeenCalledWith(
      "tok",
      "igreja-1",
      "atendimento_solicitado",
      {
        expectedRevision: 1,
        decisionPayload: {
          realProcessingAgents: "Equipe pastoral",
          operationsAndMinimumData: null,
          dataSensitivityAssessment: null,
          operationalNeed: null,
          systemsAndRecipients: null,
          retentionAndDisposalInventory: null,
          operatorInstructions: null,
          openQuestions: null,
        },
      },
    );
    expect(container.textContent).toContain(
      "Rascunho operacional salvo. Ele continua não aprovado.",
    );
  });

  it("limita cada campo e bloqueia payload operacional acima de 16 mil caracteres", () => {
    render();
    act(() => findButton("Editar rascunho")!.click());

    const textareas = [...container.querySelectorAll<HTMLTextAreaElement>("textarea")];
    expect(textareas).toHaveLength(8);
    expect(textareas.every((textarea) => textarea.maxLength === 4_000)).toBe(true);

    textareas.slice(0, 5).forEach((textarea) => setValue(textarea, "a".repeat(4_000)));

    expect(findButton("Salvar rascunho")?.disabled).toBe(true);
    expect(container.querySelector("[role='alert']")?.textContent).toContain(
      "20.000/16.000 caracteres",
    );
  });

  it("em 409 recarrega a revisão corrente e exige nova revisão do operador", async () => {
    const current = makeState({
      revision: 3,
      purposes: makeState().purposes.map((purpose) =>
        purpose.purpose === "atendimento_solicitado"
          ? {
              ...purpose,
              revision: 3,
              decisionPayload: {
                ...EMPTY_PAYLOAD,
                realProcessingAgents: "Outra equipe",
              },
            }
          : purpose,
      ),
    });
    api.updateIgrejaConsentGovernancePurpose.mockRejectedValue(
      new AdminRequestError(409, "Revisão divergente."),
    );
    api.fetchIgrejaConsentGovernance.mockResolvedValue(current);
    render();

    act(() => findButton("Editar rascunho")!.click());
    setValue(
      container.querySelector<HTMLTextAreaElement>(
        "#governance-atendimento_solicitado-realProcessingAgents",
      )!,
      "Minha edição",
    );
    act(() => findButton("Salvar rascunho")!.click());
    await flush();

    expect(api.fetchIgrejaConsentGovernance).toHaveBeenCalledWith("tok", "igreja-1");
    expect(container.querySelector<HTMLTextAreaElement>(
      "#governance-atendimento_solicitado-realProcessingAgents",
    )?.value).toBe("Outra equipe");
    expect(container.querySelector("[role='alert']")?.textContent).toContain(
      "alterado em outra sessão",
    );
  });

  it("encaminha 401 para expiração da sessão", async () => {
    const onExpired = vi.fn();
    api.initializeIgrejaConsentGovernance.mockRejectedValue(
      new AdminSessionExpiredError(),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(makeState({ initialized: false, purposes: [] }), { onExpired });

    act(() => findButton("Iniciar quatro rascunhos")!.click());
    await flush();

    expect(onExpired).toHaveBeenCalledTimes(1);
  });
});
