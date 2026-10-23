# Readiness, alertas e backup

Esta camada mantém `/health` como liveness barata e usa `/ready` para sinalizar
DB, Redis, workers e Evolution. Falha opcional deixa a readiness `degraded`,
mas continua HTTP 200; o healthcheck do container da API permanece em `/health`
e, portanto, Evolution não causa restart loop.

## Sinais e resposta

| Sinal | Efeito no container | Alerta |
|---|---|---|
| `/health` falha | API fica `unhealthy` | Brevo + GitHub issue |
| DB/Redis falha em `/ready` | HTTP 503, sem reinício automático | Brevo + GitHub issue |
| Evolution/worker degrada | HTTP 200 `degraded`, sem reinício da API | Brevo + GitHub issue |
| Heartbeat de worker expira | somente aquele worker fica `unhealthy` | readiness degradada |
| Manifesto de backup ausente, velho ou não verificado | nenhum reinício | Brevo |
| TLS/páginas públicas falham | nenhum reinício | GitHub issue |

## Fluxo parado de outbox e webhooks

`/operations/pending` inclui contagem e idade do item mais antigo da outbox
(`pendente`, `retry` e lease vencida) e dos webhooks ainda ativos nas filas
Redis. Dead letters aparecem em `webhook_dead_letters`, fora de pendências,
vencimentos e do alerta `stuck_flow`. O endpoint continua restrito a
administrador ativo e usa a igreja da identidade autenticada. Ele retorna
somente contagens e idades, sem payload, texto, telefone ou identificador de
pessoa. Webhooks anteriores à inclusão do timestamp continuam contados, com
`age_complete=false` até saírem da fila. O snapshot Redis lê no máximo 128
envelopes por fotografia, com limite independente para filas ativas e DLQ.
Se a DLQ exceder o limite ou tiver envelope inválido, só sua métrica fica
indisponível; isso não afeta `stuck_flow`. Se a fotografia ativa ficar
incompleta, a projeção de webhooks fica indisponível em vez de aparecer como
zero.

O check `stuck_flow` do monitor fica desligado por padrão. Para ativá-lo, defina
no `.env` de implantação:

```dotenv
MONITOR_STUCK_FLOW_ENABLED=true
MONITOR_STUCK_FLOW_URL=http://127.0.0.1:8000/operations/pending
MONITOR_STUCK_FLOW_TOKEN=<credencial dedicada de leitura>
MONITOR_STUCK_FLOW_MAX_AGE_SECONDS=3600
```

Hoje o endpoint só aceita a sessão de um administrador ativo e ainda não existe
credencial dedicada de leitura para o monitor. Não habilite o check até essa
credencial existir; não use token de sessão de pessoa. O check cobre apenas a igreja vinculada
ao administrador dessa credencial, não todas as igrejas. O monitor só aceita
endpoint loopback nessa rota. A credencial é copiada pelo
allowlist para `/etc/pastorai-monitor.env`, com modo `0600`, e nunca entra nos
logs. O endpoint é consultado no escopo da igreja do administrador autenticado;
credencial inválida, métrica indisponível ou idade incompleta degrada o check.
Ele separa pendências ainda não vencidas da idade de vencimento, portanto um
lembrete futuro não gera alerta. A fila degrada quando o item vencido mais
antigo excede o limite. O monitor não tenta renovar credenciais.

Os relatórios expõem somente estados fechados e tipos de erro. URLs privadas,
chaves, corpos de webhook e strings de conexão não são impressos.

O queue-worker só renova sua lease enquanto o loop principal registra progresso
dentro da janela de 60 segundos. Cada efeito do agente é precedido por uma
verificação atômica de ownership que também renova a lease; depois da janela,
outro worker pode recuperar o mesmo envelope. O marcador só vira `done` depois
dos efeitos e somente para o dono atual. O cron-worker usa um watchdog separado,
mas ele publica heartbeat apenas enquanto recebe progresso cooperativo do tick
(descoberta, tenant, cron, cobrança e envio). Um tick travado deixa de renovar;
um tick longo que atravessa várias unidades de trabalho continua saudável.

## Resposta do agente no WhatsApp

Antes de chamar a Evolution, o queue-worker grava uma intenção de saída em
`messages`, protegida pelo índice outbound existente e por fence transacional.
A chave opaca deriva exclusivamente de igreja, evento e claim, sem conteúdo ou
fingerprint da resposta. Apenas a
intenção `ia_pendente` pode iniciar transporte; `ia_em_transporte`,
`ia_ambigua`, falha e supressão nunca são reenviadas automaticamente. Uma
resposta aceita só vira `ia` depois da persistência final. Se houver timeout,
resposta ambígua, queda após a chamada ou falha de persistência, a linha fica
para reconciliação operacional. A Evolution não documenta idempotência de
envio, portanto este desenho evita duplicação automática, mas não promete
entrega exatamente uma vez.

