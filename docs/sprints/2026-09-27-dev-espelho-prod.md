# DEV recriado como espelho do schema de PROD, com o mesmo ledger — 2026-09-27

**Branch:** `ops/dev-espelho-prod-20260927` (base `148007f`, da branch `docs/prod-sessao-a-b-20260926`) · **Commits:** `2b474e8`, `036c479`, `d9793ed`, `e9bc854` e este registro · **Deploy:** nenhum. Escrita só no banco do DEV (Supabase `cxmjojnocigekgcxhubi`), com "ok" do Raniel antes de cada passo; PROD só leitura.

Fase 0 do plano do MVP, item "Reconciliar ou recriar o DEV": pré-requisito da próxima
migration em PROD (decisão do Raniel, 26/09). Nenhum `.env`, URL de banco ou senha foi
impresso; a URL do DEV não passou pelo chat.

## O que foi feito

- **Acesso ao DEV** por `backend/scripts/dev_db_service.py`: o proprietário cola URL e senha
  sem eco; o script recusa o ref de PROD, exige o ref do DEV e grava o serviço libpq
  `pastorai_dev` em `~/.config/pastorai/` (0600). Uso: `PGSERVICEFILE=~/.config/pastorai/pg_service.conf`
  com `psql service=pastorai_dev` ou `MIGRATION_DATABASE_URL=service=pastorai_dev`.
- **DEV antes (só leitura, 11:21–13:43 UTC):** PostgreSQL 17.6; 55 tabelas, 11 funções e 31 enums
  em `public`; ledger antigo `(name, applied_at)` com 33 linhas (`migrate.py status` 33/78/45);
  ledger nativo com 6 linhas, inclusive a d1a (28/08). Pelas 243 checagens, faltavam
  `20260705_120600` (parte), `20260824_180000` e `20260826_030508`; sobrava a d1a; sem
  `ensure_rls`. Dados: 1 igreja, 10 logins, 4 pessoas, 1 conversa, nenhum arquivo no Storage.
- **Leitura de PROD (só leitura)** pela VPS às 13:14 UTC, com chave temporária desta sessão
  (`restrict`, expiração em 28/09 06:00 UTC) e host key igual à de 26/09. `ler_prod_na_vps.sh`
  usa o helper do backup (sha256 igual ao do repo, `e088bbeb…`), `pg_dump --schema-only` 17.10 e o
  kit. Encontrado: ledger com 70 linhas (63 PROVA_OBJETO, 6 BASELINE_V1_HISTORICO, 1 MIGRATE_PY =
  S2), md5 `name:origem` `dd161e3863956b19baf220ca5f3cf991`; 243 checagens iguais às de 26/09; S2
  3/3; `ensure_rls` do `postgres`, tags CREATE TABLE/CREATE TABLE AS/SELECT INTO, função
  `6998ea6b…`; default privileges, ACL do schema `public`, extensões e os outros 6 event triggers
  iguais aos do DEV; schema `recovery` só em PROD. Depois: pastas temporárias e a chave desta
  sessão removidas (7 → 6 chaves do root; nova tentativa recusada). A chave de 26/09 já não
  estava lá.
- **Kit** `docs/ops/dev-espelho-prod-20260927/` (ver o README): inventário, fingerprint objeto a
  objeto, lista do ledger, checagens da S2, leitura na VPS, gerador da recriação, guarda dos
  logins e semente.
- **Ensaios** em Supabase 17.6 local descartável (`supabase/postgres:17.6.1.159`; PROD simulado com
  as 70 migrations, DEV simulado com 67 + ledger antigo de 33). Com o dump real de PROD:
  fingerprint igual em 1.173 objetos, `pg_dump` idêntico (6.494 linhas), checagens iguais exceto
  `c02_credentials_backup`, `migrate.py status` 70/78/8. Recusas: rodar de novo, rodar contra
  PROD e DEV alterado depois da inspeção (trava); fingerprint divergente → ROLLBACK com o DEV
  intacto. Opção (a) e semente ensaiadas de ponta a ponta.
- **Achado:** 3 funções de PROD (`current_igreja_id()`, `trg_celula_solicitacao_evento_append_only()`
  e `trg_pessoa_arquivamento_evento_append_only()`) têm `\r\n` no corpo (30 linhas no dump); os
  arquivos do repo não têm. A 1ª versão do gerador convertia as quebras e a conferência pegou
  (ROLLBACK no ensaio). O gerador passou a ler e gravar bytes.
- **Sarah:** GO só para o passo 6 sobre `recriar_dev_20260927.sql` (sha256
  `01605becfdb19d7405bb4c60e292b55c6e8d9a7db6e6e44889149623bbac9fb3`), P0=0, P1=0, 8 P2
  (tratamento abaixo). Ela regerou o artefato a partir das entradas e obteve os mesmos bytes, salvo
  data e chave do `\restrict`, e rodou 24 controles negativos no gerador.
