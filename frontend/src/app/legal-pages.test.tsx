import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import PrivacyPage, { metadata as privacyMetadata } from "./privacidade/page";
import TermsPage, { metadata as termsMetadata } from "./termos/page";

describe("páginas legais públicas", () => {
  it("descreve LGPD, dados religiosos e o Uso Limitado das APIs Google", () => {
    const html = renderToStaticMarkup(<PrivacyPage />);

    expect(html).toContain("Política de Privacidade");
    expect(html).toContain("dados pessoais sensíveis");
    expect(html).toContain("Uso Limitado (Limited Use)");
    expect(html).toContain("não são vendidos");
    expect(html).toContain("Google Calendar");
    expect(html).toContain("Autoridade Nacional de Proteção de Dados");
    expect(html).toContain("pr.raniellevi@gmail.com");
    expect(privacyMetadata.title).toBe("Política de Privacidade");
  });

  it("cobre o uso pastoral, IA, WhatsApp, Calendar e legislação brasileira", () => {
    const html = renderToStaticMarkup(<TermsPage />);

    expect(html).toContain("Termos de Uso");
    expect(html).toContain("WhatsApp");
    expect(html).toContain("Inteligência artificial");
    expect(html).toContain("Google Calendar");
    expect(html).toContain("leis da República Federativa do Brasil");
    expect(html).toContain('href="/privacidade"');
    expect(termsMetadata.title).toBe("Termos de Uso");
  });

  it("não publica marcadores de texto incompleto", () => {
    const html = `${renderToStaticMarkup(<PrivacyPage />)}${renderToStaticMarkup(<TermsPage />)}`;

    expect(html).not.toMatch(/\[(?:VERIFY|FILL IN|TODO|CNPJ|ENDEREÇO|EMPRESA)\]/i);
  });
});
