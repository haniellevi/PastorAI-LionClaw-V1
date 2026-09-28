# Histórico supersedido: reconciliação do DEV

**Não executar este roteiro.** Preservado somente como registro de 27/09/2026.
Foi supersedido por [MVP §3.5](../MVP-PLANO-SIMPLIFICACAO.md#35-ambientes-local-e-produção-decisão-de-2709):
a validação ocorre em ambiente local descartável e CI; DEV na nuvem está
parado e não recebe migrations/testes. Não é pré-requisito de merge ou migration.
Migration/deploy PROD continuam no gate humano próprio de release, com backup
e rollback. Os comandos e as recomendações abaixo são históricos, sem autorização
operacional vigente.

Preparado em 27/09/2026 sobre a main `e6aafc296014770ceabc24d5ea6bd9572f33ace4`. Nenhum comando de banco deste roteiro foi executado pelo Orquestrador. A URL e o backup ficam somente com Raniel.

Recomendação: primeiro conferir o histórico e preservar o DEV existente. Recriar agora pode apagar dados e não resolve, por si só, divergências de roles, RLS e histórico. O diagnóstico abaixo determina quais migrations realmente faltam. Isso não bloqueia o desenvolvimento da S2b; bloqueia sua futura migration/deploy em PROD.

## 1. Preparar uma cópia fixa dos arquivos

Execute no terminal local desta máquina, fora de qualquer sessão gravada. Não use terminal da VPS nem cole a URL em chat. Os comandos copiam somente código SQL e o runner, sem arquivos de ambiente.

```bash
set +x
set -o pipefail
unset PYTHONOPTIMIZE PYTHONPATH PYTHONHOME
umask 077
export DEV_FONTE_DIR="$(mktemp -d /tmp/igreja12-dev-fonte.XXXXXX)"
export DEV_PYTHON=/home/raniel-linux/workspace/PastorAi-1.0/backend/.venv-runtime/bin/python
git -C /home/raniel-linux/workspace/PastorAi-1.0 archive \
  e6aafc296014770ceabc24d5ea6bd9572f33ace4 \
  backend/scripts/migrate.py backend/migrations | tar -x -C "$DEV_FONTE_DIR"
"$DEV_PYTHON" --version
pg_dump --version
pg_restore --version
```

Esperado: Python 3.13 e ferramentas PostgreSQL 17. Se faltar comando ou a cópia falhar, pare. Esta fonte cobre a main acima; ainda não contém a migration S2b. A futura aplicação S2b usará o SHA exato aprovado da sua PR.

## 2. Informar o destino sem mostrar a URL

No painel privado, confira que o projeto selecionado é DEV. O identificador registrado no repositório é `cxmjojnocigekgcxhubi`; se o DEV mudou, pare para corrigir o roteiro antes de conectar. Use a conexão direta ou o pooler de sessão, nunca o pooler de transação da porta 6543.

```bash
read -r -s -p 'Cole a URL PostgreSQL do DEV e pressione Enter: ' MIGRATION_DATABASE_URL
printf '\n'
export MIGRATION_DATABASE_URL
for DEV_PG_VAR in ${!PG@}; do unset "$DEV_PG_VAR"; done
unset DEV_PG_VAR
export DEV_BACKUP_DIR="$(mktemp -d "$HOME/igreja12-dev-backup.XXXXXX")"
```

O bloco seguinte só valida o destino e prepara variáveis privadas para o backup. Não conecta ao banco. Ele recusa PROD, destino desconhecido, atalhos de serviço e parâmetros alternativos de host. Não imprime host, usuário ou senha.

```bash
"$DEV_PYTHON" - <<'PY'
import os, pathlib
from psycopg2.extensions import parse_dsn
try:
    d = parse_dsn(os.environ['MIGRATION_DATABASE_URL'])
    ref = 'cxmjojnocigekgcxhubi'
    host, user = d.get('host', ''), d.get('user', '')
    direct = host == f'db.{ref}.supabase.co' and user == 'postgres'
    pooler = host.endswith('.pooler.supabase.com') and user == f'postgres.{ref}'
    allowed = {'host', 'port', 'user', 'password', 'dbname', 'sslmode', 'connect_timeout'}
    valid = (set(d) <= allowed and (direct or pooler)
             and d.get('dbname') == 'postgres' and d.get('port', '5432') == '5432'
             and d.get('sslmode') in {'require', 'verify-ca', 'verify-full'}
             and d.get('password') and 'pffafnchtxbimpwyaczq' not in host + user)
    if not valid:
        raise ValueError('destino recusado')
except Exception:
    raise SystemExit('PARAR: destino/formato não confirmado como DEV. Não compartilhe a URL.')
pathlib.Path(os.environ['DEV_BACKUP_DIR'], 'destino-confirmado').write_text('DEV\n')
print('DEV confirmado; nenhuma conexão executada neste passo.')
PY
```

Se aparecer `PARAR`, não avance. Não remova a validação para fazer a conexão passar.

## 3. Conferir o histórico, sem aplicar nada

```bash
test -f "$DEV_BACKUP_DIR/destino-confirmado" && \
  "$DEV_PYTHON" "$DEV_FONTE_DIR/backend/scripts/migrate.py" status
```

Esperado: contagens `aplicadas`, `arquivos`, `pendentes` e nomes dos arquivos. Guarde somente essas contagens/nomes como evidência sanitizada. Não envie URL, resultado com dados, captura do painel, backup nem traceback bruto.

Pare nestes casos:

- `schema_migrations não existe`, coluna `name` ausente ou ledger incompatível: não crie ledger vazio e não marque migrations como aplicadas por suposição. É necessário conferir schema e proveniência antes de registrar histórico.
- Migration consta pendente, mas seus objetos já existem: não tente forçar/reaplicar. A ausência no ledger não prova ausência do SQL.
- `NO BANCO, SEM ARQUIVO`: pode incluir frentes pausadas filtradas pelo runner; conferir o nome antes de concluir que houve perda.

`status` compara nomes, não comprova que colunas, policies, grants e funções correspondem ao código. Não use “pendentes=0” como único critério de DEV reconciliado.

## 4. Fazer backup privado antes de qualquer escrita

Pause edições e jobs do DEV pela operação humana já usada para esse ambiente. Não use comandos de PROD. O backup abaixo preserva o schema `public` e seus dados; não cobre autenticação gerenciada, storage, roles ou outros schemas. Nenhuma etapa deste roteiro apaga/recria esses recursos.

```bash
test -f "$DEV_BACKUP_DIR/destino-confirmado" && "$DEV_PYTHON" - <<'PY'
import os, pathlib, subprocess
from psycopg2.extensions import parse_dsn
d = parse_dsn(os.environ['MIGRATION_DATABASE_URL'])
env = {k: v for k, v in os.environ.items() if not k.startswith('PG') and k != 'MIGRATION_DATABASE_URL'}
for key, value in d.items():
    env['PG' + key.upper().replace('DBNAME', 'DATABASE')] = value
env['PGCONNECT_TIMEOUT'] = '10'
folder = pathlib.Path(os.environ['DEV_BACKUP_DIR'])
backup = folder / 'dev-public.dump'
if backup.exists():
    raise SystemExit('PARAR: backup já existe; não será sobrescrito.')
subprocess.run(['pg_dump', '--format=custom', '--schema=public', '--no-owner',
                '--file', str(backup)], env=env, check=True)
with (folder / 'inventario.txt').open('w') as output:
    subprocess.run(['pg_restore', '--list', str(backup)], stdout=output, check=True)
if backup.stat().st_size == 0:
    raise SystemExit('PARAR: backup vazio.')
print('Backup criado e inventário legível. Preserve a pasta privada; não a envie.')
PY
```

Esperado: sucesso dos dois comandos. Inventário legível não prova restauração completa; antes de uma operação destrutiva, seria obrigatório ensaiar a recuperação em destino descartável separado. Este roteiro só autoriza preparar uma sequência aditiva, sem apagar o DEV.

## 5. Aplicar somente a sequência conferida, um arquivo por vez

Compartilhe com os conselheiros apenas a saída sanitizada do passo 3. Antes do primeiro `apply`, eles devem devolver uma sequência exata ordenada, com dependências satisfeitas e justificativa para cada migration anterior que permanecer pendente. Uma anterior sem explicação interrompe a sequência. O runner não verifica essa ordem nem os predecessores por você. Não execute um loop sobre todas as pendentes. Frentes D2A/E4B/consentimento continuam pausadas, mesmo se algum arquivo antigo não tiver o marcador que o runner filtra.

Este roteiro limita a sequência a migrations transacionais comprovadamente restritas ao schema `public`. Arquivo que crie/altere role, extensão, outro schema, default privileges ou recurso gerenciado precisa de backup e rollback específicos antes de aplicação; o backup acima não basta. Isso inclui `20260826_094317_harden_recovery_artifacts_retention.sql`, que toca o schema `recovery`: não aplicar por este roteiro. Sem essa conferência, execute somente `status`.

Em particular, não aplicar automaticamente `20260827_230003_d2a_agent_runtime_private_context.sql`, `20260828_045213_d2b2_consentimento_finalidade_evento.sql` ou `20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql`. Não chamar `apply_migrations.py`, `new_migration.py`, `prepare-head` ou ferramentas de catálogo para esta reconciliação MVP.

Quando receber a sequência conferida, informe os nomes separados por espaços, na ordem recebida. Não inclua nomes escolhidos por conta própria:

```bash
read -r -a DEV_SEQUENCIA -p 'Cole a sequência de nomes conferida pelos conselheiros: '
DEV_INDICE=0
printf '%s\n' "${DEV_SEQUENCIA[@]}"
```

Confira visualmente a lista. Execute o bloco abaixo uma vez por arquivo, sem alterar o índice para pular etapas. Só a próxima migration da lista pode ser aplicada; sucesso avança o índice. Após falha, pare, não repita o bloco:

```bash
DEV_MIGRATION="${DEV_SEQUENCIA[$DEV_INDICE]:-}"
if test -n "$DEV_MIGRATION"; then
  printf 'Próxima migration: %s\n' "$DEV_MIGRATION"
  "$DEV_PYTHON" "$DEV_FONTE_DIR/backend/scripts/migrate.py" status && \
    "$DEV_PYTHON" "$DEV_FONTE_DIR/backend/scripts/migrate.py" apply "$DEV_MIGRATION" --yes && \
    "$DEV_PYTHON" "$DEV_FONTE_DIR/backend/scripts/migrate.py" status && \
    DEV_INDICE=$((DEV_INDICE + 1))
else
  printf 'Sequência encerrada ou vazia; nenhuma aplicação feita.\n'
fi
```

Esperado: `aplicada: <nome>` e esse nome sai da lista. Só avance se o comando terminar com sucesso. `20260826_030508` já foi informada como aplicada em PROD; isso não informa o estado de DEV e não autoriza reaplicá-la. O mesmo vale para qualquer outra migration.

Falha de SQL: pare na primeira, preserve o nome e a classe do erro sanitizada. O modo normal reverte a migration e o registro juntos. Não use `--no-transaction`, não remova checks, não edite SQL histórico e não registre sucesso manualmente. Se uma migration exigir modo não transacional, ela precisa de sequência própria antes de continuar.

## 6. Conferir o resultado e encerrar

Depois da sequência, conferir os objetos esperados, RLS e grants das migrations aplicadas com consultas de schema preparadas para esse conjunto exato. Fazer o smoke funcional do DEV com dados sintéticos e envios/provedores desligados. A suíte `rls_integration` cria e remove objetos: execute-a somente no PostgreSQL descartável local, nunca no DEV compartilhado.

Registro histórico: o roteiro exigia SHA, horário, nomes aplicados, pendências e conferência do DEV. Esse gate foi supersedido pelo MVP §3.5; a orientação vigente é validação local descartável e CI, mantendo release/migration/deploy sob autorização própria.

```bash
unset MIGRATION_DATABASE_URL DEV_MIGRATION DEV_SEQUENCIA DEV_INDICE
```

Como desfazer: antes de `apply`, nada foi alterado no schema. Após uma migration bem-sucedida, não apague a linha do ledger nem restaure um dump sobre o banco existente. Use compensação revisada para o arquivo exato ou restauração ensaiada em destino novo. Preserve o backup privado.

Se o histórico estiver irrecuperável e Raniel preferir recriar DEV, preparar uma operação separada em projeto vazio: schema aprovado, sem dados/usuários/credenciais de PROD, com roles/extensões/RLS e dependências gerenciadas conferidas. Manter o DEV antigo até validar o novo. Copiar apenas o schema de PROD sem conferir essas dependências não prova equivalência.
