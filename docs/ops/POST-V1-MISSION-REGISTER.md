# PastorAI / Igreja 12 — registro central de missões pós-V1

Atualizado em 2026-08-23 (America/Sao_Paulo) após validação de produção da PR #279 e checagens de integridade prévias. A V1 permanece
`V1_ENCERRADA`; este documento não altera a tag `v1.0.0` nem autoriza ativação
de integrações externas.

## Baseline obrigatório

- código V1 em produção: `903394fe0e36a3aad450bf11eee732f7e4e0d77c`;
- frontend (Vercel): `pastorai-frontend-prod` com SHA `903394fe0e36a3aad450bf11eee732f7e4e0d77c`;
- Supabase PROD: `pffafnchtxbimpwyaczq`;
- Clerk: estado a confirmar (verificação de instância PROD pendente).
- flags externas: Asaas real, broadcast e Brevo live fechados;
- fonte de verdade: `origin/main` atualizado.

## Missões

1. **PR #257 — fluxo da Central de Células.**
   - Motivo: a PR permanecia aberta e não pertenceu ao fechamento da V1.
   - Estado: **MERGED** em `bae285b...` (squash merge a partir do HEAD
     `b969c9a1de170d9c48e0729a9f867e2c95bb9232`); 5/5 checks do GitHub Actions
     verdes e validações locais (793 testes, typecheck, lint, build e 5 E2E)
     executados com sucesso.
   - Evidência: aba "Hoje" exibe fila de exceções prioritárias sem duplicar
     contagem de multiplicações; totais da igreja permanecem acessíveis via
     `details` colapsível.

2. **Células — transferência/remoção de membros.**
   - Motivo: capacidade explicitamente excluída da V1.
   - Estado: **MISSÃO 2 CONCLUÍDA e DEPLOYADA em produção** no SHA
     `903394fe0e36a3aad450bf11eee732f7e4e0d77c`.
   - Evidência: rota `/cells/{cell_id}/membros/transferir` e
     `/cells/{cell_id}/membros/remover` ativas no OpenAPI de produção; produção
     do frontend em Vercel no commit acima.

3. **Clerk Production.**
   - Motivo: retirar o piloto da instância DEV antes de abertura pública.
   - Estado: **BLOCKED** no escopo de verificação atual.
   - Bloqueios: não foi possível extrair prova técnica não-confidencial de
     `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` em produção pelo pipeline disponível,
     nem validar `CLERK_SECRET_KEY` / `CLERK_JWT_ISSUER` no VPS a partir desta
     sessão.
   - Ação seguinte obrigatória: obter evidência de prefixo `pk_live_` e issuer/JWKS
     de produção, seguido de smoke completo por perfil (master, admin/pastor,
     líder, membro).

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

## Ativação pós-deploy PR #279 (2026-08-23)

Revalidação de produção realizada nesta sessão:

- **FRONTEND_SHA**: `903394fe0e36a3aad450bf11eee732f7e4e0d77c` (redeploy Vercel production: `https://pastorai-frontend-prod-mc2wlzp16-raniel-levis-projects.vercel.app`, alias `https://pastorai-frontend-prod.vercel.app`).
- **BACKEND_SHA**: `903394fe0e36a3aad450bf11eee732f7e4e0d77c` (OpenAPI em `https://api.igreja12.com.br` com `/cells/{cell_id}/membros/transferir` e `/cells/{cell_id}/membros/remover`).
- **Artefatos sensíveis**: nenhum encontrado no worktree; padrões de exclusão (`clerk_*_prod.*`, `migrate_clerk_production.py`, `target_users*.json`) já estão em `.git/info/exclude`.
- **Vercel env (production)**: adicionada `NEXT_PUBLIC_API_URL=https://api.igreja12.com.br` (não-sensível, target `production`) e reimplantado. Confirmação: os chunks do novo deploy contêm `api.igreja12.com.br` e não contêm `localhost:8000`.
- **Clerk no frontend**: não aplicável — o frontend não utiliza Clerk (`@clerk/nextjs` não consta em `package.json`, nenhum `pk_` nos chunks). A verificação de `CLERK_SECRET_KEY`/`CLERK_JWT_ISSUER` no VPS não foi possível por falta de acesso SSH à instância `76.13.234.127`.
- **Status**: **BLOCKED** — o próximo gate é obter acesso SSH ao VPS `76.13.234.127` (ou a saída redigida do comando `grep -E 'CLERK_SECRET_KEY|CLERK_JWT_ISSUER|CLERK_JWKS_URL' /opt/pastorai-current/.env`) para confirmar que a instância Clerk é PROD, seguido de smoke por perfil.

## Paralelismo seguro

Auditorias read-only de PR #257, recuperação de Células e desenho de Clerk
Production podem ocorrer em sessões separadas. Migrations, mudanças de
identidade, flags, canários, deploys e merges continuam estritamente seriais e
exigem preflight vivo no momento da ação.
