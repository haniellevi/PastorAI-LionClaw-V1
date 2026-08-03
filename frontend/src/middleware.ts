import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_LEGAL_PATHS = new Set(["/privacidade", "/termos"]);

/**
 * Roteia as três superfícies por subdomínio (mesmo deployment):
 *
 * - `painel.igreja12.com.br/…` → console master (dono do sistema). Reescreve
 *   internamente para `/admin/…` (rota Next do console), sem o usuário digitar
 *   `/admin`. A URL no navegador continua `painel.<dominio>/…`.
 * - `admin.igreja12.com.br/…`  → painel do ADMIN da igreja. Reescreve para
 *   `/gestao/…` (superfície administrativa da igreja).
 * - `app.igreja12.com.br/admin…` → link legado do console (que morava em
 *   `admin.`): REDIRECIONA para `painel.<dominio>`.
 * - `app.igreja12.com.br/…`    → inalterado (painel operacional em `/`).
 *
 * O path interno (`/admin`, `/gestao`) é ortogonal ao host. As chamadas de API
 * vão para `NEXT_PUBLIC_API_URL` (independe do host).
 */
export function middleware(req: NextRequest) {
  const rawHost = req.headers.get("host") ?? "";
  const host = (rawHost.split(":")[0] ?? "").toLowerCase();
  const { pathname } = req.nextUrl;

  // Documentos públicos existem na raiz em todas as três superfícies. Sem
  // esta exceção, admin./painel. reescreveriam para rotas inexistentes.
  if (PUBLIC_LEGAL_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  // painel.<dominio>/… → serve o console master (rota interna /admin) na raiz.
  if (host.startsWith("painel.") && !pathname.startsWith("/admin")) {
    const url = req.nextUrl.clone();
    url.pathname = pathname === "/" ? "/admin" : `/admin${pathname}`;
    return NextResponse.rewrite(url);
  }

  // admin.<dominio>/… → serve o painel do admin da igreja (rota interna /gestao).
  if (host.startsWith("admin.") && !pathname.startsWith("/gestao")) {
    const url = req.nextUrl.clone();
    url.pathname = pathname === "/" ? "/gestao" : `/gestao${pathname}`;
    return NextResponse.rewrite(url);
  }

  // app.<dominio>/admin… → link legado do console master, agora em painel.
  if (host.startsWith("app.") && pathname.startsWith("/admin")) {
    const target = new URL(req.nextUrl.toString());
    target.host = host.replace(/^app\./, "painel.");
    target.pathname = pathname.replace(/^\/admin/, "") || "/";
    return NextResponse.redirect(target);
  }

  return NextResponse.next();
}

export const config = {
  // Ignora assets do Next, favicon e arquivos com extensão (estáticos).
  matcher: ["/((?!_next/|favicon\\.ico|.*\\..*).*)"],
};
