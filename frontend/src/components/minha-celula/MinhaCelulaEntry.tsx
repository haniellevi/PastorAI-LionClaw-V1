"use client";

/**
 * Entrada da Minha Célula por PAPEL autenticado (sem toggle de demonstração):
 *   - Líder de célula (lider_celula) → visão do Líder (casca por ora);
 *   - demais (membro/discípulo)      → visão do Discípulo (US-01..05, US-21).
 * A decisão vem dos papéis reais de /auth/me; nada é escolhido na UI.
 */
import { useAuth } from "@/lib/auth-context";
import { DiscipuloScreen } from "./DiscipuloScreen";
import { MinhaCelulaLider } from "./MinhaCelulaLider";

export function MinhaCelulaEntry() {
  const { user } = useAuth();
  const isCellLeader = user?.roles.includes("lider_celula") ?? false;

  return isCellLeader ? <MinhaCelulaLider /> : <DiscipuloScreen />;
}
