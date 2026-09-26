# Validação local S2

Candidato de código `af58cd00261073104aee637f2cabfc7d0d6d1a11`, baseado na main
`a5244cad1f0a888b650258bc910f58952c5f2a72`. Ambiente local, 26/09/2026.

| Verificação | Resultado |
|---|---:|
| Backend offline, Python 3.13.14 | 5.419 passaram, zero skips |
| PostgreSQL 17.6 descartável, suíte RLS | 340 passaram, zero skips |
| Frontend, Node 24.19.0 | 883 passaram |
| Typecheck e build, Next 15.5.25 do lockfile | passaram |
| E2E críticos, Playwright 1.62.1, mocks loopback | 6 passaram |

Os arquivos de produção/unitários do backend testados em `114facf` são
idênticos aos de `af58cd0`; o commit seguinte acrescenta somente as provas PG,
incluídas na suíte RLS final. Os oito blobs UI foram conferidos entre o
diretório isolado de teste e o candidato. Nenhuma dependência foi atualizada.

Provas específicas: migration SQL real aplicada à baseline sintética pré-S2;
ACL, RLS/FORCE e policies preservadas; role authenticated não owner e
NOBYPASSRLS; SQL direto e GET/PUT entre duas igrejas; JSONB não objeto rejeitado.
A baseline usa grants sintéticos estabelecidos antes da migration. Isso não
certifica os grants atuais nem aplicação da migration em produção.

No Tier A, edição anterior à aplicação atualiza até o identity map antigo;
edição posterior espera o lock da linha, comprovado por `pg_blocking_pids`.
Limpeza, perfil inválido e mudança de configuração têm testes focais. Auditoria
pública não inclui fatos e esse caminho não cria custo LLM. A garantia termina
no commit do turno: não invalida retroativamente uma resposta já persistida
se o perfil for alterado depois dele.

No painel, salvar/reabrir/limpar foi exercitado em desktop e 390px, incluindo
Tab. Troca de token limpa dados e respostas/erros de GET/PUT antigos não
contaminam a sessão nova. Casos novos passaram por RED/GREEN. Trace sintética
foi inspecionada visualmente; nenhum portal de produção foi operado.

Revisão independente Terra Max em sessão separada: UI e domínio/API/migration
aprovados em `3ecaf48`; runtime e prova PG aprovados em `af58cd0`, sem P1/P2.
As suítes completas acima concluíram a condição de validação desse parecer.
Sarah e CI devem avaliar o head publicado. **Merge S2 continua bloqueado até
liberação explícita coordenada com a sessão PastorAI PROD operacional.**
Não houve acesso DEV/PROD/VPS, provedor real, aplicação compartilhada ou deploy.
