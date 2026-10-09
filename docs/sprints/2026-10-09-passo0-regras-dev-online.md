# Passo 0: regras únicas, plano consolidado e acompanhamento — 2026-10-09

**Branch:** `docs/passo0-regras-dev-online`  ·  **PR:** #461  ·  **Deploy:** não

## O que foi feito
- `AGENTS.md` como fonte única de regras; `CLAUDE.md` passa a importá-lo e só
  acrescenta orientações do Claude.
- `AGENTS.md`: autonomia para iteração reversível com dados sintéticos; o DEV
  online é o alvo para a validação integrada, descrito como planejado até existir.
- Plano MVP: removida a exigência de plano aprovado por conselheiros, Sarah e
  autorização nominal por item (contradizia o §3.1); registrada a decisão de
  08/10 (Neon cancelado, DEV online planejado) no §3.5 e no §5.
- `sarah.md`: escopo restrito a autenticação/RLS e migrations de produção.
- [`docs/ops/refatoracao-modular-plano.md`](../ops/refatoracao-modular-plano.md)
  substituído pelo plano consolidado de 09/10: sequência única, critérios de
  aceite, limites de validação e apêndice das propostas retiradas. É a única
  fonte técnica versionada; o plano anterior deste PR ficou no histórico do Git.
- Acompanhamento visual em [`docs/ops/acompanhamento/`](../ops/acompanhamento/README.md):
  `tarefas.json` (registro), painel estático (`painel.html`) e `./acompanhar.sh`.
  Procedimento curto registrado em `AGENTS.md`.

## Decisões
- Primeira fatia de código: simulador de WhatsApp com modo
  `WHATSAPP_TRANSPORTE=simulado`, sem ligar `ALLOW_REAL_SENDS` (PR #462, com
  correções pendentes descritas no plano, F2a).
- A extração de ações do agente fica adiada até haver capacidade concreta; a
  primeira extração de domínio é só a validação do visitante (F1).
- `npm audit --omit=dev` aprovado não significa ausência de vulnerabilidades no
  grafo completo; a triagem das altas restantes é tarefa separada (S4).
- O painel só mostra o que está em `tarefas.json` e `github.json`; não há
  percentual de esforço nem prazo.

## Pendente / próximo passo
- Integração do #463 (dependências) pelo proprietário. Depois, atualizar a base
  deste PR e revalidar os quatro checks: hoje `backend-tests` e `frontend-ci`
  reprovam nos audits de dependências herdadas da `main`.
- Em seguida, na ordem do plano: `test-local.sh` rejeitar alvo desconhecido,
  correções do #462, F1, F2b, F3, F4 e F5.
- Triagem do Production monitor (falha contínua desde 03/10), fora da sequência.
- Resíduo Neon no guia local não rastreado `CONFIGURACAO-DESENVOLVIMENTO.md:125`
  (arquivo do proprietário, fora do Git).

## Verificação
- Mudança só de documentação e ferramenta de acompanhamento. O painel foi aberto
  no navegador (abas, filtros, detalhes, links, desktop e celular) e a falha
  simulada do GitHub preservou a última evidência como desatualizada.
- Os quatro checks do PR ainda não valem como prova: dependem da base nova (#463).
