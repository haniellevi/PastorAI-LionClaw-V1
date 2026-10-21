# Consumo operacional de IA por igreja

`GET /operations/ai-usage` exige sessão web e papel `admin` da igreja,
revalidados pelas dependências existentes. O tenant vem da sessão; parâmetros
como `igreja_id` não escolhem outra igreja. Não há consulta global de plataforma.

Retorna contagem de registros do ledger `ai_usage_logs`, soma de tokens de
entrada/saída e custo registrado, entre agora menos sete dias (inclusivo) e
agora (exclusivo), UTC. Valores nulos legados contribuem zero. A contagem não
representa turnos completos, sucesso nem cobertura integral de chamadas de IA;
o custo segue a unidade já registrada no ledger, sem conversão monetária.
Ausência de registros retorna zeros, sem provar ausência de tráfego.

A consulta agrega no Postgres com filtro explícito por igreja e contexto RLS
existente. Não lê texto de conversa, nomes de modelos ou ferramentas, nem
retorna identificadores pessoais. A resposta usa `Cache-Control: no-store`.
Nenhum dado novo é persistido: retenção adicional zero; janela de consulta de
sete dias não significa purga do ledger original. A retenção desse ledger
continua inalterada e sua definição/execução permanece pendente.

A fatia de idade acrescenta `GET /operations/pending`, com a mesma sessão web,
papel admin, tenant derivado da sessão e `Cache-Control: no-store`. Não recebe
identificador de igreja como seletor. Nenhum dado novo é persistido.

Retorna `measured_at` UTC e, por fonte, contagem, idade em segundos do mais
antigo, quatro contagens por faixa (`under_5m`: [0,300), `5m_to_1h`:
[300,3600), `1h_to_24h`: [3600,86400), `24h_plus`: [86400,infinito)),
`stuck_count` e `stuck_oldest_age_seconds`. Sem pendências: contagens zero e
idades nulas. Datas futuras contribuem idade zero. O parâmetro
`stuck_after_seconds` aceita inteiro entre 1 e 2592000 (30 dias), padrão 3600;
a comparação é estritamente maior que o limite. Ele configura somente a
leitura, sem persistir configuração ou alterar filas.

Fontes desta fatia:

- `messages`: respostas outbound de IA em `ia_reservada`, `ia_executando`,
  `ia_pendente` ou `ia_em_transporte`, pela data `criado_em`. Estados finais,
  falhos e ambíguos ficam fora; inbound não é presumido como pendente.
- `tasks`: tarefas `work_queue_items` com status nulo legado, `aberto` ou
  `assumido`, pela data `created_at`. São tarefas operacionais humanas,
  não jobs de transporte. Resolvidas ficam fora.

“Preso” é um indicador de pendência antiga por fonte, calculado desde a criação;
não prova falha, inatividade desde a última transição ou descumprimento de SLA.
Não se somam fontes: uma mesma jornada pode ter tarefa e mensagem.
Todas as agregações respeitam também policies restritivas de privacidade;
a contagem representa apenas linhas visíveis à sessão autenticada.

**Limites explícitos:** `webhooks_available=false` porque webhooks ainda não
persistidos vivem em listas Redis globais, sem isolamento RLS ou projeção
segura de metadados por tenant. `outbox_available=false` porque a outbox completa
é privada do worker; a sessão humana só vê uma parte por policy. Ambas ficam
fora de `sources`, em vez de retornar zero enganoso. Não há leitura de payload
Redis, remoção de claim JWT, impersonação de worker, BYPASSRLS ou ampliação
de SELECT em conteúdo. A medição dessas duas fontes permanece pendente de
projeção agregada segura por igreja em outra fatia.

Migrations antes de publicar o backend:

1. `20261023_100000_ai_usage_force_rls.sql`: mantém a policy existente por
   `igreja_id` e garante ENABLE/FORCE RLS no ledger. Usa `lock_timeout=2s`;
   se não obtiver o lock de metadados, parar e tentar em janela autorizada.
2. `20261023_100001_ai_usage_tenant_created_idx.sql`: índice
   `(igreja_id, created_at)`, `CREATE INDEX CONCURRENTLY IF NOT EXISTS` via
   `backend/scripts/migrate.py apply <arquivo> --yes --no-transaction`.
   O runner suporta a opção; o índice fica em arquivo separado porque múltiplas
   instruções no mesmo comando criariam transação implícita incompatível.
   Não bloqueia escritas durante a construção, mas usa locks breves de
   coordenação. Uma falha pode deixar índice inválido: conferir `pg_index.indisvalid`
   e reconciliar em manutenção autorizada antes de repetir; IF NOT EXISTS não
   repara índice inválido. Rollbacks comentados nos arquivos.

Não altera catálogo/roteador do agente, provedores, workers, filas, gates ou
comportamento de envio. Não cria capacidade do agente ou alerta externo.
Nenhum efeito externo é ativado. Produção, desempenho em volume real e quatro
checks de integração: **não verificado** por esta prova local.

Validação: PostgreSQL 17 descartável exclusivo, cadeia ativa completa de
migrations aplicada pelo runner, instalação do zero e atualização com ledger
sintético preexistente. A fixture da #537 passa a usar o schema/policies reais.
As consultas rodam como `authenticated`, sem superusuário/BYPASSRLS, com claim
humano sintético e tenant. Testes cobrem duas igrejas, ausência de conteúdo,
faixas/limiar, estados terminais, fonte vazia, índice e gates HTTP de papel e
sessão. Identidade HTTP é injetada: login Clerk real não foi verificado.

Próxima fatia: projeção segura de metadados das filas Redis/outbox por igreja,
sem payload ou acesso privilegiado na leitura admin. Depois: métricas por rota,
SLO e retenção/purga do ledger. Alertas externos exigem escopo e autorização
próprios.
