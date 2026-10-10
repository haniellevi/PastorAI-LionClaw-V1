# Conclusão do desenvolvimento da refatoração

## Resultado e limites

O desenvolvimento planejado das fatias F1/F2a/F2b/F3/F4/F5 está implementado em candidatos publicados. Isso não fecha o aceite operacional do plano: merges, recursos/aceite DEV e release PROD permanecem pendentes. Nenhum acesso novo à VPS/Supabase, migration remota, alteração Vercel, envio, cobrança ou limpeza de worktree alheia foi realizado. Backlogs B1-B6 continuam condicionados a uma necessidade concreta.

Base integrada: `52286af7c78a8bf9c0fcc7e0e205ac0226cf7dd1`. Worktree Codex própria; checkout principal e duas worktrees Claude preservados. As notas de 09/10 sobre preparação parcial e ausência de push descrevem a etapa anterior; esta sprint registra o avanço posterior.

## Candidatos e ordem de integração

| PR | Fatia | Head publicado da fatia | Base temporária |
|---|---|---|---|
| #462 | T05: destinos, fake e gates | c5e9af5e | main |
| #465 | T06: domínio visitante | d71ea700 | feat/simulador-whatsapp |
| #466 | T07: PG/RLS/Redis e turno | a0c42673 | codex/t06-dominio-visitante |
| #467 | T12: leitura da resposta | e6e34f15 | codex/t07-integracao-real |
| #468 | T09: imagem allowlist | 2bd656b3 | codex/t12-leitura-resposta |
| #469 | S3: Next patch | a6956868 | codex/t09-imagem-guardada |
| #470 | S4: ferramentas auditadas | 9b3fd41e | codex/s3-next-patch |
| #471 | T09: pipeline físico DEV | 0b4fbd6a | codex/s4-ferramentas-auditadas |
| #472 | T10: compatibilidade e registro final | conferir head final no GitHub | codex/t09-dev-pipeline |

| #473 | T10: promoção por digest | conferir head final no GitHub | codex/t10-compat-release |

Todos os links usam `https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/NUMERO`. #465 a #473 são drafts. Não integrar na base temporária. Após integração autorizada de cada antecessor, mudar a base da próxima fatia para main, conferir o diff e revalidar o head final. Aprovação em base temporária não comprova aprovação no novo merge candidate.

## Provas locais

Regressão anterior: 6443 testes backend offline; 874 integrações PG/RLS/Redis, zero skips, mais dois testes novos PG separados e uma prova adicional de compatibilidade. Frontend: 1165 testes, 69 E2E Chromium, lint, tipos, build e headers aprovados. Python 3.13.14 e Node 24.19.0. Não somar execuções diferentes como uma execução única.

O executor físico foi ensaiado no SHA `bbf52f2d0d4b429af9f6f7d2f434d6e1d4e20e56`, com duas imagens desse SHA:

- Backend local: `sha256:f25a64e467f147007ab0b2e48aed2c79efcccc9c1cb62e91f9c35a6cff0fc439`.
- Frontend local: `sha256:068d0c37a048a67cc3078e0a8322ef5e728773c39ff187be24de8c7b699a009a`.
- Catálogo independente: `0e6b1b8f8c6d51fe394b743c627f8be2ce88af440155cd2c00bb1bf5e4533685`.

Esses IDs são imagens locais, não prova de publicação no GHCR. PASS em migrations reconstruídas num PG17 independente, prontidão de processos, HTTP/headers frontend, fila Redis persistente, contenção após falha de troca, recuperação com schema aditivo, reset sintético, invalidação de reserva pendente e preservação de aceite concluído. API, frontend e três workers executam em processos separados, rede interna sem egress. Todos os containers/volumes exclusivos desse ensaio foram removidos.

Compatibilidade do release: 86 testes de release/controller/coordenação com 59 subtests aprovados; dois testes PG17 novos aprovados, zero skips. Bundle exige SHA/hash revisados e catálogo/ledger exatos, identidade e TLS nominal; não aceita extras indiscriminadamente. Imagem/ENV isolados não provam procedência do release vivo. Frontend/Clerk/Storage online e recuperação de dados reais precisam de aceite no alvo autorizado.

