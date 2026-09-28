# Revisão do delta V2b após CI e threads

> Parecer histórico do snapshot `4a3fd616d71081af1e551a30ddbab9dbf1ec8208`.
> O candidato da PR #435 recebeu alterações posteriores; este parecer e os
> resultados locais abaixo não atestam o head atual. O head final requer CI e
> revisão próprios antes de qualquer merge.

## Artefato

- Base destacada: `58bcd1808aa511cdfafc7957d5c36a9c0f8ee348`.
- Worktree de revisão: `/tmp/igreja12-v2b-agenda-review-20260927`.
- Manifesto: `V2B-REVISED-SNAPSHOT.json`, SHA-256
  `19b3c24acfa2132e1e64e1112b8922d5f5e7e54473d3584c51a44ab1bb20312a`.
- Patch desde `20a44e2`: `V2B-CI-AND-THREADS-DELTA.patch`, SHA-256
  `a544bc982d1b444291df4d46fad8e65750f2c4abae3a44ab5f4f9604a517016c`.
- As 36 pós-imagens do manifesto conferem byte a byte. Os serviços alterados
  são `cell_report_reminders.py`, SHA-256
  `d2386c990df8b1845d960fa9e704a19f6798a577ac694929a5865a6af57b1245`,
  e `notification_outbox.py`, SHA-256
  `2a13a1777a1a954ea2edc1ea8a766f5361c23feefb10dacd1fb2b3ed05cfe367`.
- `git diff --check` contra a base não apresentou erro de espaço.

## Avaliação estática

### Não replay V1a

O scheduler comum continua a deduplicar por intenção de outbox e agora também
consulta `CellReportReminder` por igreja, reunião e líder, sem filtrar estado.
Uma linha legada `pendente`, `em_envio`, `retry`, `enviado`, `ambiguo`,
`cancelado` ou `obsoleto` impede nova intenção para a mesma reunião e líder.
O limite móvel de 24 horas passa a contar também qualquer linha legada recente
do mesmo líder no mesmo tenant. As consultas preservam `igreja_id`; a linha
legada expirada de outra reunião deixa de bloquear, e o histórico de outra
igreja não interfere.

Os 16 casos PG novos exercitam cada estado nos dois fences, o histórico
expirado e o isolamento entre igrejas. Isso fecha o P1 identificado na thread:
o scheduler não depende mais apenas da outbox nova para decidir se a reunião já
teve intenção ou se o líder já consumiu sua vaga diária.

### Agenda recorrente

O domínio aceita apenas ocorrências `pontual` e `semanal`. Para semanal, uma
`antecedencia_horas` inteira e não negativa passa a ser aplicada a cada
ocorrência. Sem antecedência válida, `notificar_em` absoluto é aceito somente
na data local do primeiro evento; uma ocorrência semanal posterior é recusada.
Não há derivação inventada do timestamp absoluto. A guarda final ainda recusa
due no passado ou igual ou posterior à ocorrência.

As duas funções de teste adicionadas cobrem a derivação de primeira e segunda
ocorrência com antecedência, e a recusa fechada da segunda ocorrência quando
somente há timestamp absoluto. A E2E Agenda previamente revisada permanece
como cobertura do turno real, S3, recibo, outbox e provider fake.

### SAIR, RLS e fixtures

O prefixo compartilhado Conversation para Pessoa agora usa
`populate_existing=True` nos dois `SELECT ... FOR UPDATE`. Isso evita que uma
instância ORM carregada antes do lock reapareça com estado desatualizado na
retirada concorrente. O teste real de duas mensagens `SAIR` segue exercendo o
helper pelo runtime e exige um único registro de retirada.

As demais mudanças são de fixture: acrescentam a coluna de cutover no DDL
manual e tornam o `AppUser` TOCTOU ativo. Elas reproduzem o contrato da
migration e da política humana, sem ampliar comportamento de produção.

Não encontrei novo bloqueador estático neste delta. A migration e os contratos
S3 permanecem nos hashes anteriormente revisados e não foram modificados.

## Evidência local final

- `/tmp/v2b-revised-offline.xml`, SHA-256
  `fb089119e7ea840f4794dc20905139d20ff2096159fb44be55224152c03e95a5`,
  registra 5.918 testes, zero falhas, zero erros e zero skips.
- `/tmp/v2b-revised-full-rls.xml`, SHA-256
  `9c195c8d93915f0c5a9816c57c286ff5e28ae4df782547b4ba70b97c9a78cdef`,
  registra 683 testes RLS, zero falhas, zero erros e zero skips.

Os testes foram executados pelo root. Esta revisão conferiu os XMLs, os hashes
do snapshot e os contratos estáticos, sem executar PostgreSQL, CI, migration
nem qualquer envio.

## Veredito

**Apto a novo push, CI e revisão de Sarah.** O snapshot substitui o parecer
anterior para os achados de CI e threads, e não há bloqueador estático ou local
remanescente. Isso não afirma CI remota verde nem autoriza merge, migration
aplicada, envio real ou mudança de gates.

## Próximo gate

CI no SHA publicado deste snapshot; depois, revisão de Sarah.
