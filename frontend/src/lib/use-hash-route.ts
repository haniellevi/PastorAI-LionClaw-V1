"use client";

/**
 * Roteamento por hash (#rota) — seção 4.2. Troca de tela SEM reload,
 * sincronizado com `location.hash`. Retorna a rota atual e um navegador.
 */
import { useCallback, useSyncExternalStore } from "react";

let currentHash: string | null = null;
let subscribers = 0;
let currentHistoryIndex: number | null = null;
let currentHistoryState: unknown = null;
let hashRouteGuard: ((event: Event) => boolean) | null = null;
let guardedEvent: Event | null = null;
let guardedEventAllowed = true;

/** Confirma a saída antes de publicar o hash, independente da ordem no Window. */
export function registerHashRouteGuard(guard: (event: Event) => boolean): () => void {
  hashRouteGuard = guard;
  guardedEvent = null;
  return () => {
    if (hashRouteGuard === guard) {
      hashRouteGuard = null;
      guardedEvent = null;
    }
  };
}

/** Índice do documento atual, sem substituir URL ou state interno do Next. */
export function getHashRouteHistoryIndex(): number {
  // Fragmentos nativos começam sem state. Reutilizar a última entrada do
  // documento preserva o contrato do router, sem fabricar campos internos.
  const state = window.history.state ?? currentHistoryState;
  const entry = state?.__igreja12HashEntry;
  if (entry?.url === window.location.href && Number.isSafeInteger(entry.index)) {
    return entry.index;
  }
  // Um fragmento novo pode copiar o state anterior. A URL identifica a entrada.
  const index = (currentHistoryIndex ?? -1) + 1;
  // Só anotamos state. Passar uma URL ao wrapper Next pode disparar restore.
  window.history.replaceState({
    ...state,
    __igreja12HashEntry: { index, url: window.location.href },
  }, "");
  return index;
}

function readHash(): string {
  if (typeof window === "undefined") return "";
  // O snapshot muda somente após hashchange. Renderizações disparadas por
  // popstate/Next antes desse evento não desmontam uma tela com rascunho
  // antes que seu guard de navegação possa confirmar ou cancelar a saída.
  if (subscribers > 0 && currentHash !== null) return currentHash;
  return window.location.hash.replace(/^#/, "");
}

function subscribe(onChange: () => void): () => void {
  if (subscribers++ === 0) {
    currentHash = window.location.hash.replace(/^#/, "");
    currentHistoryIndex = getHashRouteHistoryIndex();
    currentHistoryState = window.history.state;
  }
  const sync = (event: Event) => {
    if (hashRouteGuard) {
      if (guardedEvent !== event) {
        guardedEvent = event;
        guardedEventAllowed = hashRouteGuard(event);
      }
      if (!guardedEventAllowed) return;
    }
    currentHistoryIndex = getHashRouteHistoryIndex();
    currentHistoryState = window.history.state;
    currentHash = window.location.hash.replace(/^#/, "");
    onChange();
  };
  window.addEventListener("hashchange", sync);
  return () => {
    window.removeEventListener("hashchange", sync);
    if (--subscribers === 0) {
      currentHash = null;
      currentHistoryIndex = null;
      currentHistoryState = null;
    }
  };
}

function serverHash(): string {
  return "";
}

export function useHashRoute(): [string, (route: string) => void] {
  // SSR e hidratação compartilham o vazio; mounts client já recebem o hash atual.
  const route = useSyncExternalStore(subscribe, readHash, serverHash);

  const navigate = useCallback((next: string) => {
    const target = next.startsWith("#") ? next : `#${next}`;
    if (window.location.hash !== target) {
      window.location.hash = target;
    } else {
      // Mesma rota: força re-sync (ex.: clique repetido).
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    }
  }, []);

  return [route, navigate];
}
