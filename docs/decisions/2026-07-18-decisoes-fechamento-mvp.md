# Decisoes do dono - Fechamento do MVP - 2026-07-18

**Baseline:** `origin/main` = `fcdb81c` (pos PR#188/#189)
**Processo:** sessao de decisoes M8 do plano de fechamento; cada tema investigado no
codigo antes da pergunta; respostas do dono registradas abaixo com alternativas
rejeitadas e desdobramento.

## Decisao 1 - Re-opt-in de comunicacoes (opt-out do WhatsApp)

- **Contexto:** opt-out marca `pessoas.optout=true` (agente silencia, broadcast exclui);
  nao existia nenhum caminho de volta (nenhum endpoint seta `optout=false`).
- **Decisao:** criar botao administrativo "Reativar comunicacoes" na ficha da pessoa,
  restrito a admin/pastor, registrando novo consentimento (data/versao do termo) e quem
  reativou.
- **Rejeitadas:** reativacao automatica por deteccao de intencao na conversa (risco
  LGPD de interpretacao errada; candidata pos-MVP); manter opt-out permanente.
- **Desdobramento:** missao **OPTIN-1** (P, backend+frontend, sem migration).

## Decisao 2 - Comportamento quando a OpenAI falha

- **Contexto:** ja existe fallback deterministico (`_refine_with_llm` retorna None em
  falha e o rascunho do fluxo e enviado; `backend/app/agent/runtime.py:313-330`);
  1 tentativa, sem retry. Ninguem fica sem resposta.
- **Decisao:** manter como esta. Sem retry, sem mudanca de codigo.
- **Rejeitadas:** retry unico antes do fallback (+latencia no WhatsApp); alerta de
  observabilidade dedicado (pode voltar pos-MVP se o fallback frequentar os logs).

## Decisao 3 - Rotulo "Sem interesse (CSIM)" -> "Fora da igreja"

- **Contexto:** comportamento pedido ja existia (pill vermelha, ordenado por ultimo,
  IA pausada via CONV-AI-1, fora da Visao G12); faltava so o nome.
- **Decisao:** renomear o rotulo visivel para "Fora da igreja" em todas as telas;
  valor tecnico interno (`sem_interesse`/`csim`) inalterado.
- **Rejeitadas:** renome parcial (manter CSIM no formulario); manter como esta.
- **Desdobramento:** missao **ROTULO-1** (P, frontend-only, ~10 strings).

## Decisao 4 - Reativacao administrativa de pessoa arquivada

- **Contexto:** existe arquivar (com preflight de vinculos); nao existe desarquivar.
- **Decisao:** criar botao "Reativar pessoa" (admin/pastor) que limpa
  `arquivada_em/motivo` e registra quem reativou e quando.
- **Rejeitadas:** deixar pos-MVP; arquivamento definitivo por politica.
- **Desdobramento:** missao **REATIVAR-1** (P, sem migration - campos ja existem).

## Decisao 5 - Agenda: UX de confirmacao

- **Decisao:** "A confirmar" ordenado por data entra no MVP (**AGENDA-ORD-1**, P
  trivial, frontend). Selecao de destinatarios na confirmacao/edicao do evento vai
  para pos-MVP, junto com a ativacao do envio real de notificacoes (EVT-9).

## Decisao 6 - Propostas estruturais confirmadas como pos-MVP

Ficam registradas como primeiras candidatas do pos-MVP (modulos novos - bons
candidatos a pipeline Development 2.0 do LionClaw):

- Arvore ministerial configuravel (pastor/pastora/casal; ate 12 posicoes por lideranca;
  membro do G12 podendo ou nao liderar celula).
- Novo lider dependente de aptidao + lider superior + celula + aprovacao da Central,
  com estado "lider em atualizacao" durante a aprovacao.
- Convite de celula distinguindo membro e visitante.
- Plano da igreja selecionado pela administracao da plataforma + contratacao/assinatura
  via Asaas.
- Guia interativo de configuracao da igreja.
- Reativacao automatica de opt-out por intencao (ver Decisao 1).
- Selecao de destinatarios de evento (ver Decisao 5).

## Resumo executivo

| Missao nova | Tamanho | Camada | Migration |
|---|---|---|---|
| OPTIN-1 (re-opt-in admin) | P | backend+frontend | nao |
| REATIVAR-1 (desarquivar admin) | P | backend+frontend | nao |
| ROTULO-1 (Fora da igreja) | P | frontend | nao |
| AGENDA-ORD-1 (A confirmar por data) | P | frontend | nao |

As 4 sao codigo puro auto-verificavel - aptas ao mesmo formato de pipeline LionClaw
usado no fechamento FECH-01..04 (PR#188). Nenhuma outra decisao segue bloqueando
missoes do MVP.
