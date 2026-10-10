# Revisão da recuperação com chaves estrangeiras

A revisão pendente do #472 identificou um bloqueador real: tabela nova podia
referenciar uma tabela anterior sem invalidar o bundle aditivo. Isso pode
impedir a exclusão pelo código anterior ou alterar dados da versão candidata.

O catálogo agora captura relações referenciadas e ações DELETE/UPDATE. Recusa
referências novas a tabelas anteriores e a schemas fora do catálogo; conserva
referências entre tabelas novas. Bundles sem esse envelope são recusados e
precisam ser reconstruídos. Nenhuma migration de produto ou operação real foi
executada.

PostgreSQL 17 descartável exclusivo: 9 testes aprovados, zero skips, nos
contratos de bundle e compatibilidade. Exercitam NO ACTION, RESTRICT, CASCADE,
SET NULL e SET DEFAULT com exclusão real pelo caminho anterior, recusas do
bundle e do verificador vivo, referência nova compatível e bundle incompleto.
Regressão do executor de release: 54 testes e 59 subtests aprovados.
Os quatro checks e synthetic-release do novo head ainda precisam validar a
correção antes do merge; o CI anterior não valida este diff.

Revisão: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/472#discussion_r4237537588
