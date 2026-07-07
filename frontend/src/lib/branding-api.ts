/**
 * Cliente da identidade visual da igreja (Missão 4 PR2). Contratos do backend
 * (app/routers/church.py) — todos admin-only:
 *   GET    /igreja/branding  -> { nome, logoUrl }
 *   PUT    /igreja/logo      { mime, base64 } -> { nome, logoUrl }
 *   DELETE /igreja/logo      -> { nome, logoUrl }
 *
 * A logo customizada é a identidade do tenant; a marca do produto "Igreja 12"
 * é outra coisa e não passa por aqui. Sem logo, a UI cai no nome da igreja.
 */

import { SessionExpiredError } from "./api";
import { ApiError, authedFetch, readDetail } from "./dashboard-api";

export interface ChurchBranding {
  /** Nome completo da igreja (fallback textual quando não há logo). */
  nome: string;
  /** URL pública da logo, ou null quando a igreja não tem logo customizada. */
  logoUrl: string | null;
}

/** Formatos aceitos (D5). SVG fica fora do MVP. `image/jpg` é alias de browser. */
export const ACCEPTED_LOGO_MIMES = ["image/png", "image/jpeg", "image/webp"] as const;
/** Atributo `accept` do input (inclui o alias jpg que alguns browsers emitem). */
export const LOGO_ACCEPT_ATTR = "image/png,image/jpeg,image/jpg,image/webp";
/** Teto de 1 MB — o backend revalida (magic bytes + tamanho). */
export const MAX_LOGO_BYTES = 1 * 1024 * 1024;

/**
 * Valida o arquivo escolhido no cliente (UX; o backend é a fonte de segurança).
 * Devolve uma mensagem de erro em pt-BR, ou null se o arquivo passa.
 */
export function validateLogoFile(file: File): string | null {
  const mime = (file.type || "").toLowerCase();
  const accepted: readonly string[] = [...ACCEPTED_LOGO_MIMES, "image/jpg"];
  if (mime === "image/svg+xml") {
    return "SVG não é aceito. Envie uma imagem PNG, JPG ou WebP.";
  }
  if (!accepted.includes(mime)) {
    return "Formato não suportado. Envie uma imagem PNG, JPG ou WebP.";
  }
  if (file.size > MAX_LOGO_BYTES) {
    return "A imagem excede o limite de 1 MB. Escolha um arquivo menor.";
  }
  return null;
}

/** Lê um File e devolve o base64 puro (sem o prefixo `data:...;base64,`). */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Falha ao ler o arquivo."));
        return;
      }
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(new Error("Falha ao ler o arquivo."));
    reader.readAsDataURL(file);
  });
}

function normalizeBranding(d: unknown): ChurchBranding {
  const o = (d ?? {}) as { nome?: unknown; logoUrl?: unknown };
  return {
    nome: typeof o.nome === "string" ? o.nome : "",
    logoUrl: typeof o.logoUrl === "string" && o.logoUrl ? o.logoUrl : null,
  };
}

export async function getChurchBranding(token: string): Promise<ChurchBranding> {
  const res = await authedFetch(token, `/igreja/branding`);
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar a identidade da igreja.");
  }
  return normalizeBranding(await res.json());
}

/** Envia/troca a logo. `mime` é o tipo declarado; o backend confere magic bytes. */
export async function uploadChurchLogo(token: string, file: File): Promise<ChurchBranding> {
  const base64 = await fileToBase64(file);
  const res = await authedFetch(token, `/igreja/logo`, {
    method: "PUT",
    body: JSON.stringify({ mime: file.type || "application/octet-stream", base64 }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível enviar a logo.");
  }
  return normalizeBranding(await res.json());
}

export async function deleteChurchLogo(token: string): Promise<ChurchBranding> {
  const res = await authedFetch(token, `/igreja/logo`, { method: "DELETE" });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível remover a logo.");
  }
  return normalizeBranding(await res.json());
}
