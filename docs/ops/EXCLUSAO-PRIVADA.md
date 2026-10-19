# Exclusão privada — conversa, pessoa e igreja

Código candidato; aplicação/deploy/operação remotos **não verificados**.
Não autoriza release, acesso remoto ou alteração de gates. Testes usam dados
fictícios e provedores simulados.

## Contrato e autorização web

- `DELETE /conversations/{id}` continua admin-only e responde com recibo.
- `DELETE /contacts/{id}/private-content` apaga o acervo privado da Pessoa.
- `DELETE /igreja/private-content` apaga o acervo privado da igreja autenticada.
- Os dois últimos exigem JSON com `operation_id` UUID gerado pelo cliente e
  `confirmacao: "EXCLUIR CONTEUDO PRIVADO"`. Repetir o mesmo identificador
  recupera o recibo original; outra exclusão de conteúdo novo exige outro UUID.
- `GET /igreja/private-deletions/{receipt_id}` acompanha progresso. O GET anterior
  `/conversations/{id}/deletion-receipt` permanece disponível.

O backend exige admin autenticado web; a função SQL revalida subject, vínculo
admin ativo e igreja. O admin apaga conteúdo pastoral sem ganhar SELECT desse
conteúdo. Recibos contêm somente IDs, geração e contagens. Nenhum texto,
telefone, transcrição, caminho ou hash de conteúdo entra no recibo.

**Escopo privado:** preserva cadastros oficiais de Pessoa/igreja, opt-out e
provas de consentimento sem conversas anexadas. Não muda o contrato de
`archive_pessoa`: arquivamento continua uma ação distinta. Exclusão cadastral
ou reset global continuam no [runbook nominal](TENANT-DELETION-RESET-RUNBOOK.md).
Esse caminho agora chama a mesma limpeza privada **antes** das cascatas,
na mesma transação e sem provedores. Seu contrato cadastral de consentimento
não foi alterado. Não existe endpoint web para reset global.

## Camadas e recibos anteriores

A transação enumera e apaga mensagens (incluindo protegidas), logs vinculados,
entradas V1b com âncoras vivas ou imutáveis e suas transcrições/hashes/leases.
Pessoa inclui entradas V1b órfãs identificadas pela pessoa; igreja inclui todas.
Cascatas removem desafios/provas de identidade, propostas/recibos de ação,
drafts de relatório, avisos/eventos de áudio e pedidos/propostas de oração.
O recibo enumera essas camadas; associações de mensagens protegidas, quando
instaladas, também são contadas. `transcricoes` conta texto presente;
`entradas_audio` conta entradas, mesmo ainda não transcritas.

Resumos, checkpoints e vetores privados duráveis ainda não têm tabelas ativas:
contagem zero, sem implementação de memória nova nesta fatia. Registros
oficiais publicados não são convertidos em memória nem apagados por este reset.

Recibos coletivos incluem as tarefas e envios de recibos anteriores associados,
sem transferir ou duplicar tarefas. A igreja inclui todos os anteriores;
Pessoa inclui sua proveniência e recibos antigos sem proveniência de pessoa
(inclusive resets da igreja), conservadoramente. Isso pode manter o recibo da
pessoa pendente por limpeza histórica de outro contato. Contagens agregam
camadas diretamente apagadas por cada operação, sem duplicar transitivamente.

Logs sem conversa não permitem provar a pessoa de origem. Exclusões coletivas
limpam seus **payloads** na igreja inteira, conservando IDs/eventos de dedupe:
apagar o marcador operacional poderia provocar reenvio. Logs vinculados a
outra conversa/pessoa e todos os dados de outra igreja permanecem intactos.

## Concorrência e limpeza externa

Ingestão adquire barreira advisory compartilhada por igreja antes dos locks de
Pessoa/conversa. Exclusão adquire a exclusiva antes dos locks; pais usam KEY
SHARE, compatível com FKs de mensagens. Conversas são bloqueadas em ordem de
UUID; sua geração avança antes da remoção. Writers existentes revalidam geração
sob lock. Novos eventos após o snapshot podem abrir conversa nova; não é uma
suspensão permanente de atendimento. Replay de eventos excluídos é recusado por
token opaco derivado da identidade do evento, nunca do conteúdo.

Tarefas de Storage são gravadas antes de eliminar referências. O cron limitado
usa `remove_tenant_media` estrito e retry/backoff. Sucesso apaga o caminho;
falha conserva somente código fechado `storage_unavailable`. Recibos/tarefas,
dependências e barreiras sobrevivem à remoção cadastral da igreja.

Upload iniciado tem ownership durável; tarefa não conclui enquanto ele existir.
Retorno tardio encontra a tarefa por `source_id`, inclusive sem conversa viva,
reabre limpeza e remove ownership atomicamente. Falha/timeout com resultado
externo desconhecido conserva pendência; lease vencida não prova fim do efeito.

Envio tem marcador durável criado com `ia_em_transporte`; geração/prazo são
revalidados antes do HTTP e ao persistir resultado. A janela de 60s autoriza
início, mas **não conclui recibo por tempo**: `pendente_envio` permanece até o
transporte retornar e liberar ownership. Não há reenvio após expiração.
Processo perdido exige reconciliação explícita; nunca apagar marcador somente
para deixar o recibo verde. HTTP iniciado pode ter chegado ao provedor.

## Release, RLS e limites

Aplicar `20261018_090000` e depois `20261019_090001` via `scripts/migrate.py`
antes de publicar novos writers/cron. Conter a ingestão da versão anterior
durante a troca: writers antigos ainda não tomam a barreira compartilhada. A migration de sigilo `20261018_120000`
(#515), se integrada, precede a nova por timestamp. Prova sintética cobre
mensagens invisíveis ao admin com FK composta e RLS restritiva; isso não prova
a integração futura de todas as mudanças de outra PR.

Tabelas novas têm `igreja_id`, ENABLE/FORCE RLS, FKs compostas e revokes.
O helper interno só é executável pelo proprietário SQL; HTTP chama wrapper
que revalida admin. Processing mantém o escopo tenant NOBYPASSRLS da #509.

Pendências P2 preservadas para outra fatia: identidade de worker ainda segue o
padrão servidor confiável sem subject da #509; reconciliação automática de
upload que falhou é ausente (falha pode ser ambígua); tombstones não expiram
sem política aprovada e horizonte comprovado de replay/restauração. Logs sem
âncora não têm proveniência individual retroativa; a limpeza é conservadora.
O frontend apresenta ID/estado do recibo no feedback da exclusão; não há nova
central de acompanhamento persistente no painel.

Recibo cobre banco operacional e objetos referenciados, não backups, cópias de
provedor ou objetos órfãos anteriores sem referência. A fila legada de reset
mantém a limpeza do namespace completo. Restauração exige reaplicar exclusões
posteriores ao snapshot antes de reabrir consumidores. Aplicação em PROD,
retenção jurídica e execução nominal continuam gates humanos separados.
