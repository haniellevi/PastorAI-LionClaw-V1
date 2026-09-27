# Revisão independente, delta final da PR 428

**Resultado: APTO técnico delimitado.** Não encontrei P0, P1 ou P2 aberto nos deltas congelados.

## Candidato conferido

- Base: `2bacfe8ae7688e7b489294ad75f1b9f2dac29b72`.
- Manifesto: `docs/ops/s3-whatsapp-20260927/CANDIDATE-HASHES.json`.
- SHA-256 do manifesto: `6834153ed0fb80b183eef2b6baef3d33bff86448fe4a7b3defdcd1a89e327db6`.
- Conferência local: 46 de 46 blobs de fonte, testes e CI correspondem ao manifesto.

## Threads do robô

O catálogo agora lê exclusivamente o inbound persistido e ancorado pelo par igreja e conversa antes de formar qualquer `CandidateOption`. A comparação normalizada aceita somente nome único explicitamente citado naquele inbound. A contagem de homônimos acontece antes dos limites, portanto uma ocorrência fora da página continua suprimindo o alvo ambíguo. B e C recebem apenas rotas, códigos e descrições; D recebe somente os alvos filtrados. O teste PG captura os três prompts, exclui a pessoa não solicitada e demonstra que `outcome.texto` forjado não altera a seleção.

Sem nome explícito, não há alvo mutante nem roster no estágio D. Consultas readonly permanecem classificadas pelo modelo e exigem confirmação forte no painel. Esse é o limite deliberado da fatia, pois não há detector determinístico de intenção natural nesta entrega.

Na confirmação de identidade, a orientação de erro e expiração manda repetir a consulta sensível no WhatsApp. O componente não expõe comando inexistente, URL, armazenamento persistente ou detalhe retornado pela API. A troca de escopo de sessão aborta a requisição anterior e impede que sua conclusão modifique a sessão nova.

## Delta Sarah

A migration aditiva repete com `CREATE ... IF NOT EXISTS`, recria somente constraints e policies nomeadas, e mantém os grants e revokes explícitos. A prova de SQL literal no schema `public` executa os bytes duas vezes, preserva o OID e a proposta já gravada. As relações novas continuam com RLS e FORCE RLS, e as policies separam leitura do painel, emissão pelo worker e criação de prova pelo sujeito autenticado.

`PRIVILEGE_APPROVED_RELEASE_ID` nasce como `None`. Mesmo uma igreja listada na variável de ambiente permanece inerte até uma revisão de código nomear release aprovada. Os testes cobrem allowlist vazia, igreja listada sem release, release vazia, release sintética explícita e UUID inválido, sem abrir banco ou provedor no caminho inerte.

## Evidência informada

Não executei banco, provedor ou ambiente externo nesta revisão. O root informou backend `5661/5661`, sem skips, e frontend com 22 testes focais, build e um E2E aprovados no manifesto exato. A suíte RLS de 390 cenários permanecia em execução no momento deste relatório; seu resultado deve ser associado ao mesmo manifesto, sem inferência antecipada.

## Limites

Este parecer não autoriza merge, flag, envio WhatsApp, TypeSafe, OpenAI, deploy, migration compartilhada ou uso de dados reais. Também não mede qualidade de classificação nem latência de campo. Uma mudança futura que nomeie release aprovada exige revisão e gates próprios.
