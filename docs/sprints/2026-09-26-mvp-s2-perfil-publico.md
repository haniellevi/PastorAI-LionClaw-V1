# MVP fase 2, S2: perfil público estruturado: 2026-09-26

**Branch:** `feat/public-agent-profile` · **Commits:** `53748bf`, `3ecaf48`, `114facf`, `af58cd0`, `fe544d7` · **Deploy:** nenhum deploy manual por esta missão; CI registra preview automático.

## O que foi feito

- Painel e GET/PUT `/agent/public-profile` permitem ao admin publicar endereço
  institucional, horários e até cinco células públicas por bairro. Tenant vem
  do backend; não há criação de configuração nem ativação do agente. Troca de
  sessão limpa os dados e ignora respostas tardias.
- Migration `20260926_191500_agent_public_profile.sql`: JSONB
  `agent_configs.informacoes_publicas`, default vazio, CHECK de objeto,
  RLS/policies/ACL preservadas e rollback destrutivo apenas comentado.
- As quatro perguntas naturais de culto e consultas de célula por bairro usam
  somente a projeção validada. Bloco legado deixa de fornecer fatos e continua
  retirado do prompt, inclusive com Cf/U+200B. O perfil novo não entra no LLM.
- Tier A recarrega o perfil após HTTP, sob lock curto, revalida configuração e
  recalcula a resposta pública antes do commit, com auditoria sem dados do
  perfil e sem custo LLM. A garantia termina no commit da aplicação.
- Duas threads documentais do robô motivaram este registro, o checklist MVP e
  a restauração de `PRD-COVERAGE.md`, pois o domínio continua Parcial.

## Decisões

- **Sem backfill do bloco legado.** O reset previsto do piloto torna esse
  conteúdo anterior irrelevante para a nova configuração; o admin deve
  publicar novamente os campos estruturados. Esta missão não executou reset
  nem assume que ele já tenha ocorrido em produção.
- **Aplicação futura com `lock_timeout` curto, referência de 2 segundos na
  sessão aplicadora.** O default constante dispensa rewrite, mas o ALTER TABLE
  ainda precisa de lock exclusivo. Se houver timeout, abortar e reagendar com
  a sessão operacional, sem espera ilimitada ou retry automático. Este ajuste
  é requisito operacional documentado; não altera o SQL revisado nem executa
  qualquer aplicação de migration nesta missão.
- Revert de código preserva coluna/dados e pode restaurar a fonte legada;
  remoção física exige decisão própria. O filtro de padrões privados não é
  detector geral de PII. Não há consulta privada nem proximidade geográfica.

## Pendente / próximo passo

- **Merge PR423 RETIDO** até liberação explícita coordenada com PastorAI PROD
  operacional e autorização nominal de Raniel. A coluna nova deve estar
  coordenada com o deploy. PASSO A PASSO RANIEL permanece suspenso.
- Sarah GO no head `fe544d7` foi informado pelo usuário, P0/P1/P2=0. O delta
  desta rodada é somente documental; aguarda revisão do delta e CI do novo head.
- S3 foi autorizada em branch nova da main `a5244ca`: identidade/papel com
  confirmação Clerk, ferramentas readonly por papel e Jev B/C/D, conforme plano.
  Provedores reais, DEV/PROD/VPS continuam fora do escopo. O piloto permanece
  interno e o aceite de 20 conversas reais continua pendente.

## Verificação

- Backend: 5.419 testes, zero skips, Python 3.13.14.
- RLS: 340 testes, zero skips, PostgreSQL17.6 descartável; SQL real aplicado
  à baseline sintética, ACL/policies preservadas, SQL/API A/B, CHECK e bloqueio
  observado por `pg_blocking_pids`. Isso não prova grants nem aplicação PROD.
- Frontend: 883 testes, typecheck/build Next15.5.25, Node24.19.0 e seis E2E
  sintéticos em loopback, incluindo desktop/390px e navegação por teclado.
- Terra Max independente: sem P1/P2 nos blobs de código de `af58cd0`.
  `fe544d7` acrescenta só documentação e teve CI7/7 SUCCESS. Este ajuste
  mantém backend/frontend/migration byte-identical ao head aprovado por Sarah.
- Nenhum acesso DEV/PROD/VPS, banco real ou provedor real nesta execução.

[Contrato e uso](../ops/s2-public-agent-profile-20260926/README.md),
[validação detalhada](../ops/s2-public-agent-profile-20260926/VALIDATION.md) e
[plano S1/S2/S3](../ops/mvp-fase2-agente-inteligente-plano.md).
