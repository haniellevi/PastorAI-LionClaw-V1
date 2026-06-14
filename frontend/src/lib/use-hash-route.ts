"use client";

/**
 * Roteamento por hash (#rota) — seção 4.2. Troca de tela SEM reload,
 * sincronizado com `location.hash`. Retorna a rota atual e um navegador.
 */
import { useCallback, useEffect, useState } from "react";

function readHash(): string {
  if (typeof window === "undefined") return "";
  return window.location.hash.replace(/^#/, "");
}

export function useHashRoute(): [string, (route: string) => void] {
  const [route, setRoute] = useState<string>(readHash);

  useEffect(() => {
    const onChange = () => setRoute(readHash());
    window.addEventListener("hashchange", onChange);
    // Sincroniza no mount (cobre SSR -> hydration).
    onChange();
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const navigate = useCallback((next: string) => {
    const target = next.startsWith("#") ? next : `#${next}`;
    if (window.location.hash !== target) {
      window.location.hash = target;
    } else {
      // Mesma rota: força re-sync (ex.: clique repetido).
      setRoute(readHash());
    }
  }, []);

  return [route, navigate];
}