- **Execução no DEV**, com "ok para A":
  - backup `~/.local/share/pastorai/backups/dev-public-antes-espelho-20260927T154103Z.dump`
    (sha256 `8976afce…`, 0600, fora do git);
  - logins guardados às 15:41 UTC (10 logins, 2 admins de plataforma);
  - recriação 15:41:57–15:44:04 UTC: COMMIT, "1173 objetos de public conferidos", nenhuma
    diferença, nem de plataforma;
  - semente às 18:04 UTC ("sim"): 1 igreja fictícia, 10 logins, 10 papéis, 2 admins, 3 planos e
    30 permissões; schema temporário apagado.

## Decisões

- **Recriar em vez de reconciliar as 45 pendentes:** o DEV tinha objetos fora do ledger e a d1a,
  que o PROD não tem. O dump garante a igualdade por construção, e a prova é fingerprint + dump +
  243 checagens.
- **Schema `public`, sua ACL e comentário e os default privileges não são copiados:** são geridos
  pelo Supabase, e os de `supabase_admin` o `postgres` nem consegue definir. Foram conferidos
  iguais antes (fingerprint do DEV às 13:43 UTC) e de novo depois.
- **Zerar os grants dos default privileges na criação e aplicar só as ACLs do dump:** sem isso,
  `anon` e `authenticated` ganhariam ALL no ledger e nas tabelas fechadas.
- **`ensure_rls` recriado no DEV** pelo `postgres` (o supautils permite), igual ao do PROD.
- **Ledger do DEV** com as mesmas 70 linhas e origens do PROD; `applied_at` = data da cópia no
  DEV. O comentário da tabela é o do PROD (faz parte da planta).
- **Semente** = dados fictícios que as 70 migrations criam num banco vazio ("Igreja Piloto
  PastorAI") + as contas de teste do proprietário que já estavam no DEV. O login com o id do
  Pastor Piloto foi fundido a ele e manteve os papéis que tinha. O tenant vem de
  `app_users.clerk_user_id`, então os logins funcionam sem mexer no Clerk.
- **Aceito pelo proprietário** (aviso antes do "ok para A"): o DEV perdeu os dados de teste
  anteriores e as 5 travas da d1a (P2-4 da Sarah); a d1a segue pendente com gate próprio.
- **`sslmode=require` no serviço do DEV** (P2-5): mantido (credencial de DEV na máquina do
  proprietário, trava no SQL); `verify-full` com a CA do Supabase fica como melhoria.

## Pendente / próximo passo

- Proprietário: entrar no DEV com as contas de teste; reconectar o WhatsApp de teste do DEV, se
  houver; decidir quando apagar o backup local do DEV.
- PR de follow-up: `--lock-timeout` no `backend/scripts/migrate.py` (`SET LOCAL` na mesma
  transação do apply; o pooler ignora `PGOPTIONS`). Depois, `20260926_120446_platform_jev_settings`:
  DEV primeiro, então PROD com backup, Sarah e "ok".
- Enviar esta branch ao GitHub e abrir o PR (inclui o commit `148007f` de 26/09, ainda local).
- Diferenças deliberadas que ficam: schema `recovery` só em PROD;
  `supabase_migrations.schema_migrations` (DEV 6, PROD 32), só histórico; `applied_at` do ledger.

## Verificação

- Leitura de PROD (`SHA256SUMS` conferido): dump `99e47dbc…`, fingerprint `c3991162…`, ledger
  `14533c5e…`, prova `2a4cd2ba…`, prova_s2 `2d55c948…`, inventário `fee08bc6…`.
- Depois da recriação e de novo depois da semente, só leitura: fingerprint do DEV idêntico ao de
  PROD no arquivo inteiro (1.199 linhas, inclusive plataforma); `pg_dump --schema-only` do DEV
  idêntico ao de PROD (6.494 linhas, com os 30 `\r`); 246 checagens iguais exceto
  `c02_credentials_backup`; `migrate.py status` = 70 aplicadas, 78 arquivos, as mesmas 8 pendentes
  do PROD; ledger 70 linhas, md5 `dd161e38…`, `anon`/`authenticated` sem privilégio, RLS sem
  FORCE, 0 policy; estado de `public` 283/`73634fad…`, igual ao do PROD.
- P2 da Sarah: P2-1, registros dos três negativos gravados; P2-2, fingerprint do DEV conferido
  antes (schema, default_acl e plataforma iguais, exceto `ensure_rls`); P2-3, backup; P2-4,
  aceito; P2-5, documentado; P2-6, `036c479`; P2-7, commits `2b474e8` em diante; P2-8, plano
  atualizado (45 pendentes = 44 + a S2).
