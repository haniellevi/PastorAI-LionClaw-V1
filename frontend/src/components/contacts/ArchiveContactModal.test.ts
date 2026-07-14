// @vitest-environment jsdom
/**
 * M7B-W3.2B — confirmação de arquivamento de Pessoa:
 *  - preflight liberado exibe automáticos/preservados e habilita confirmar
 *    só depois de um motivo preenchido, enviando-o já aparado (trim);
 *  - preflight bloqueado nunca renderiza o botão de confirmar (pode_arquivar
 *    controla a existência do botão, não só seu estado disabled);
 *  - erro de preflight oferece "Tentar novamente"; erro de confirmação
 *    (403/409) aparece como banner sem fechar o diálogo.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Contact, OffboardingPreflight } from "@/lib/contacts-api";

import { ArchiveContactModal } from "./ArchiveContactModal";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const contact: Contact = {
  id: "p1",
  nome: "Ana Souza",
  telefone: "5511987654321",
  email: null,
  genero: null,
  tipo: "membro",
  etapa: "discipular",
  subetapa: null,
  acompanhamento: null,
  semInteresse: false,
  semInteresseMotivo: null,
  presencasCelula: 4,
  aceitouJesus: true,
  celulaId: null,
  liderId: null,
  aptoLider: false,
  liderDeCelula: false,
};

function preflight(over: Partial<OffboardingPreflight> = {}): OffboardingPreflight {
  return {
    pessoa_id: "p1",
    pode_arquivar: true,
    bloqueadores: [],
    automaticos: [],
    preservados: [
      { tipo: "conversas_mensagens", rotulo: "Conversas e mensagens do WhatsApp", recurso_id: null, recurso_nome: null, acao_recomendada: null },
    ],
    ...over,
  };
}

let container: HTMLDivElement;
let root: Root;

function render(props: Partial<Parameters<typeof ArchiveContactModal>[0]> = {}) {
  act(() => {
    root.render(
      h(ArchiveContactModal, {
        contact,
        preflight: preflight(),
        preflightLoading: false,
        preflightError: null,
        busy: false,
        error: null,
        onRetryPreflight: () => {},
        onClose: () => {},
        onConfirm: () => {},
        ...props,
      }),
    );
  });
}

function findButton(label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((b) => b.textContent!.includes(label));
}

function setTextarea(value: string) {
  const textarea = container.querySelector("textarea")!;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")!.set!;
  act(() => {
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ArchiveContactModal — M7B-W3.2B", () => {
  it("preflight liberado: mostra preservados, permite confirmar e envia o motivo aparado", () => {
    const onConfirm = vi.fn();
    render({ preflight: preflight({ pode_arquivar: true }), onConfirm });

    expect(container.textContent).toContain("Conversas e mensagens do WhatsApp");
    expect(container.textContent).toContain("não é excluído");

    setTextarea("  Mudou de cidade  ");
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith("Mudou de cidade");
  });

  it("motivo vazio: clique não confirma e mostra o erro de validação", () => {
    const onConfirm = vi.fn();
    render({ onConfirm });
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    expect(onConfirm).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Informe o motivo",
    );
  });

  it("bloqueadores presentes: pode_arquivar=false não renderiza o botão de confirmar", () => {
    const onConfirm = vi.fn();
    render({
      preflight: preflight({
        pode_arquivar: false,
        bloqueadores: [
          {
            tipo: "celula_lider",
            rotulo: "Líder de célula ativa",
            recurso_id: "c1",
            recurso_nome: "Célula Central",
            acao_recomendada: "Troque o líder da célula antes de arquivar.",
          },
        ],
      }),
      onConfirm,
    });

    expect(findButton("Arquivar pessoa")).toBeUndefined();
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.textContent).toContain("Não é possível arquivar agora");
    expect(container.textContent).toContain("Líder de célula ativa");
    expect(container.textContent).toContain("Célula Central");
    expect(container.textContent).toContain("Troque o líder da célula antes de arquivar.");
    expect(findButton("Fechar")).toBeDefined();
  });

  it("erro de preflight: mostra banner com Tentar novamente e não trava a UI", () => {
    const onRetryPreflight = vi.fn();
    render({
      preflight: null,
      preflightError: "Não foi possível verificar se esta pessoa pode ser arquivada.",
      onRetryPreflight,
    });
    expect(container.textContent).toContain("Não foi possível verificar");
    act(() => {
      findButton("Tentar novamente")!.click();
    });
    expect(onRetryPreflight).toHaveBeenCalledTimes(1);
  });

  it("preflight carregando: não mostra formulário nem listas", () => {
    render({ preflight: null, preflightLoading: true });
    expect(container.querySelector("textarea")).toBeNull();
    expect(findButton("Arquivar pessoa")).toBeUndefined();
  });

  it("erro de confirmação (409/403) aparece como banner sem fechar o diálogo", () => {
    render({ error: "Não é possível arquivar: há vínculos ativos pendentes." });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Não é possível arquivar: há vínculos ativos pendentes.",
    );
    // O diálogo segue aberto — o formulário continua presente.
    expect(container.querySelector("textarea")).not.toBeNull();
  });
});
