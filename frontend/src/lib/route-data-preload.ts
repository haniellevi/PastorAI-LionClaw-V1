/**
 * Pré-carrega somente os dados das rotas mais usadas. As funções abaixo usam
 * o mesmo cache curto e isolado por sessão que as telas reais; portanto, ao
 * clicar, a tela consome a resposta já validada em vez de repetir a viagem à
 * API. Falha de prefetch é silenciosa: a própria tela mantém seu erro/retry.
 */
import { fetchPipeline } from "./contacts-api";
import { fetchConversations } from "./conversations-api";
import {
  fetchCells,
  fetchOverview,
  fetchTeamLookup,
  fetchWorkQueuePage,
} from "./dashboard-api";
import { resolveDashboardResponsibilities } from "./dashboard-responsibilities";
import { fetchEvents, fetchUpcomingEvents } from "./events-api";
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
        ...(responsibilities.canAssignQueue ? [fetchTeamLookup(token)] : []),
        ...(responsibilities.canLinkCell ? [fetchCells(token)] : []),
        ...(responsibilities.showOverview ? [fetchOverview(token)] : []),
        ...(canSee("calendario", roles, matrix) ? [fetchUpcomingEvents(token)] : []),
      ];
      break;
    case "calendario":
      jobs = [fetchEvents(token)];
      break;
    case "ganhar":
      jobs = [
        fetchPipeline(token, "ganhar"),
        ...(responsibilities.canLinkCell ? [fetchCells(token)] : []),
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
