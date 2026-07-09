/**
 * Prova a correção do PR #138: 'celulas' não está em ADMIN_NAV_SECTIONS, então
 * navegar por hash local dentro da superfície admin faz o AdminAppShell
 * recusar a rota e voltar pro #setup em silêncio (bug corrigido). O CTA desse
 * item precisa cruzar de superfície (appSurfaceHref) direto pra
 * #central-celula — nunca chamar navigate("celulas") por dentro do admin.
 */
import { describe, expect, it } from "vitest";

import { resolveSetupNavAction } from "./setup-nav";

describe("resolveSetupNavAction", () => {
  it("celulas cruza pra superfície operacional em #central-celula, nunca navega interno pra 'celulas'", () => {
    const action = resolveSetupNavAction({ id: "celulas", screen: "celulas" });
    expect(action.kind).toBe("external");
    if (action.kind !== "external") throw new Error("unreachable");
    expect(action.href.endsWith("#central-celula")).toBe(true);
    expect(action.href).not.toContain("#celulas");
  });

  it.each(["identidade", "equipe", "whatsapp", "agente", "assinatura"])(
    "%s navega internamente pelo screen que o backend manda",
    (id) => {
      const action = resolveSetupNavAction({ id, screen: id });
      expect(action).toEqual({ kind: "internal", screen: id });
    },
  );
});
