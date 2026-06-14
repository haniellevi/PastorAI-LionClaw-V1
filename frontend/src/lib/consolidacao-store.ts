"use client";

/**
 * Store de sessão das consolidações abertas/atribuídas pelo painel.
 *
 * O backend não expõe um GET de consolidações com o consolidacaoId e o
 * responsavel_id por pessoa; eles vêm como retorno de api-launch-decision
 * (e de assign-consolidador). Para habilitar a confirmação de etapas
 * (que exige consolidacaoId + gate de identidade), guardamos esse vínculo em
 * memória durante a sessão — keyed por pessoaId — compartilhado entre as telas
 * #consolidar e #consol-individual.
 *
 * É um estado efêmero (não persiste em reload); reflete apenas o que foi
 * lançado/atribuído nesta navegação. A regra de identidade definitiva continua
 * garantida no backend (403/409).
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
