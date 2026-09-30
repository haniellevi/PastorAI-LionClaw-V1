"use client";

/**
 * Roteamento por hash (#rota) — seção 4.2. Troca de tela SEM reload,
 * sincronizado com `location.hash`. Retorna a rota atual e um navegador.
 */
import { useCallback, useSyncExternalStore } from "react";

function readHash(): string {
  if (typeof window === "undefined") return "";
  return window.location.hash.replace(/^#/, "");
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
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
