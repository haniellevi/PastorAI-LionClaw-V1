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
uma oferta nem prolonga seu prazo.

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

O [roteiro DEV](RECONCILIAR-DEV-RANIEL.md) foi preparado para Raniel executar.
DEV reconciliado condiciona migration/deploy PROD, sem bloquear código/PR/CI.
Esta missão não acessa DEV/PROD/VPS/provedores. Não executar a suíte RLS contra
DEV: ela usa PostgreSQL descartável e fixtures sintéticas.

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

Backend: 5.453 testes passaram. PostgreSQL17 descartável: 352 testes RLS
passaram, sem skips. Frontend: 902 testes, typecheck/build e seis cenários E2E
conferidos, com hashes preservados. O [registro](TEST-EVIDENCE.json) vincula
base, patch e arquivos; [SQL original](EXACT-SQL-EVIDENCE.json) foi aplicado
sem substituição em `public` de um banco descartável separado. CI e Sarah
continuam ligados ao head publicado. Nenhum resultado prova ambiente real.
