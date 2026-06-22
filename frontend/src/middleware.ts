import { NextResponse, type NextRequest } from "next/server";

/**
 * Roteia o subdomínio dedicado do console master (superfície separada do painel
 * da igreja). O console tem UM endereço canônico: `admin.<dominio>`.
 *
 * - `admin.igreja12.com.br/…`     → serve o console (`/admin/…`) na raiz, sem o
 *   usuário precisar digitar `/admin` (reescrita interna; a URL no navegador
 *   continua `admin.igreja12.com.br/…`).
 * - `app.igreja12.com.br/admin…`  → REDIRECIONA para `admin.<dominio>` (o painel
 *   da igreja não expõe a tela do master; links antigos continuam levando ao
 *   lugar certo).
 * - `app.igreja12.com.br/…`       → inalterado (painel da igreja em `/`).
 *
 * As chamadas de API vão para `NEXT_PUBLIC_API_URL` (independe do host).
 */
export function middleware(req: NextRequest) {
  const rawHost = req.headers.get("host") ?? "";
  const host = (rawHost.split(":")[0] ?? "").toLowerCase();
  const { pathname } = req.nextUrl;

  // admin.<dominio>/… → serve o console na raiz.
  if (host.startsWith("admin.") && !pathname.startsWith("/admin")) {
    const url = req.nextUrl.clone();
    url.pathname = pathname === "/" ? "/admin" : `/admin${pathname}`;
    return NextResponse.rewrite(url);
  }

  // app.<dominio>/admin… → redireciona para o subdomínio dedicado.
  if (host.startsWith("app.") && pathname.startsWith("/admin")) {
    const target = new URL(req.nextUrl.toString());
    target.host = host.replace(/^app\./, "admin.");
    target.pathname = pathname.replace(/^\/admin/, "") || "/";
    return NextResponse.redirect(target);
  }

  return NextResponse.next();
}

export const config = {
  // Ignora assets do Next, favicon e arquivos com extensão (estáticos).
  matcher: ["/((?!_next/|favicon\\.ico|.*\\..*).*)"],
};
