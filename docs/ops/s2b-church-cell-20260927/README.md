# S2b: cadastro da igreja e células como fonte pública

Plano aprovado: [dados canônicos](../mvp-s2b-dados-canonicos-plano.md).
Base de implementação: main `e6aafc296014770ceabc24d5ea6bd9572f33ace4`.
Registro da entrega: [sprint S2b](../../sprints/2026-09-27-mvp-s2b-dados-canonicos.md).

## Uso no painel

O admin preenche endereço institucional e horários em Configurações > Cadastro
da igreja. A tela Agente mantém configuração do agente e credencial, sem outro
formulário de dados públicos. O líder edita o bairro da própria célula pelo
cadastro existente; somente pastor/admin pode marcar “Divulgar no WhatsApp”.
Células nascem sem divulgação. Atividade e bairro são requisitos de publicação.
Se informado, o dia precisa representar um único dia da semana: aliases como
“Qua” e “quarta feira” são normalizados. Ao publicar, dia inválido recebe
aviso no painel e erro na API; dia ausente é permitido. Um dia legado inválido
é omitido da resposta pública, preservando os outros detalhes da célula.

O agente consulta os dados da própria igreja. Para células, só divulga nome,
bairro, dia e horário; nunca endereço residencial, nome/telefone do líder,
anfitrião ou links. Oferece encaminhamento à secretaria para conectar ao líder.
Não calcula distância nem cria expectativa de visitante para um desconhecido.
Esse registro continua no serviço humano autenticado existente.

Sem informação cadastrada, a resposta é: “Não tenho essa informação cadastrada.
Quer falar com a secretaria da igreja?”. A confirmação da oferta tem validade
de dez minutos a partir do envio confirmado, é determinística e precede o Jev.
SAIR, LGPD, atendimento humano e gates mantêm precedência. “Sim” consome uma
oferta vigente uma vez; “não” ou mudança de assunto cancela. O retry não reabre
uma oferta nem prolonga seu prazo. Se a versão do termo mudar enquanto
a oferta aguarda resposta, o aceite continua pertencendo à oferta, sem
registrar consentimento novo. Aceites ligados a oferta inválida ou expirada
ficam encerrados de forma durável, inclusive no retry.

A resposta pública recebe classificação tipada no ledger; termo LGPD e outras
respostas novas ficam separados desse caminho. Pendências antigas sem essa
classificação, ligadas a uma consulta pública reconhecida, são suprimidas antes
do envio. Isso evita transportar fatos anteriores à troca de fonte. O operador
considera essas pendências na janela de deploy; não há reenvio automático nem
classificação por heurística sobre o texto da resposta.

## Compatibilidade e dados legados

O frontend consulta `GET /igreja/cadastro/capabilities`, autenticado. Só
`version: 1` habilita novos campos. Falha/404 mantém a interface protegida e
payloads compatíveis com o backend anterior. A troca de sessão/igreja descarta
respostas antigas; capability não é autorização de edição.

`GET/PUT /igreja/cadastro` exige admin e deriva a igreja da sessão. Os campos
são `enderecoInstitucional` e `horariosCulto`; o PUT envia ambos, cada um
aceitando `null` ou texto de até 400 caracteres.
No cadastro de célula, `bairro` e `divulgarWhatsapp` preservam os valores
existentes quando ausentes de um payload antigo. A autorização é revalidada
no backend e o isolamento permanece no banco.
O cadastro normaliza bairro em NFC; a comparação ignora caixa e os acentos
portugueses previstos. Escrita SQL direta fora da API deve manter essa
normalização; a fatia não introduz trigger de normalização nem backfill de bairro.

A migration copia somente endereço/horários válidos do JSON estruturado
`agent_configs.informacoes_publicas`, se o destino canônico estiver vazio.
Preserva o JSON, dados já existentes e divergências. Não faz backfill do bloco
livre `[informacoes_publicas]`, não cria células e não habilita divulgação.
A coluna antiga permanece como legado; não é fallback do agente nem destino
de novas gravações. A API antiga fica em leitura canônica temporária.

## Operação futura e rollback

Conforme [MVP §3.5](../MVP-PLANO-SIMPLIFICACAO.md#35-ambientes-local-e-produção-decisão-de-2709),
a validação usa ambiente local descartável e CI no head exato. O
[roteiro de reconciliação DEV](RECONCILIAR-DEV-RANIEL.md) é histórico e foi
supersedido: DEV na nuvem não é pré-requisito de merge ou migration.
Merge exige revisão e autorização nominal da PR; migration/deploy PROD
dependem do gate humano próprio de release, com backup e rollback. Esta
missão não acessa DEV/PROD/VPS/provedores. A suíte RLS usa exclusivamente
PostgreSQL descartável e fixtures sintéticas.

O assert de `igrejas_self_update` exige a policy existente de UPDATE. Não
certifica predicados alterados nem policies adicionais em um banco real;
a reconciliação precisa confirmar a baseline tenant da migration de branding.
Os testes sintéticos exercitam os predicados canônicos e o isolamento.

A migration deve usar espera curta de lock, referência de 2 segundos; em
timeout, abortar e reagendar com o operador, sem retry automático. O processo
mantém os gates separados de banco, deploy e envio. Antes de merge, avisar que
há backend e que o deploy manual exige gate próprio. Vercel publica o frontend
no merge; capability evita usar a API nova antes desse deploy.

Durante o backfill e até o deploy, suspender edições do perfil antigo para não
perder atualizações entre cópia e troca de fonte. Conferir cópia sem registrar
conteúdo privado. O rollback de aplicação preserva colunas e dados; não
restaura silenciosamente a leitura legada, apaga JSON ou remove o ledger.
Uma compensação de banco precisa de decisão operacional específica.

## Evidência local

Evidência histórica do head `7a00383`: 5.453 testes backend passaram. PostgreSQL17 descartável: 352 testes RLS
passaram, sem skips. Frontend: 902 testes, typecheck/build e seis cenários E2E
conferidos, com hashes preservados. O [registro](TEST-EVIDENCE.json) vincula
base, patch e arquivos; [SQL original](EXACT-SQL-EVIDENCE.json) foi aplicado
sem substituição em `public` de um banco descartável separado. CI e Sarah
continuam ligados ao head publicado. Nenhum resultado prova ambiente real.

## Delta de revisão da PR426

Dois P2 de Sarah corrigidos: normalização de dia único compartilhada pela API
e pelo agente, com aviso de publicação na UI/API, e assert de existência da
policy `igrejas_self_update` de UPDATE. A célula permanece na resposta quando
somente o dia legado é inválido. A thread do robô sobre resposta à oferta
interpretada como aceite de termo novo também está coberta pelo delta.

Migration corrigida SHA256
`3bfdecda8dd667de6af793c2ccb302b2b09bdec8a3fcefa3b79c410509b31c65`.
As evidências anteriores permanecem históricas; a validação deste delta fica
registrada separadamente, vinculada à base `7a00383` e ao hash do patch.

Delta validado: 5.467 testes backend, 354 RLS PG17 sem skips, 915 frontend
e typecheck final. SQL original em `public`: quatro provas passaram.
[Evidência do delta](P2-TEST-EVIDENCE.json), [SQL](P2-EXACT-SQL-EVIDENCE.json)
e [UI](UI-P2-EVIDENCE.json) mantêm os hashes e os limites de cada execução.
