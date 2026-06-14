"use client";

/**
 * Providers globais do app.
 * Integra o Clerk SDK (US-01) quando há publishable key configurada. Sem chave,
 * o app roda em modo backend-only: o login continua consumindo api-login (que
 * valida credenciais no Clerk pelo servidor), mantendo o build verde em CI.
 */
import { ClerkProvider } from "@clerk/nextjs";
import type { ReactNode } from "react";

import { AuthProvider } from "@/lib/auth-context";
import { PermissionsProvider } from "@/lib/permissions-context";

const CLERK_KEY = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export function AppProviders({ children }: { children: ReactNode }) {
  const tree = (
    <AuthProvider>
      <PermissionsProvider>{children}</PermissionsProvider>
    </AuthProvider>
  );

  // ClerkProvider só é montado com chave válida (evita throw em build/SSR sem env).
  if (CLERK_KEY) {
    return <ClerkProvider publishableKey={CLERK_KEY}>{tree}</ClerkProvider>;
  }
  return tree;
}
