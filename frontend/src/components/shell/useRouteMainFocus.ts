"use client";

/**
 * Move o foco para o landmark principal depois de uma troca real de rota.
 * A montagem inicial fica intacta para não interromper a recuperação de sessão
 * nem o foco que o navegador já tenha escolhido.
 */
import { useEffect, useRef } from "react";

export function useRouteMainFocus(route: string) {
  const mainRef = useRef<HTMLElement | null>(null);
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }

    mainRef.current?.focus({ preventScroll: true });
  }, [route]);

  return mainRef;
}
