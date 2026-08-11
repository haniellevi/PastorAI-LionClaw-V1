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
  fetchWorkQueue,
} from "./dashboard-api";
import { fetchEvents } from "./events-api";
import type { Role } from "./roles";

export async function preloadRouteData(
  token: string,
  route: string,
  roles: readonly Role[],
): Promise<void> {
  let jobs: Promise<unknown>[] = [];
  const canLinkCell = roles.some((role) => role === "admin" || role === "pastor");
  const canAssignQueue = roles.some(
    (role) =>
      role === "admin" ||
      role === "pastor" ||
      role === "lider_g12" ||
      role === "lider_consol",
  );

  switch (route) {
    case "dashboard":
      jobs = [
        fetchWorkQueue(token),
        ...(canAssignQueue ? [fetchTeamLookup(token)] : []),
        ...(canLinkCell ? [fetchCells(token)] : []),
        fetchOverview(token),
      ];
      break;
    case "calendario":
      jobs = [fetchEvents(token)];
      break;
    case "ganhar":
      jobs = [
        fetchPipeline(token, "ganhar"),
        ...(canLinkCell ? [fetchCells(token)] : []),
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
