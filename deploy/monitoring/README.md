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
| Backup ausente ou com mais de 30 h | nenhum reinício | Brevo |
| TLS/páginas públicas falham | nenhum reinício | GitHub issue |

Os relatórios expõem somente estados fechados e tipos de erro. URLs privadas,
chaves, corpos de webhook e strings de conexão não são impressos.

## Ativação após merge e deploy aprovado

No Web Terminal da VPS, já com `/opt/pastorai-current` apontando para o release:

```bash
cd /opt/pastorai-current
MONITOR_ALERT_EMAIL=seu-email@dominio.com sh deploy/monitoring/install.sh
```

O instalador reutiliza o Brevo já configurado no `deploy/.env`; não cria conta
nem instala plugin. Ele executa um primeiro backup e um primeiro monitor; se um
deles falhar, termina com erro e preserva o diagnóstico no journal. Depois
valide:

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

O backup existente é validado e mantido na própria VPS. Isso cobre restauração
lógica, mas não perda total da conta/região. Cópia externa criptografada ou
backup diário gerenciado continua sendo um gate separado de disaster recovery.