Painel: recusa chamar de integração na main um merge em base temporária ou desconhecida. As três novas variantes desse comportamento, os testes do executor/coordenação e o contrato de actions passaram: 38 testes focados. Registo validado: 22 tarefas, 11 fases, zero avisos.

## CI e audits

#462 e #465 a #470 passaram nos quatro checks obrigatórios nos heads acima. O primeiro backend-tests de #471 falhou no contrato das actions: SHAs corretos, comentários de versão ausentes nos workflows novos. Commit `71355ea2` acrescenta as versões revisadas; três testes do contrato passaram. A correção também foi incorporada ao #472. Os checks dos novos heads são prova separada e precisam terminar antes da integração. O ensaio físico do primeiro #472 passou no GitHub.

Pip-audit dos dois locks sem vulnerabilidades conhecidas. Audit npm de produção limpo. Reconsulta do grafo completo em 10/10 mantém cinco alertas altos de ferramentas de desenvolvimento, derivados de `GHSA-vfj7-8cjw-p6xm` (braces). O reparo automático sugere downgrade major de eslint-config-next; não foi aplicado. O aviso permanece explícito, sem desligar gate ou alegar zero vulnerabilidades no grafo completo.

## Próximas operações

Decisão T08: executor exclusivo, região/teto e verificação nominal do projeto DEV. O workflow online está desativado por padrão. Depois de integrar e revalidar os candidatos, provisionar/configurar somente com autorização; executar login, duas igrejas e fluxo de produto online antes do aceite. T11 continua uma operação própria: preflight vivo, versão anterior comprovada, bundle de compatibilidade revisado, backup restaurável, consumidores contidos e publicação coordenada autorizada. S1 mantém hipótese histórica sem causa nova provada nesta execução.

Guias: [pipeline DEV](../ops/DEV-PIPELINE-SINTETICO.md), [compatibilidade](../ops/COMPATIBILIDADE-RELEASE-REVISADA.md) e [plano](../ops/refatoracao-modular-plano.md).


## Correção do isolamento observada no CI final

Os checks RLS dos candidatos 71355ea2/d25ccd3c apontaram um erro na preparação do teste de seed: service_role já existia no cluster compartilhado sem BYPASSRLS. A fixture criava somente papéis ausentes e herdava essa configuração, fazendo a migration M06 recusar o bootstrap. O commit 0b4fbd6a normaliza os três papéis exclusivamente no cluster loopback rls_disposable, mantendo anon/authenticated NOBYPASSRLS e service_role BYPASSRLS. A migration e os guards permanecem inalterados.

Regressão nova reproduz papel pré-existente sem bypass, aplica as migrations ativas e confere os três atributos reais. Seed e regressão passaram em PG17 descartável: 2 passed, zero skips. O ensaio físico e todos os outros checks dos candidatos anteriores passaram; o CI dos heads corrigidos é uma prova nova, a conferir antes da integração. Não usar os resultados anteriores como aprovação do head novo.

## Fechamento da promoção por artefato

A revisão final identificou que o release legado ainda recompilava no alvo. O modo opcional RELEASE_IMAGE_REF agora promove referência nominal por digest, valida SHA/IDs, conserva a imagem anterior real para recuperação e recusa imagens inconsistentes. Contenção verifica estado parado; criação não faz build/pull; gates são conferidos antes de iniciar. Lock e reconfirmação do link impedem releases concorrentes neste modo. Pinagem pública persiste no candidato saudável, preservando a configuração privada e futuras operações Compose. O modo padrão permanece compatível, sem alegar promoção imutável.

Testes do release e parser Compose real: 62 passed e 65 subtests passed. Incluem retorno sem build, tag/SHA/repository recusados, imagem e contenção divergentes, lock e preservação do checker/gates. O código e o runbook estão preparados; aquisição/publicação da imagem production, janela do banco, frontend/Vercel e operação do alvo real continuam sujeitos ao pacote concreto autorizado. Os candidatos #471 0b4fbd6a e #472 cb87b174 passaram nos quatro checks e no ensaio físico no GitHub.
