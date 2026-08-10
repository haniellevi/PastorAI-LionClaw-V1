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
| Backup em `/root/pastorai-backups` ausente ou com mais de 30 h | nenhum reinício | Brevo |
| TLS/páginas públicas falham | nenhum reinício | GitHub issue |

Os relatórios expõem somente estados fechados e tipos de erro. URLs privadas,
chaves, corpos de webhook e strings de conexão não são impressos.

O queue-worker só renova sua lease auxiliar enquanto o loop principal registra
progresso dentro da janela de 60 segundos; depois disso a lease expira e outro
worker pode recuperar o item. O cron-worker publica heartbeat no próprio loop,
inclusive durante a espera entre ticks, e não possui thread auxiliar capaz de
mascarar um tick travado.

O monitor grava a transição e o instante da tentativa antes de chamar o Brevo.
Falha HTTP inequívoca usa cooldown de uma hora; timeout ou resposta ambígua usa
seis horas. Uma recuperação ou uma nova combinação de checks falhos continua
sendo uma transição nova e pode alertar imediatamente. Isso evita reenvio a
cada execução de cinco minutos sem esconder mudanças reais de estado.

## Ativação após merge e deploy aprovado

No Web Terminal da VPS, já com `/opt/pastorai-current` apontando para o release:

```bash
cd /opt/pastorai-current
MONITOR_ALERT_EMAIL=seu-email@dominio.com sh deploy/monitoring/install.sh
```

O instalador reutiliza o Brevo já configurado no `deploy/.env`; não cria conta
nem instala plugin. Por padrão ele preserva o cron M02 e habilita somente o
timer do monitor. Se detectar cron e timer de backup ativos ao mesmo tempo,
aborta antes de alterar o agendamento. O timer de backup só pode ser habilitado
explicitamente, em uma máquina sem cron legado:

```bash
PASTORAI_BACKUP_TIMER_MODE=enable \
  MONITOR_ALERT_EMAIL=seu-email@dominio.com \
  sh deploy/monitoring/install.sh
```

Essa opção executa um primeiro backup; use-a apenas após um preflight e uma
migração operacional aprovada. No modo padrão, o instalador executa somente a
primeira sondagem local. Depois valide:

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

O backup existente em `/root/pastorai-backups` é validado e mantido na própria VPS. Isso cobre restauração
lógica, mas não perda total da conta/região. Cópia externa criptografada ou
backup diário gerenciado continua sendo um gate separado de disaster recovery.
