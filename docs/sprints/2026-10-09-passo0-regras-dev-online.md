# Passo 0: regras únicas, plano consolidado e acompanhamento — 2026-10-09

> Registro histórico de 09/10: comandos e procedimentos abaixo descrevem aquela
> entrega. O planejamento ativo está em [ROADMAP.md](../../ROADMAP.md); o painel
> e os planos citados estão preservados nos links com SHA fixo.

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
- [`docs/ops/refatoracao-modular-plano.md` histórico](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/refatoracao-modular-plano.md)
  substituído pelo plano consolidado de 09/10: sequência única, critérios de
  aceite, limites de validação e apêndice das propostas retiradas. É a única
  fonte técnica versionada; o plano anterior deste PR ficou no histórico do Git.
- O [acompanhamento visual da época](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/acompanhamento/README.md)
  usava `tarefas.json` como registro, um painel estático (`painel.html`) e um
  comando hoje aposentado. O planejamento atual fica no [ROADMAP](../../ROADMAP.md).
- Mod do Claude Code ([arquivo histórico](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/acompanhamento/mod/hooks/register.js), comandos `/plano` e
  `/plano-faixa`): pipeline e barras de progresso dentro do Claude Code, lendo
  `dados.js`. Não carrega com `disableAllHooks` ligado.

## Decisões
- Primeira fatia de código: simulador de WhatsApp com modo
  `WHATSAPP_TRANSPORTE=simulado`, sem ligar `ALLOW_REAL_SENDS` (PR #462, com
  correções pendentes descritas no plano, F2a).
- A extração de ações do agente fica adiada até haver capacidade concreta; a
  primeira extração de domínio é só a validação do visitante (F1).
- `npm audit --omit=dev` aprovado não significa ausência de vulnerabilidades no
  grafo completo; a triagem das altas restantes é tarefa separada (S4).
- O painel da época mostrava `tarefas.json` e a última leitura do GitHub
  (`github.json`, gerado localmente). O painel não mostrava percentual de esforço nem prazo.
- `dados.js` e `github.json` ficavam fora do Git. Em um checkout novo, o
  modo offline gerava o painel com um aviso quando faltavam dados do GitHub.

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
