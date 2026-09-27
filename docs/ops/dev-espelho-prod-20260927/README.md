# Kit do espelho DEV = PROD — 27/09/2026

Arquivos usados para recriar o schema `public` do DEV (Supabase `cxmjojnocigekgcxhubi`)
igual ao do PROD, com o mesmo ledger `public.schema_migrations`, sem dados reais.
Registro da execução: [`docs/sprints/2026-09-27-dev-espelho-prod.md`](../../sprints/2026-09-27-dev-espelho-prod.md).
Serve para repetir o espelho se o DEV se afastar do PROD de novo.

| Arquivo | O que é | Efeito no banco |
|---|---|---|
| `inventario_ro.sql` | Identidade, roles, schemas, default privileges, event triggers, extensões, objetos de `public`, impressão do estado (trava), dependências de fora de `public`. Com `-v contar_linhas=1` (só DEV) conta linhas, objetos do Storage e usuários do Auth. | Só leitura. |
| `fingerprint_ro.sql` | Uma linha por objeto de `public` com md5 de tudo o que o define (inclusive ACL normalizada, com grantor, e md5 do comentário), total por seção e total de `public`; seção `plataforma` (event triggers, extensões, publicações) fora do total. | Só leitura; do ledger lê só contagem e md5. |
| `ledger_lista_ro.sql` | `name,origem` do ledger em CSV. | Só leitura. |
| `prova_s2.sql` | 3 checagens de catálogo para `20260926_191500` no formato de `../prod-ledger-20260926/prova_objetos.sql`. | Só leitura. |
| `ler_prod_na_vps.sh` | Na VPS: gera credencial efêmera com o helper do backup, roda `pg_dump --schema-only --schema=public` e os `.sql` acima, devolve um tar pela saída padrão e apaga tudo ao sair. A senha do PROD não sai da VPS. | Só leitura no PROD. |
| `montar_recriacao.py` | Não conecta em banco. Gera a transação única de recriação a partir do dump, do fingerprint e do ledger do PROD e da trava do DEV. Recusa dump com dado, troca de usuário, dono diferente de `postgres` ou tipo inesperado. | — (o SQL gerado escreve no DEV). |
| `guardar_logins_dev.sql` | Opção (a): guarda no DEV, num schema temporário fora de `public`, só o vínculo de login das contas de teste. | Escreve no DEV. |
| `semente_dev.sql` | Passo 7: dados fictícios que as migrations criam num banco vazio ("Igreja Piloto PastorAI") + devolução dos logins guardados; apaga o schema temporário. Só roda no DEV recém-recriado e vazio. | Escreve no DEV. |

## Como repetir

1. Acesso ao DEV: `python3 backend/scripts/dev_db_service.py` (URL e senha sem eco; recusa PROD).
2. Inventário e fingerprint do DEV (`inventario_ro.sql -v contar_linhas=1`, `fingerprint_ro.sql`).
3. Leitura do PROD pela VPS, com chave temporária e "ok" do proprietário:
   `ssh root@vps 'bash <kit>/ler_prod_na_vps.sh <kit>' > leitura_prod.tar`; conferir `SHA256SUMS`.
4. Ensaiar em Supabase 17.6 local descartável (PROD e DEV simulados) e gerar o SQL real com
   `montar_recriacao.py` (`--estado-dev` da §10 do inventário do DEV, `--ledger-dev`, `--ensure-rls`).
5. Sarah revisa o SQL gerado pelo SHA-256; com GO e "ok": backup do DEV, (opcional) guardar logins,
   rodar o SQL (`psql service=pastorai_dev -X -q -f ...`), conferir fingerprint, dump e checagens.
6. Semente com "ok" próprio (`semente_dev.sql`, regerada se as migrations do ledger mudarem).

## Limites

- Igualdade provada: schema `public` inteiro (objetos, ACLs, comentários), ledger (nomes e origens),
  default privileges, ACL do schema, event triggers e extensões. Não é copiado: o schema
  `recovery` (artefato manual só do PROD), `supabase_migrations.schema_migrations` (histórico),
  dados e `applied_at` do ledger.
- As checagens de `prova_objetos.sql` têm texto de detalhe sem ordem fixa: compare só as colunas
  `migration, check_id, kind, ok`.
- O dump do PROD tem `\r\n` no corpo de 3 funções: leia e grave o dump em bytes.
