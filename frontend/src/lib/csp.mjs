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
 * Scripts: o middleware gera um nonce novo a cada documento e o Next marca
 * com ele os scripts que injeta (por isso as páginas renderizam a cada
 * acesso). `'strict-dynamic'` deixa esses scripts carregarem os chunks; um
 * script injetado sem o nonce é recusado. Sem nonce, a política cai no modo
 * antigo (`'unsafe-inline'`) em vez de quebrar o painel.
 *
 * Estilos: `style-src-elem` aceita só folhas do próprio painel e `<style>`
 * com o nonce; o painel não usa `<style>` inline (os estilos vêm de arquivos
 * .css). `style-src-attr` mantém `'unsafe-inline'` porque o HTML do servidor
 * traz atributos `style=""` dos componentes. `style-src` fica como reserva
 * para navegadores sem CSP nível 3.
 */

const NONCE_PATTERN = /^[A-Za-z0-9+/_-]+={0,2}$/;

/** Nonce novo por documento: 128 bits aleatórios em base64. */
export function generateNonce() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

const DEV_API_URL = "http://localhost:8000";

export function apiOrigin(apiUrl) {
  const value = apiUrl?.trim() || DEV_API_URL;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

export function buildContentSecurityPolicy({ apiUrl, dev = false, nonce } = {}) {
  const api = apiOrigin(apiUrl);
  const hasNonce = typeof nonce === "string" && NONCE_PATTERN.test(nonce);
  const scripts = hasNonce ? [`'nonce-${nonce}'`, "'strict-dynamic'"] : ["'unsafe-inline'"];
  const styleElements = hasNonce ? [`'nonce-${nonce}'`] : ["'unsafe-inline'"];
  const directives = [
    ["default-src", "'self'"],
    ["script-src", "'self'", ...scripts, dev && "'unsafe-eval'"],
    ["style-src", "'self'", "'unsafe-inline'"],
    ["style-src-elem", "'self'", ...styleElements],
    ["style-src-attr", "'unsafe-inline'"],
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
