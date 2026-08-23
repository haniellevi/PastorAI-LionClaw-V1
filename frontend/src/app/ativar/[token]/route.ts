import { NextResponse } from "next/server";

import {
  buildPublicAuthRedirectUrl,
  PUBLIC_AUTH_RESPONSE_HEADERS,
} from "@/lib/public-auth-flow";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = await params;
  const response = NextResponse.redirect(
    buildPublicAuthRedirectUrl(request.url, "ativar", token),
    307,
  );

  for (const [name, value] of Object.entries(PUBLIC_AUTH_RESPONSE_HEADERS)) {
    response.headers.set(name, value);
  }
  return response;
}
