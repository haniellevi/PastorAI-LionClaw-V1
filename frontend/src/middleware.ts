import { NextResponse, type NextRequest } from "next/server";

/**
 * Roteia o subdomínio dedicado do console master.
 *
 * - `admin.igreja12.com.br/…`  → serve o console (`/admin/…`) na raiz, sem o
 *   usuário precisar digitar `/admin`. O painel da igreja (`/`) não é exposto
 *   nesse host.
 * - `app.igreja12.com.br/…`    → inalterado (painel da igreja em `/`; o console
 *   continua acessível por `app.igreja12.com.br/admin`).
 *
 * É só reescrita interna (a URL no navegador continua `admin.igreja12.com.br/…`).
 * As chamadas de API vão para `NEXT_PUBLIC_API_URL` (independe do host), então o
 * console funciona igual nos dois domínios.
 */
export function middleware(req: NextRequest) {
  const rawHost = req.headers.get("host") ?? "";
  const host = (rawHost.split(":")[0] ?? "").toLowerCase();
  const isAdminHost = host.startsWith("admin.");
  const { pathname } = req.nextUrl;

  if (isAdminHost && !pathname.startsWith("/admin")) {
    const url = req.nextUrl.clone();
    url.pathname = pathname === "/" ? "/admin" : `/admin${pathname}`;
    return NextResponse.rewrite(url);
  }

  return NextResponse.next();
}

export const config = {
  // Ignora assets do Next, favicon e arquivos com extensão (estáticos).
  matcher: ["/((?!_next/|favicon\\.ico|.*\\..*).*)"],
};
