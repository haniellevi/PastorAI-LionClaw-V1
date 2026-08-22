# PastorAI / Igreja 12 — registro central de missões pós-V1

Atualizado em 2026-08-22 (America/Sao_Paulo). A V1 permanece
`V1_ENCERRADA`; este documento não altera a tag `v1.0.0` nem autoriza ativação
de integrações externas.

## Baseline obrigatório

- código V1 em produção: `281e69c2fef80cfbcb27eab5ca4f85981e4adc0c`;
- frontend: `dpl_CdwTcTE8HZHvxs9t92Ak6sHxebAp`;
- Supabase PROD: `pffafnchtxbimpwyaczq`;
- Clerk: instância DEV restrita ao piloto;
- flags externas: Asaas real, broadcast e Brevo live fechados;
- fonte de verdade: `origin/main` atualizado e worktree limpo por missão.

## Missões

1. **PR #257 — fluxo da Central de Células.**
   - Motivo: a PR permanece aberta e não pertenceu ao fechamento da V1.
   - Estado: não draft; HEAD `bbd331f...`; no preflight estava 87 commits atrás
     e 1 à frente de `main`.
   - Pré-requisito: atualizar em worktree isolado, revisar contra o RBAC final
     da PR #271 e repetir frontend, backend relevante e smokes por papel.

2. **Células — transferência/remoção de membros.**
   - Motivo: capacidade explicitamente excluída da V1.
   - Estado: a referência histórica `05c0aad...` não existe no clone nem no
     GitHub; a recuperação ainda não é comprovada.
   - Pré-requisito: localizar a origem que possua o objeto/arquivos ou
     reconstruir a mudança a partir da especificação, antes de revisar código.

3. **Clerk Production.**
   - Motivo: retirar o piloto da instância DEV antes de abertura pública.
   - Pré-requisito: mapear identidades, criar backup e rollback dos seis
     vínculos, trocar secret/publishable/issuer/JWKS como conjunto e repetir os
     smokes de administrador, pastor, líder, membro e master.

4. **Asaas real.**
   - Motivo: habilitar cobrança apenas depois da validação comercial e
     financeira.
   - Pré-requisito: inventário das assinaturas, backup fresco, reconciliação,
     canário financeiro isolado e autorização nominal para abrir
     `ALLOW_REAL_SENDS` e `ASAAS_BILLING_ENABLED`.

5. **Broadcast assíncrono e envios Evolution.**
   - Motivo: o worker está implantado, mas deliberadamente ocioso na V1.
   - Pré-requisito: Evolution saudável, heartbeat do worker, destinatário único
     autorizado, observabilidade e rollback antes de abrir os dois gates.

6. **Brevo live.**
   - Motivo: a V1 comprovou apenas um canário e retornou a `off`.
   - Pré-requisito: domínio/remetente, monitoramento, novo canário autorizado e
     promoção separada para `live`, recriando todos os consumidores da flag.

7. **Dívida de performance do Supabase.**
   - Motivo: o advisor reporta 75 recomendações `INFO` — 51 FKs sem índice de
     cobertura e 24 índices ainda sem uso.
   - Pré-requisito: medir consultas e crescimento real antes de criar ou remover
     índices. O `WARN` de `current_igreja_id()` continua aceito enquanto for
     necessário às policies RLS.

## Paralelismo seguro

Auditorias read-only de PR #257, recuperação de Células e desenho de Clerk
Production podem ocorrer em sessões separadas. Migrations, mudanças de
identidade, flags, canários, deploys e merges continuam estritamente seriais e
exigem preflight vivo no momento da ação.
