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

export async function preloadRouteData(token: string, route: string): Promise<void> {
  let jobs: Promise<unknown>[] = [];

  switch (route) {
    case "dashboard":
      jobs = [
        fetchWorkQueue(token),
        fetchTeamLookup(token),
        fetchCells(token),
        fetchOverview(token),
      ];
      break;
    case "calendario":
      jobs = [fetchEvents(token)];
      break;
    case "ganhar":
      jobs = [fetchPipeline(token, "ganhar"), fetchCells(token)];
      break;
    case "inbox":
      jobs = [fetchConversations(token)];
      break;
    default:
      return;
  }

  await Promise.allSettled(jobs);
}
