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

O primeiro CI do #473 identificou um teste antigo que congelava a posição textual do comando de build. O teste passou a executar o gate em fixtures locais, nos modos padrão e por digest, comprovando que envio aberto impede build, saúde e troca do link. Não remove a proteção nem lê configuração real. As fixtures também isolam inputs de release/Docker herdados do host. A prova do head corrigido permanece separada da anterior.


## Integração sequencial autorizada em 10/10

O proprietário autorizou nominalmente #462 e #465 a #473 e o efeito automático do frontend. Os nove PRs abaixo foram integrados na main após atualizar cada base, preservar a árvore da fatia e revalidar CI do novo head e da main antecessora. #473 ainda precisa validar este registro e integrar; não foi antecipado seu resultado.

| PR | Head validado | Commit de merge na main |
|---|---|---|
| #462 | c5e9af5e467012f0db83596fb17397e21f4de0ab | 6babdf2a6d2812f1185777486060675db60ab36a |
| #465 | ae5161f648d99460afb0e9744c588d6c92dc5d9d | 2ef4f57d61b8fef448125613cf5cba85e59c1796 |
| #466 | 27597b430ab3c3e1091f531c1f34ebcd5f13c5d6 | fa60df7687d2efa8c37f0a6ea8acff83213c9ebc |
| #467 | dcc53f2a1e06b366b2417df55d6a78099bfc9896 | 2ce15bd35a18fdd3848aa7408a647827d0058c1f |
| #468 | 0cb6b9911283a52ec964eba6f5523e97d510820e | 94743953b22944cb23945339a53ba26e6b8055fd |
| #469 | 006804dd48b5d2548b285a1a94e541305288bd9c | c0c273cf559e441dacaf8856476034b07134aef9 |
| #470 | 47071289c4575a651b40f2c9b7799317fd16c394 | 52622a5e2310e0009c9a95223851ac5ddf8fe7ac |
| #471 | 75221bdc2f08997dbada9b1485b6ee22a7715a12 | d818e59514d9eb3726e4836a1976647463d94016 |
| #472 | 2c6369a8486ae8c711f8b7bc71c3793cd53d9f94 | 2076528998f9b6d6bb66219861d88586cdf27d4c |

tarefas.json e o checklist sintético do MVP refletem as integrações comprovadas. T09/T10 mantêm aceite online pendente; T08/T11 e operações reais continuam sujeitos à decisão e autorização concretas. Este registro não comprova publicação frontend sem recibo próprio, nem release backend, schema remoto ou causa da indisponibilidade histórica.
