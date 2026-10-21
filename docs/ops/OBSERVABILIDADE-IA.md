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

Não exige migration, não altera catálogo/roteador do agente, provedores,
workers, filas, gates ou comportamento de envio. Nenhum efeito externo é
ativado. Produção, desempenho em volume real e quatro checks de integração:
não verificado por esta prova local.

Validação: PostgreSQL 17 descartável com duas igrejas sintéticas, papel
`authenticated` sem BYPASSRLS, policy por `current_igreja_id()` e RLS forçada.
A fixture reproduz o contrato da tabela/policy; não atesta instalação acumulada
das migrations. Os testes HTTP injetam a identidade para exercitar o gate de
papel existente e a consulta real; não atestam login Clerk real.

Próximas fatias: idade agregada de pendências por igreja; métricas de contagem e
latência por rota normalizada com retenção limitada; SLO e diagnóstico de fluxos
presos; política de retenção/purga do ledger. Alertas externos exigem escopo e
autorização próprios.
