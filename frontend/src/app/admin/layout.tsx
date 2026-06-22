import type { Metadata } from "next";

import { AdminAuthProvider } from "@/lib/admin-auth-context";

export const metadata: Metadata = {
  title: "Console da Plataforma · Igreja 12",
  description: "Administração multi-igreja do Igreja 12 (acesso restrito).",
  // Superfície interna do provedor: nunca indexar.
  robots: { index: false, follow: false },
};

// Como o painel, é inteiramente client-side e auth-gated.
export const dynamic = "force-dynamic";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminAuthProvider>{children}</AdminAuthProvider>;
}
