# Enviar PR3 — evidências oficiais

Fatia candidata da PR #510, sem deploy ou ativação. Procedimento de migrations:
[README](../../backend/migrations/README.md#ordem-obrigatória-de-release--uvcdenviar).
Aplicar a cadeia UV/CD/Enviar antes do backend em release autorizado com backup.

Pré-requisito de release: vincular os usuários da coordenação a uma Pessoa ativa
(`app_users.pessoa_id`). A proteção contra autovalidação retorna 403 sem vínculo.
A segregação de funções vive no serviço, não no banco (limite aceito).

Somente Reencontro admite revogação por esta API. Revalidar Reencontro em turma
encerrada é intencional e exige coordenação. Novo ID preserva o histórico revogado;
a evidência ativa prevalece também na contagem e paginação de pessoas aptas.
Encontro e batismo não ganham efeito de revogação sobre a conclusão UV.

Compatibilidade com #511: `cd_conclusoes.revogada` invalida a conclusão como fonte
de equivalências de CD; sua alteração fica reservada à manutenção futura, sem
permissão de UPDATE da aplicação. Não revoga certificado emitido e não deve
alterar a evidência CD do Enviar: o leitor usa `cd_certificados.revogada`.
Regressão PostgreSQL sintética cobre conclusão revogada com certificado ativo.
Revogar o certificado continua sendo a ação que bloqueia essa evidência.

Gates preservados; produção, banco remoto, migrations remotas e deploy não
executados/não verificados. Nenhuma ativação autorizada por esta fatia.

## WhatsApp — fatia 8, desligada

`ENVIAR_WHATSAPP_APPROVED_RELEASE_ID=None` e lista
`ENVIAR_WHATSAPP_ENABLED_IGREJA_IDS` vazia por padrão, como UV/CD.
Nenhum deploy ou variável isolada remove a trava de release. Não habilitar
para teste; testes sintéticos substituem gates apenas em fixtures e usam
transporte falso. O gate humano `CELULAS_REQUESTS_ENABLED` também é preservado.

Catálogo fechado: `ENVIAR`, `ENVIAR pessoa NOME`, `ENVIAR solicitações`,
`ENVIAR nomear CÉLULA; CANDIDATO`, `ENVIAR abrir NOME; COBERTURA; CANDIDATO`.
Nomes ambíguos exigem painel. Consultas têm projeção mínima e até 25 itens;
não mostram motivo/decisão da avaliação, contatos ou referências documentais.
Solicitações exigem proposta entregue e SIM literal em até 10 minutos; NÃO
cancela a proposta. Escrita e recibo persistem na mesma transação, com
revalidação da autoridade e do transporte e recuperação sem repetir efeitos.

O WhatsApp só cria solicitação em `aguardando`; não concede aptidão, papel ou
liderança, não cria célula e não valida/revoga evidências. Avaliação e execução
continuam no painel web, com as autorizações, versão, confirmação e segregação
existentes. Formação comprovada nunca promove automaticamente. Opt-out,
consentimento, crise e handoff conservam prioridade.
