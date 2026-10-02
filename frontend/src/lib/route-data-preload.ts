/**
 * Pré-carrega somente os dados das rotas mais usadas. As funções abaixo usam
 * o mesmo cache curto e isolado por sessão que as telas reais; portanto, ao
 * clicar, a tela consome a resposta já validada em vez de repetir a viagem à
 * API. Falha de prefetch é silenciosa: a própria tela mantém seu erro/retry.
 */
import { fetchPipeline } from "./contacts-api";
import { fetchConversations } from "./conversations-api";
import {
  fetchOverview,
  fetchWorkQueuePage,
} from "./dashboard-api";
import { resolveDashboardResponsibilities } from "./dashboard-responsibilities";
import { fetchEventWindowPage, eventWindow, fetchUpcomingEvents } from "./events-api";
import { canSee, DEFAULT_PERMISSIONS, type PermissionMatrix } from "./permissions";
import type { Role } from "./roles";

export async function preloadRouteData(
  token: string,
  route: string,
  roles: readonly Role[],
  matrix: PermissionMatrix = DEFAULT_PERMISSIONS,
): Promise<void> {
  let jobs: Promise<unknown>[] = [];
  const responsibilities = resolveDashboardResponsibilities(roles);

  switch (route) {
    case "dashboard":
      jobs = [
        ...(responsibilities.hasWorkQueue ? [fetchWorkQueuePage(token, 1, 25)] : []),
        ...(responsibilities.showOverview ? [fetchOverview(token)] : []),
        ...(canSee("calendario", roles, matrix) ? [fetchUpcomingEvents(token)] : []),
      ];
      break;
    case "calendario": {
      const window = eventWindow("mes", new Date());
      jobs = [fetchEventWindowPage(token, 1, 200, window.fromDate, window.toDate)];
      break;
    }
    case "ganhar":
      jobs = [
        fetchPipeline(token, "ganhar", 50, {group:"novos-contatos"}),
      ];
      break;
    case "inbox":
      jobs = [fetchConversations(token)];
      break;
    default:
      return;
  }

  await Promise.allSettled(jobs);
}
