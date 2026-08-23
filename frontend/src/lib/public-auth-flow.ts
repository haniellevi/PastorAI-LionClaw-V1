export const PUBLIC_AUTH_RESPONSE_HEADERS = {
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Robots-Tag": "noindex, nofollow",
} as const;

export type PublicAuthFlow = "ativar" | "redefinir-senha";
export type RootAuthStatus =
  | "loading"
  | "authenticated"
  | "unauthenticated"
  | "unavailable";
export type RootSurface = "loading" | "app" | "unavailable" | "login";

export function isPublicAuthFlowRoute(route: string): boolean {
  return (
    route === "ativar" ||
    route.startsWith("ativar/") ||
    route === "redefinir-senha" ||
    route.startsWith("redefinir-senha/")
  );
}

export function resolveRootSurface(
  status: RootAuthStatus,
  route: string,
): RootSurface {
  if (isPublicAuthFlowRoute(route)) return "login";
  if (status === "loading") return "loading";
  if (status === "authenticated") return "app";
  if (status === "unavailable") return "unavailable";
  return "login";
}

export function buildPublicAuthRedirectUrl(
  requestUrl: string,
  flow: PublicAuthFlow,
  token: string,
): URL {
  const destination = new URL("/", requestUrl);
  destination.hash = `${flow}/${encodeURIComponent(token)}`;
  return destination;
}
