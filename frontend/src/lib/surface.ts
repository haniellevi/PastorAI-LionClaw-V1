/**
 * Navegação entre superfícies por subdomínio (host-based).
 *  - app.<domínio>    → painel operacional (/)
 *  - admin.<domínio>  → painel do admin da igreja (/gestao)
 *  - painel.<domínio> → console master (/admin) [servido por outra árvore]
 *
 * Em produção troca-se o prefixo do host; em dev (localhost, sem subdomínio)
 * cai-se na rota interna equivalente, para o fluxo funcionar sem DNS.
 */

/** URL da superfície do admin da igreja, a partir do app. */
export function adminSurfaceHref(): string {
  if (typeof window === "undefined") return "/gestao";
  const { protocol, host } = window.location;
  if (host.startsWith("app.")) {
    return `${protocol}//${host.replace(/^app\./, "admin.")}/`;
  }
  // Dev/local ou host sem prefixo: usa a rota interna.
  return "/gestao";
}

/** URL do painel operacional, a partir da superfície do admin. */
export function appSurfaceHref(): string {
  if (typeof window === "undefined") return "/";
  const { protocol, host } = window.location;
  if (host.startsWith("admin.")) {
    return `${protocol}//${host.replace(/^admin\./, "app.")}/`;
  }
  return "/";
}
