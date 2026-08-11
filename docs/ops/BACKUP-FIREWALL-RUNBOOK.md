# PastorAI — backup e firewall de produção

Atualizado em 2026-08-10. Este documento não contém segredos.

## Estado verificado

- Supabase PROD: `pffafnchtxbimpwyaczq`, plano Free.
- VPS: `srv1728329.hstgr.cloud` (`76.13.234.127`).
- Backup semanal da Hostinger confirmado em 2026-08-05, com 1,99 GB.
- Firewall Hostinger ativo: grupo `pastorai-production`.
- Firewall Ubuntu (UFW) ativo e habilitado no boot.
- Entrada permitida somente em TCP 22, 80 e 443, para IPv4 e IPv6.
- Portas 5432, 6379, 8000 e 8080 recusam conexão externa.

## Camadas de backup

1. Dump lógico diário do schema `public` do Supabase PROD.
2. Cópia diária dos objetos do Supabase Storage e manifesto dos buckets.
3. Dump lógico diário do PostgreSQL da Evolution.
4. Cópia consistente dos volumes `pastorai_evolution_instances`,
   `pastorai_evolution_pg_data` e `pastorai_redis_data`.
5. Cópia restrita do `.env` e do Compose do release ativo.
6. Backup semanal completo da VPS mantido pela Hostinger.
7. Cópia externa criptografada no OneDrive, sincronizada semanalmente pela
   estação Windows quando ela estiver ligada.

O backup do banco do Supabase não inclui os objetos do Storage; por isso as
duas etapas são obrigatórias. Arquivos com `.env` ficam em diretório acessível
somente por root e a cópia externa usa AES-256-CBC, PBKDF2 e chave protegida
pelo DPAPI do Windows.

## Automação na VPS

Script versionado: `deploy/backup-production.sh`.

Instalação esperada na VPS:

```bash
install -o root -g root -m 700 backup-production.sh \
  /usr/local/sbin/pastorai-backup.sh
```

Agendamento diário, às 06:15 UTC (03:15 em Brasília):

```cron
15 6 * * * root /usr/local/sbin/pastorai-backup.sh >>/var/log/pastorai-backup.log 2>&1
```

Os pacotes ficam em `/root/pastorai-backups`, modo `600`, com checksum SHA-256
e retenção de 14 dias. O script usa lock para impedir execuções simultâneas. A
`DATABASE_URL` é convertida em arquivos libpq efêmeros (`pg_service.conf` e
`pgpass`) dentro de diretório `0700`; ambos ficam em modo `600`, são montados
somente-leitura no container e removidos por trap em sucesso, erro ou sinal.
Nem a URL nem a senha chegam ao argv ou ao ambiente de Python, Docker,
`pg_dump` ou outro processo auxiliar. Depois de verificar o SHA-256 real contra
o sidecar, o backup publica somente o manifesto sanitizado
`/var/lib/pastorai-backup/backup-status.json`; ele não contém URL, senha, paths
privados ou conteúdo do pacote.
O instalador de observabilidade preserva este cron por padrão. Ele instala a
unit `pastorai-backup.service` para uma migração futura, mas só habilita o timer
com `PASTORAI_BACKUP_TIMER_MODE=enable` e recusa essa opção enquanto detectar o
cron legado. O instalador aborta também quando o timer estiver ativo embora
desabilitado, e restaura arquivos, modos e estado dos timers em falha. As units
usam `ProtectSystem=strict`, capabilities vazias e escrita direta limitada aos
destinos declarados. O monitor usa `DynamicUser`, não recebe socket Docker, não
lê `.env` nem `/root` e consulta apenas o manifesto sanitizado. O backup
continua uma fronteira root separada porque precisa do socket Docker; esse socket
é root-equivalente, portanto a allowlist de escrita não é uma contenção contra
script comprometido. Esse risco residual é explícito e nenhuma unit de
monitoramento recebe o socket.

Na estação Windows, `deploy/pull-encrypted-backup.ps1` copia o pacote mais
recente aos domingos às 05:00, valida o SHA-256, criptografa, testa a
descriptografia e remove o texto puro. A tarefa se chama
`PastorAI-Encrypted-Backup-Sync` e usa `StartWhenAvailable`, portanto roda ao
próximo login se o computador estiver desligado no horário agendado.

Verificação diária:

```bash
tail -n 50 /var/log/pastorai-backup.log
find /root/pastorai-backups -maxdepth 1 -type f \
  -name 'pastorai-backup-*.tar.gz' -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' \
  | sort -r | head
```

## Teste de restauração

Em 2026-08-07, os dumps foram restaurados em containers descartáveis, sem
escrita no ambiente de produção:

- Supabase/PostgreSQL 17: 53 tabelas, 11 funções e 9 gatilhos.
- Evolution/PostgreSQL 16: 105 tabelas de sistema/aplicação e 5.372 linhas
  estimadas nas tabelas da aplicação.
- Pacote externo: descriptografia, SHA-256 e leitura de 28 entradas aprovadas.

Repetir o teste mensalmente e após alterações relevantes de schema. Nunca
testar restauração por cima do banco PROD.

## Firewall

Regras UFW e Hostinger:

| Porta | Protocolo | Uso |
|---:|---|---|
| 22 | TCP | SSH |
| 80 | TCP | HTTP e emissão/renovação de certificado |
| 443 | TCP | HTTPS |

Política padrão: negar toda entrada não listada e permitir saída. Backend,
Evolution, Redis e PostgreSQL não podem ser publicados diretamente.

Verificar no Ubuntu:

```bash
ufw status verbose
ss -lntup
curl -fsS http://127.0.0.1:8000/health
```

Verificar externamente:

```bash
curl -fsS https://api.igreja12.com.br/health
```

Após qualquer alteração de firewall, abrir uma segunda sessão SSH antes de
fechar a primeira. Se SSH ou HTTPS falhar, usar o Web Console da Hostinger e
reverter a última alteração.

## Recuperação da cópia externa

A cópia criptografada fica em:

```text
OneDrive/Documentos/Backups/PastorAI/<timestamp>/
```

O arquivo `pastorai-backup-master.key.dpapi` só pode ser aberto pelo mesmo
perfil Windows que o criou. Para proteção contra perda total do computador,
copiar futuramente a senha de recuperação para um gerenciador de senhas; não
colocá-la no Git, em documentos compartilhados ou em conversas.

## Upgrade do Supabase

O plano Pro acrescenta backups diários gerenciados pelo Supabase e reduz a
dependência desta rotina, mas não substitui o backup dos objetos do Storage nem
uma cópia externa. O upgrade é uma decisão financeira separada; a rotina acima
mantém o plano Free protegido enquanto essa decisão não for tomada.
