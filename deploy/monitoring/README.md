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
copy, `daemon-reload`, sondagem ou `enable --now` falhar. O timer de backup só
pode ser habilitado explicitamente, em uma máquina sem cron legado:

```bash
PASTORAI_BACKUP_TIMER_MODE=enable \
  MONITOR_ALERT_EMAIL=seu-email@dominio.com \
  sh deploy/monitoring/install.sh
```

Essa opção apenas habilita o timer; não executa backup durante a instalação.
Use-a somente após preflight e migração operacional aprovada. No modo padrão,
o instalador executa somente a primeira sondagem local. Depois valide:

```bash
systemctl list-timers pastorai-monitor.timer pastorai-backup.timer --all
systemctl start pastorai-monitor.service
journalctl -u pastorai-monitor.service -n 50 --no-pager
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```

O workflow `.github/workflows/production-monitor.yml` executa de fora da VPS a
cada 30 minutos. Ele usa apenas o `GITHUB_TOKEN` do repositório e mantém uma
única issue de incidente, fechando-a quando a produção se recupera.

## Limite de recuperação

O backup privilegiado calcula e compara o SHA-256 real do pacote e seu sidecar
antes de publicar atomically o manifesto sanitizado. O monitor falha fechado se
o manifesto estiver ausente, malformado, não verificado ou atrasado; ele não
tenta ler o pacote privado em `/root/pastorai-backups`. Esse backup local cobre
restauração lógica, mas não perda total da conta/região. Cópia externa
criptografada ou backup diário gerenciado continua sendo um gate separado de
disaster recovery.
