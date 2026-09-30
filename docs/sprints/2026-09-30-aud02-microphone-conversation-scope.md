# AUD-02: microfone no escopo da conversa

## Origem e recorte

Continuidade local de AUD-02 após a integração da PR #445, Hoje e atendimento
humano v1. A composição parte de `origin/main`
`363ecb5fecb2fb81a52a14577555b9f281eef7ca` sobre o candidato AUD-02 anterior
`0965b963a9196883762a61ba605d690c24830a25`, em
`fix/aud02-microphone-scope-20260930`. Esse estado descreve o snapshot de implementação antes do commit de composição.

O recorte preserva rascunhos privados por conversa da #445, a exclusão de
submits concorrentes, polling sem deslocamento, paginação com cobertura
explícita e erros/retry. Não altera backend, RLS, banco, dependências, gates,
provedores ou ambiente externo.

## RED histórico

A ficha `M-2026-09-30-aud02-microphone-conversation-scope.md` registra a
regressão DOM negativa criada e observada antes do patch AUD-02. Essa evidência
histórica cobre a permissão tardia e não foi reexecutada contra a composição,
pois o candidato já contém a correção.

## GREEN da composição

A composição mantém o ciclo de gravação vinculado à geração, à conversa e a um
contexto autenticado opaco. Troca de conversa, desmontagem ou alteração de
status, token, igreja, identidade ou papéis invalida gravação e anexo; stream
tardio encerra tracks sem iniciar recorder, cronômetro ou arquivo. A mudança de
contexto remonta a sessão do inbox e descarta seus rascunhos, enquanto a troca
de conversa na mesma sessão conserva cada rascunho.

## Testes e limites

Ambiente local, Node `v24.19.0`, com `PATH` pinado para o binário Node 24 em
npm e subprocessos:

- focais de gravação, thread e corrida do inbox: 69 testes verdes em 3 arquivos;
- inbox completo: 98 testes verdes em 6 arquivos;
- `npm run typecheck` e lint focal: verdes;
- suíte frontend completa: 982 testes verdes em 104 arquivos; 3 falhas M09 em
  `src/lib/m09-loopback-url.test.ts`. O subprocesso local do Playwright retorna
  `EPERM` ao tentar iniciar o Node 24, com stdout e stderr vazios, antes de
  carregar a configuração. A falha se repete com `PATH` pinado e fica fora do
  recorte AUD-02/#445.

Os testes usam apenas DOM, streams, tracks e conversas sintéticas. Eles não
provam RLS, isolamento backend, integração com provedor, deploy, flag, banco ou
dados reais.

## Gate e rollback

Gate pendente: autorização nominal de Raniel para merge da PR #446 no head
exato, após CI obrigatório e revisões requeridas. Rollback local: abortar o
merge pendente antes de commit, ou reverter em branch própria após autorização.
Nenhuma operação externa ocorreu.

## Verificação independente da composição

Em 2026-09-30T20:55Z, Orquestrador verificou a composição com Node24.19.0 e
PATH fixado: suíte frontend completa 985/985 em105 arquivos, typecheck e
diff-check PASS; implementador registrou inbox98/98 e lint focal PASS. Os
guards M09 locais (51/51) e a suíte completa passaram em execução do comando
exato submetido à avaliação automática; no sandbox os três subprocessos
Playwright falham EPERM antes de carregar configuração. Nenhum teste externo
à allowlist foi alterado. RED original permanece histórico, separado do GREEN.

Origem de #445 conferida no GitHub: autor e integrador haniellevi, branch
codex/ux-hoje-atendimento-v1, head76df51fe6db6ba29e22dda71d6783a459f9e738b,
merge363ecb5fecb2fb81a52a14577555b9f281eef7ca em2026-09-30T19:25:27Z.
O corpo registra autorização de publicação por Raniel; a ordem original não
foi verificada independentemente nesta sessão. Isso não concede gate adicional.

CI remoto e LENTE/Sarah devem ser vinculados ao novo head exato; nenhuma
aprovação anterior é transportada para esta composição. Classificação de
domínio na matriz PRD permanece igual. Gate humano único: autorização nominal
Raniel para merge #446 após evidências e revisões; sem merge nesta missão.

## P1 detectado e corrigido na revisão de composição

LENTE reprovou946a3b745d35b1fe560cfb648046ce32cfacaa46: após enviar mídia emA
e navegarA->B->A, a confirmação antiga apagava o novo rascunhoA. Uma
regressão permanente noInboxScreen real falhou antes dofix (33PASS/1FAIL),
com origemconv-a e legenda sintéticas. O retorno do submit agora captura
a geração e só limpa rascunho/anexo se ela continuar válida, aproveitando
a invalidação de ciclo já existente. Sem alteração de payload/backend ou
transferência da gestão de mídia ao pai.

GREEN em30/09 21:07Z: inbox99/99, gravação28/28, typecheck/lint/diffPASS;
Orquestrador reexecutou a suíte frontend completa986/986 em105arquivos com
Node24.19.0 ePATH fixado. Evidência986 é do snapshot P1, enquanto985 acima
permanece histórico do candidato946a3b7. CI e revisões devem ser renovados
no head que incorpora esta correção; nenhumGO anterior é reaproveitado.
