// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TodayContext } from "./TodayContext";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

type TodayContextProps = Parameters<typeof TodayContext>[0];

function renderContext(
  onNavigate = vi.fn(),
  overrides: Partial<TodayContextProps> = {},
) {
  act(() => {
    root.render(
      createElement(TodayContext, {
        title: "Hoje",
        loading: false,
        events: [
          {
            id: "evento-1",
            titulo: "Culto",
            data: "2026-08-12",
            hora: "19:30",
            descricao: null,
            googleEventId: null,
            sincronizado: false,
            status: "a_confirmar",
          },
        ],
        meeting: {
          id: "reuniao-1",
          celula_id: "celula-1",
          data: "2026-08-13",
          hora: "20:00",
          local: "Casa",
          tema: "Comunhão",
          minha_presenca: "nao_confirmou",
        },
        notices: [],
        showEvents: true,
        showMeeting: true,
        shortcuts: ["inbox"],
        onNavigate,
        now: new Date(2026, 7, 11, 9, 0, 0),
        ...overrides,
      }),
    );
  });
  return onNavigate;
}

describe("TodayContext navigation semantics", () => {
  it("renders events, meeting and shortcuts as real hash links", () => {
    renderContext();

    expect(container.querySelector('a[href="#calendario"]')).not.toBeNull();
    expect(container.querySelector('a[href="#minha-celula"]')).not.toBeNull();
    expect(container.querySelector('a[href="#inbox"]')).not.toBeNull();
    expect(container.textContent).toContain("Pendente de confirmação");
  });

  it("uses shell navigation for plain activation and preserves modified clicks", () => {
    const onNavigate = renderContext();
    const link = container.querySelector<HTMLAnchorElement>('a[href="#calendario"]')!;

    const plainAllowed = link.dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }),
    );
    expect(plainAllowed).toBe(false);
    expect(onNavigate).toHaveBeenCalledWith("calendario");

    onNavigate.mockClear();
    const modifiedAllowed = link.dispatchEvent(
      new MouseEvent("click", {
        bubbles: true,
        cancelable: true,
        button: 0,
        ctrlKey: true,
      }),
    );
    expect(modifiedAllowed).toBe(true);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("puts responsibility shortcuts first when the role depends on them", () => {
    renderContext(vi.fn(), { prioritizeShortcuts: true });

    const firstLink = container.querySelector<HTMLAnchorElement>(".dh-context-body a");
    expect(firstLink?.getAttribute("href")).toBe("#inbox");
  });

  it("distinguishes unavailable sources from genuinely empty sections", () => {
    renderContext(vi.fn(), {
      events: [],
      meeting: null,
      notices: [],
      eventsUnavailable: true,
      meetingUnavailable: true,
      noticesUnavailable: true,
    });

    expect(container.textContent).toContain("Agenda indisponível agora");
    expect(container.textContent).toContain("Reunião indisponível agora");
    expect(container.textContent).toContain("Avisos indisponíveis agora");
    expect(container.textContent).not.toContain("Nenhum evento futuro publicado");
    expect(container.textContent).not.toContain("Nenhuma próxima reunião planejada");
    expect(container.textContent).not.toContain("Nenhum aviso novo");
  });
});
