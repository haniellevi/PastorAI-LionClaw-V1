/**
 * Decide como o CTA de um item do checklist (#setup) deve navegar.
 *
 * 'celulas' não está em ADMIN_NAV_SECTIONS — o cadastro/CRUD de célula vive só
 * na superfície operacional (tela LEGACY, acesso implícito do admin via
 * canSee). Navegar por hash local dentro do admin faz o AdminAppShell recusar
 * a rota (não está em ADMIN_SCREENS) e voltar pro #setup em silêncio. Por
 * isso esse item cruza de superfície com appSurfaceHref() direto pra Central
 * de Célula; os demais navegam internamente pelo screen que o backend manda.
 */
import { appSurfaceHref } from "./surface";

export type SetupNavAction =
  | { kind: "internal"; screen: string }
  | { kind: "external"; href: string };

export function resolveSetupNavAction(item: { id: string; screen: string }): SetupNavAction {
  if (item.id === "celulas") {
    return { kind: "external", href: `${appSurfaceHref()}#central-celula` };
  }
  return { kind: "internal", screen: item.screen };
}
