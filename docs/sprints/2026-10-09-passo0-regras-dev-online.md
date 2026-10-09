# Passo 0: regras únicas e DEV online — 2026-10-09

**Branch:** `docs/passo0-regras-dev-online`  ·  **Commits:** neste PR  ·  **Deploy:** não

## O que foi feito
- Diagnóstico, arquitetura alvo, DEV/PROD e fatias versionados em
  [`docs/ops/refatoracao-modular-plano.md`](../ops/refatoracao-modular-plano.md).
- `AGENTS.md` como fonte única de regras; `CLAUDE.md` passa a importá-lo e só
  acrescenta orientações do Claude.
- `AGENTS.md`: autonomia para iteração reversível com dados sintéticos; DEV
  online substitui "só local" como ambiente integrado.
- Plano MVP: removida a exigência de plano aprovado por conselheiros, Sarah e
  autorização nominal por item (contradizia o §3.1); registrada a decisão de
  08/10 (Neon cancelado, DEV online) no §3.5 e no §5.
- `sarah.md`: escopo restrito a autenticação/RLS e migrations de produção.

## Decisões
- Primeira fatia de código: simulador de WhatsApp com modo
  `WHATSAPP_TRANSPORTE=simulado`, sem ligar `ALLOW_REAL_SENDS`.
- A extração de ações do agente começa como refatoração pura (mantém CHECK,
  regras e ativação).

## Pendente / próximo passo
- Fatia 1 (simulador) em PR próprio.
- Local e custo do DEV online antes da Fatia 2.

## Verificação
- Mudança só de documentação e configuração de agente; os quatro checks do PR.
