/**
 * Política de segurança de conteúdo (CSP) do painel, publicada primeiro em
 * modo de teste (`Content-Security-Policy-Report-Only`): o navegador avisa
 * no console o que seria bloqueado, sem bloquear nada.
 *
 * Origens que o painel usa hoje:
 * - scripts, estilos, fontes (@fontsource) e chunks: o próprio painel;
 * - dados: só a API (`NEXT_PUBLIC_API_URL`, fixada no build);
 * - logos e mídia das conversas: URLs https do armazenamento, montadas pelo
 *   backend (o host não é conhecido no build do painel), mais data:/blob:
 *   das prévias de upload.
 *
 * `'unsafe-inline'` em script-src continua necessário: o App Router injeta
 * scripts inline sem nonce. Trocar por nonce é um passo próprio, antes de
 * passar a política para o modo que bloqueia.
 */

const DEV_API_URL = "http://localhost:8000";

export function apiOrigin(apiUrl) {
  const value = apiUrl?.trim() || DEV_API_URL;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

export function buildContentSecurityPolicy({ apiUrl, dev = false } = {}) {
  const api = apiOrigin(apiUrl);
  const directives = [
    ["default-src", "'self'"],
    ["script-src", "'self'", "'unsafe-inline'", dev && "'unsafe-eval'"],
    ["style-src", "'self'", "'unsafe-inline'"],
    ["img-src", "'self'", "data:", "blob:", "https:", api],
    ["media-src", "'self'", "blob:", "https:", api],
    ["font-src", "'self'", "data:"],
    ["connect-src", "'self'", api],
    ["frame-src", "'none'"],
    ["object-src", "'none'"],
    ["base-uri", "'self'"],
    ["form-action", "'self'"],
    ["frame-ancestors", "'none'"],
  ];
  return directives
    .map(([name, ...sources]) => [name, ...new Set(sources.filter(Boolean))].join(" "))
    .join("; ");
}