Reconciliação é deliberadamente humana e não executa retry cego: o operador
confere o evento no histórico da Evolution e a conversa correspondente antes
de qualquer nova mensagem. Enquanto o estado for `ia_em_transporte` ou
`ia_ambigua`, o worker não inicia outro transporte. Uma ação automática para
reenviar só poderá existir em gate próprio, com confirmação explícita e prova
de que o primeiro transporte não foi aceito.

O monitor serializa processos concorrentes com lock `0600` e grava a transição
e o instante da tentativa antes de chamar o Brevo.
Falha HTTP inequívoca usa cooldown de uma hora; timeout ou resposta ambígua usa
seis horas. Uma recuperação ou uma nova combinação de checks falhos continua
sendo uma transição nova e pode alertar imediatamente. Isso evita reenvio a
cada execução de cinco minutos sem esconder mudanças reais de estado.

## Limites de privilégio das units

As duas units usam `ProtectSystem=strict`, devices e namespaces privados,
capabilities vazias e escrita limitada aos diretórios declarados. O monitor usa
`DynamicUser`, `ProtectHome=true` e não recebe Docker, o `.env` do release ou
os pacotes privados. Ele lê somente
`/var/lib/pastorai-backup/backup-status.json`, um manifesto sanitizado contendo
idade, nome, bytes e SHA-256 já verificados pelo backup privilegiado.

O backup é a fronteira privilegiada separada: precisa acessar o socket Docker
para montar volumes e executar `pg_dump`. Esse socket é equivalente a root no
host, portanto `ReadWritePaths` limita escrita direta da unit, mas não deve ser
tratado como uma allowlist de segurança contra um script comprometido. Não há
socket Docker exposto ao monitor. A redução adicional desse risco exigiria um
proxy de socket com API limitada, que não é criado por esta missão.

## Ativação após merge e deploy aprovado

No Web Terminal da VPS, já com `/opt/pastorai-current` apontando para o release:

```bash
cd /opt/pastorai-current
MONITOR_ALERT_EMAIL=seu-email@dominio.com sh deploy/monitoring/install.sh
```

O instalador reutiliza o Brevo já configurado no `deploy/.env`; não cria conta
nem instala plugin. Por padrão ele preserva o cron M02 e habilita somente o
timer do monitor. Se detectar cron legado junto de timer de backup habilitado
ou ativo, aborta antes de escrever qualquer arquivo. A instalação é
transacional: arquivos, modos e estado anterior dos timers são restaurados se
copy, validação estrutural de unit, `daemon-reload` ou `enable --now` falhar.
Manifesto ausente, `/ready` degradado ou indisponibilidade do Brevo são sinais
operacionais: o timer de monitor permanece habilitado para alertar e observar a
recuperação, sem rollback de uma instalação válida. O timer de backup só
pode ser habilitado explicitamente, em uma máquina sem cron legado:

```bash
PASTORAI_BACKUP_TIMER_MODE=enable \
  MONITOR_ALERT_EMAIL=seu-email@dominio.com \
  sh deploy/monitoring/install.sh
```

Essa opção apenas habilita o timer; não executa backup durante a instalação.
Use-a somente após preflight e migração operacional aprovada. O primeiro tick
do monitor executa depois do commit da instalação e pode reportar degradação.
Depois valide:

```bash
systemctl list-timers pastorai-monitor.timer pastorai-backup.timer --all
systemctl start pastorai-monitor.service
journalctl -u pastorai-monitor.service -n 50 --no-pager
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

O workflow `.github/workflows/production-monitor.yml` executa de fora da VPS a
cada 30 minutos. Ele usa apenas o `GITHUB_TOKEN` do repositório e mantém uma
única issue de incidente, fechando-a quando a produção se recupera. A manutenção
da issue roda mesmo se o probe falhar; em seguida, o job falha para que o
histórico do GitHub Actions também sinalize a indisponibilidade.

## Limite de recuperação

O backup privilegiado calcula e compara o SHA-256 real do pacote e seu sidecar
antes de publicar atomically o manifesto sanitizado. O monitor falha fechado se
o manifesto estiver ausente, malformado, não verificado ou atrasado; ele não
tenta ler o pacote privado em `/root/pastorai-backups`. Esse backup local cobre
restauração lógica, mas não perda total da conta/região. Cópia externa
criptografada ou backup diário gerenciado continua sendo um gate separado de
disaster recovery.
