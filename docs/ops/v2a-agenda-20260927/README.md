# V2a: consulta da agenda pelo WhatsApp

Fatia somente de leitura, empilhada sobre PR433 `3e8306e`. O [plano V2](../mvp-v2-agenda-whatsapp-plano.md) foi aprovado com separação entre consulta V2a e lembretes/outbox V2b. Esta entrega não ativa lembretes, não muda frontend e não cria migration.

## Contrato de privacidade

O agente recebe identidade, vínculo e papel resolvidos pelo servidor. Usuários sem vínculo continuam no perfil público da S2b. Membro, operador e líder consultam eventos confirmados; rascunhos editoriais exigem pastor/admin e confirmação Clerk da S3. `publico_alvo` continua sendo seleção de destinatários e não concede visibilidade pública a `events`.

`Event.titulo` é texto livre. O filtro S2b não é um detector geral de nomes, e `origem=manual` ou `status=confirmado` não provam quem cadastrou o conteúdo. Portanto, a projeção V2a exige confirmação persistida por usuário ativo autorizado do mesmo tenant e vocabulário institucional conservador. Sem essa prova ou fora do vocabulário, usa o rótulo fixo do tipo, sem truncar/reproduzir parte do título rejeitado. Eventos legados sem autoria verificável podem aparecer como “Culto”, “Reunião” ou outro tipo, mantendo data/hora cadastradas.

Título válido tem até 120 caracteres e aparece apenas em template fixo; nunca entra no prompt do roteador. Descrição, mensagem livre, participantes, telefones e endereços residenciais ficam fora. Essa política prefere omitir um título legítimo a divulgar um nome não reconhecido; não se afirma detecção universal de PII por regex.

## Ativação e operação

A flag por igreja nasce vazia e a release em código permanece `None`, cumulativas aos gates S3. Variável de ambiente sozinha não autoriza acesso. O transporte existente revalida a autorização e a consulta antes de enviar, inclusive em retry.

PROD só muda por release em lote, com backup, migrations, backend, frontend e revisão Sarah da release. A PR432 ainda estava aberta no preflight desta missão; seu guia também marcava o simulador como pendente. Esta implementação não comprova `./dev.sh reset` nem E2E no painel/simulador. Esses testes serão feitos após disponibilização da base local, sem reutilizar dados ou provedores reais.

## Verificação e rollback

O [plano de QA](QA-PLAN.md) foi exercitado no [candidato03](V2A-CANDIDATE-03.json): 5.881 testes offline e 117 testes PG17 passaram, sem skips nas suítes executadas. Os 642 casos PG foram excluídos da seleção offline, conforme o CI. [Resultados e hashes](TEST-RESULTS.json) registram ambiente e limites; [revisão independente](REVIEW-V2A-CANDIDATE03.md) confere os oito blobs. Os pareceres parciais preservam o histórico dos achados corrigidos.

O teste Clerk inicialmente falhou por divergência na configuração sintética entre emissão e validação; agora usa confirmação real e exige contexto sensível válido antes da consulta. A suíte offline travou no TestClient sob sandbox; a execução local avaliada, com ambiente limpo e fakes, passou. Isso não comprova painel, simulador ou provedor real.

Rollback: desligar a flag V2a, suprimir/reconciliar suas respostas pendentes antes de reverter o consumidor. Nenhuma mudança de schema deve ser desfeita nesta fatia. V2b terá PR própria, unicidade por tenant/destinatário/ocorrência/finalidade e janela 08:00-21:00 igual à V1.
