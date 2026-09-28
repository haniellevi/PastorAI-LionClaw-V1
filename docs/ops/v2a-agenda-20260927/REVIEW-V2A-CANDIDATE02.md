# Revisão independente, V2a Agenda, candidato 02

## Identidade do candidato

- Base: `3e8306e9dfd5e3dec3097f3e8a701829b4d7aa36`.
- Patch SHA256: `5b556d17157d1eb543739b2abafb39623df6fdcae192f260fd0b5ad57e701d2f`.
- Manifesto: `V2A-CANDIDATE-02.json`.
- Conferência: 8 de 8 blobs do manifesto correspondem aos SHA256 declarados.

## Parecer de fonte

Não encontrei P1 ou P2 novo no recorte de oito arquivos. O candidato fecha os achados da revisão parcial:

- O título passa por limite de 120 caracteres, normalização e allowlist institucional; título sem prova humana atual, livre ou ambíguo cai no tipo fixo. A consulta não projeta descrição nem mensagem do evento.
- A prova de autoria humana exige `confirmado_em`, autor ativo do mesmo tenant, identificador Clerk não vazio e papel atual de pastor ou admin. Rascunho só alcança a projeção depois do papel elegível e da prova S3 sensível.
- O parser rejeita controles fora de faixa, filtra horário já passado no dia corrente e retorna handoff se a consulta supera 160 linhas, sem uma página parcial apresentada como completa.
- O catálogo oferece ao Choice somente a capacidade genérica `consultar_agenda`; nenhum título, identificador de evento, descrição ou mensagem entra no prompt. A projeção ocorre após o Choice, com tenant e contexto revalidados.
- A entrega reconsulta a âncora inbound, os gates, o contexto, o snapshot e o texto antes do transporte. Alteração de evento, papel, prova ou release suprime o reply pendente. A sessão usada no Choice fecha antes do lock curto de Conversation e Message.

## Bloqueio de validação

Ainda não há APTO final para o hash do candidato. O PG2 informado falha em `test_draft_agenda_requires_clerk_proof_then_projects_only_type`, pois não encontra o outbound de agenda após a prova.

O código do teste cria a prova com `s3-secret-synthetic` e `_TERM`, enquanto `resolve_confirmed_identity` consulta a referência própria `agent_identity.get_settings`. A fixture só substitui `whatsapp_privilege.get_settings`. Isso é uma hipótese concreta de desalinhamento de fixture, pois pode invalidar o HMAC ou o termo antes de `agenda_drafts_allowed`; não é prova suficiente para atribuir a falha ao produto. O diagnóstico precisa registrar o contexto sensível efetivamente resolvido e então corrigir a fixture ou a fonte conforme a causa observada.

## Limites desta revisão

- Não executei PostgreSQL, provedor, rede ou operação externa.
- A suíte offline completa estava em execução pelo coordenador quando este parecer foi escrito; não a uso como evidência concluída.
- A configuração efetiva de modelo e esforço não é exposta nesta sessão.

## Próximo gate

Receber o delta congelado que resolve o caso Clerk, conferir novamente os blobs e exigir o PG correspondente verde antes de emitir APTO técnico do candidato final.
