"use client";

/**
 * Cache de sessão das consolidações. A leitura autenticada de atribuições
 * reidrata responsável e etapas do servidor após reload e resposta ao convite.
 * A autorização definitiva continua no backend.
 */
import { useSyncExternalStore } from "react";

import type { DecisionVinculo } from "./consolidacao-api";

export interface SessionConsolidation {
  consolidacaoId: string;
  pessoaId: string;
  responsavelId: string | null;
  prazoConexao: string | null;
  vinculo: DecisionVinculo;
  /** Etapas obrigatórias confirmadas nesta sessão. */
  confirmedStages: string[];
  concluida: boolean;
}

const store = new Map<string, SessionConsolidation>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version += 1;
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

function getSnapshot(): number {
  return version;
}

/** Insere/atualiza a consolidação de uma pessoa (ex.: ao lançar decisão). */
export function upsertConsolidation(entry: SessionConsolidation): void {
  store.set(entry.pessoaId, entry);
  emit();
}

/** Aplica um patch parcial à consolidação de uma pessoa, se existir. */
export function patchConsolidation(
  pessoaId: string,
  patch: Partial<SessionConsolidation>,
): void {
  const current = store.get(pessoaId);
  if (!current) return;
  store.set(pessoaId, { ...current, ...patch });
  emit();
}

/** Lê a consolidação conhecida de uma pessoa (ou undefined). */
export function getConsolidation(pessoaId: string): SessionConsolidation | undefined {
  return store.get(pessoaId);
}

/**
 * Assina o store. Retorna um contador de versão; os componentes leem os dados
 * via getConsolidation no render (re-render disparado a cada mudança).
 */
export function useConsolidationStore(): number {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
