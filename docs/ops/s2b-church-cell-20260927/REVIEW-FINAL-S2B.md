# Revisão final S2b

## Veredito

**APTO técnico limitado** para o candidato congelado com base
`e6aafc296014770ceabc24d5ea6bd9572f33ace4` e patch SHA-256
`3e69b971fe3f29a121a6fd3fbaee6a1dcfb03fca84a3f8a1d5a2ba1abaeef8e0`.

Conferi os 44 arquivos do registro `TEST-EVIDENCE.json`: 44 hashes coincidem
com a cópia revisada. Também conferi a migration
`6679087ae4b8b97eba7dca1a8b068c76fdc7a799b87cda95347e285c16d6ebe1` e o
teste SQL `3a752e5cf6ef92ca2d5f7e2f720dfc278fb2adf2573e1af8744156af4cea3a6e`.

Não identifiquei P0, P1 ou P2 pendentes neste patch.

## Pontos verificados

- O marcador `messages.public_info_reply` separa a resposta pública
  determinística de consentimento e respostas gerais. `true` rederiva a
  resposta usando a âncora inbound e os fatos atuais antes do transporte;
  `false` não reclassifica uma resposta comum; `null` legado só é suprimido
  para consulta pública reconhecida. A revalidação preserva opt-out, humano,
  configuração ativa, credencial válida e termo atual.
- A oferta de secretaria permanece ancorada em conversa e mensagem do mesmo
  tenant pelas FKs compostas. O estado preparado só ganha os dez minutos após
  confirmação de transporte. Aceite antecipado, repetição, expiração, retry e
  substituição de estado terminal mantêm consumo único sem renovar oferta.
- A deleção de tenant bloqueia todas as conversas do tenant em ordem estável
  antes de tocar Igreja ou Message. Isso fecha a inversão com o worker, que
  bloqueia Conversation antes de Message. O trigger invoker limpa as quatro
  colunas antes da exclusão da âncora, e os testes PG verificam as constraints
  de FK específicas, inclusive tenant e conversa distintos.
- A projeção pública lê somente endereço institucional, horário, bairro, nome,
  dia e horário de célula publicada/ativa do tenant. O filtro ocorre antes do
  limite; endereço residencial, liderança, telefone e links não atravessam a
  fronteira. API e UI preservam o isolamento por sessão, papel e capability,
  inclusive ausência de campo legado e falha de nova leitura.
- A documentação descreve a S2b como preparação, conserva os gates de banco,
  deploy e envio separados e não afirma aplicação em ambiente real.

## Evidência revisada

- Backend local: 5.453 testes aprovados, 352 RLS excluídos dessa execução.
- PostgreSQL 17 descartável: 352 testes RLS aprovados, sem falhas ou skips.
- Frontend: 902 testes, typecheck, build e seis cenários E2E aprovados.
- SQL original da migration, sem reescrita de schema, aplicado em `public` de
  banco descartável exclusivo: duas provas aprovadas.

Essas evidências validam o código e a migration no candidato exato, em fixtures
sintéticas. Não comprovam aplicação da migration, deploy, configuração ou
envio em DEV/PROD. A fronteira física do provedor continua sem garantia de
exactly-once após falha ambígua, conforme o protocolo já documentado.

Próximo gate humano: autorização nominal de merge após PR e checks do head
publicado, mantendo banco, deploy e envio como gates independentes.
