"use client";

import type { ReactNode } from "react";

import { AuthProvider } from "@/lib/auth-context";
import { PermissionsProvider } from "@/lib/permissions-context";

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <PermissionsProvider>{children}</PermissionsProvider>
    </AuthProvider>
  );
}
