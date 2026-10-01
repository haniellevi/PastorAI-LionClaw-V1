# AUD-02: microfone no escopo da conversa

## Recorte e fonte

O candidato local parte de `origin/main`
`363ecb5fecb2fb81a52a14577555b9f281eef7ca`, na branch
`fix/aud02-microphone-scope-20260930`, com base de implementação
`7c9b404f87e9229db9b1bccd2fd2c3db78111759`.

O recorte é somente frontend: delimita a gravação por conversa e por contexto
autenticado, impede reentrada de envio de mídia e preserva o rascunho correto
quando a confirmação chega tarde. Não altera dependências, backend, banco, RLS,
payload de API, provedores, gates ou ambiente externo.

Além dos seis arquivos já presentes no candidato, `ConversationThread.test.ts`
foi adaptado para o contrato obrigatório de contexto de gravação. Não houve
outra ampliação de allowlist ou de escopo.

## RED e proveniência

Antes da alteração de produção desta rodada, os casos de regressão locais foram
executados com Node `v24.19.0` no diretório `frontend`:

```text
node node_modules/vitest/vitest.mjs run \
  src/components/inbox/ConversationThread.recording.test.ts \
  src/components/inbox/InboxScreen.race.test.ts \
  src/components/inbox/ConversationThread.test.ts
```

O resultado foi 3 falhas e 86 testes verdes em 3 arquivos: contexto de gravação
ausente ainda habilitava o microfone, duas ativações pré-render enviavam duas
mídias e a confirmação antiga em A, B, A mantinha a legenda que deveria ser
limpa. A fonte de produção desse RED era a base `7c9b404`; os testes de
regressão foram adicionados localmente nesta rodada.

Para a contagem histórica, a suíte limpa de `7c9b404` registrada por Sarah é
`984/984` em 104 arquivos. A evidência recebida do Root relata a mesma execução
limpa com Node 24 e `npm exec --offline -- vitest run src`; ela é a origem
histórica dessa contagem, não uma descrição do estado atual da PR. O Root também
informou que `frontend/next.config.test.mjs` já existia em `7c9b404` e que o
diff de `946a3b7..7c9b404` nesse arquivo e na configuração do Vitest era zero.

A referência a `946a3b7` é `983/983` em 104 arquivos de `src`, derivada de
contagem anterior e não uma reexecução histórica desta rodada. Sem reexecutar
os snapshots históricos, `985/985` em 105 arquivos corresponde aritmeticamente
a `983` em `src` mais os 2 testes versionados de `next.config.test.mjs`; do
mesmo modo, `986/986` em 105 arquivos corresponde a `984` em `src` mais esses
2 testes. Essas são inferências de contagem, não atribuições de execução a um
SHA. Também não há prova para atribuir um oráculo LENTE posterior a logs
antigos.

## Correção

O submit de mídia em `ConversationThread` usa uma trava síncrona em ref antes
do primeiro `await`, liberada em `finally`. O `InboxScreen` real tem uma
regressão que aciona duas vezes o botão antes do render bloqueante e verifica
exatamente uma chamada a `sendMedia`.

`recordingContext` é obrigatório no contrato e falha fechada para `null` ou
ausência em tempo de execução. Sem contexto, o compositor de áudio fica
desabilitado e não chama `getUserMedia`. A chave de sessão do pai cobre papéis,
igreja, token, status e identidade; a matriz de testes cobre cada troca durante
gravação ativa e com anexo pronto. Ao desmontar a sessão, a limpeza interrompe
tracks tardias e descarta ciclo de gravação e anexo, sem enviar mídia.

O rascunho agora guarda valor e versão no mesmo estado do pai. Quando uma mídia
antiga conclui, a limpeza só ocorre se ambos ainda correspondem ao snapshot de
submissão. O updater de React é puro e não escreve ref. O caso A, B, A de
legenda inalterada passa sob `StrictMode`; o caso de rascunho novo que volta ao
mesmo texto e anexo novo preserva os dois valores após a conclusão antiga.

## Verificação local

Executado localmente com Node `v24.19.0`, sem instalação ou rede:

- regressões focais de gravação, thread e corrida: `89/89` em 3 arquivos;
- inbox completo: `118/118` em 6 arquivos;
- caso de legenda inalterada sob `StrictMode`: 1 teste verde;
- typecheck sem emissão e lint dos cinco arquivos frontend alterados: verdes.

Uma execução local anterior de `npm exec --offline -- vitest run src` registrou
`1000/1003` testes verdes em 103 de 104 arquivos, com três asserts em
`src/lib/m09-loopback-url.test.ts` recebendo stdout e stderr vazios. Nenhum
arquivo M09 foi alterado. Essa observação é restrita ao ambiente que a produziu
e não permite inferir causa nem reaproveitar o relato histórico de `EPERM`.

No SHA `77e52922736f189985af2a665ff06d80a4923589`, Sarah mediu `1003/1003`
em 104 arquivos para `vitest run src` e `1005/1005` em 105 arquivos para
`vitest run` sem escopo. Os 2 testes adicionais vêm de
`frontend/next.config.test.mjs`, arquivo versionado, não de arquivo temporário
de auditoria.

Os testes não provam RLS, isolamento backend, provedor, deploy, flag, banco ou
dados reais.

Risco residual aceito neste recorte source-only: a perda de posse da conversa
ou um estado `degraded` descarta gravação e anexo por falha fechada; permissão
negada e gravação vazia não exibem feedback ao usuário. Melhorias de UX ficam
para fatias próprias e não abrem gate nesta rodada.

## Estado e próximo gate

A rodada 3 foi commitada e publicada por push normal no head
`77e52922736f189985af2a665ff06d80a4923589` da PR #446. Segundo evidência
recebida do Root nesse SHA, CI está `7/7 SUCCESS`, o estado é `CLEAN` e há
0 threads abertas. Não houve merge. Este delta documental exige novo head, CI
e revisões no SHA exato antes de qualquer gate humano de merge.

Se autorizado, rollback é feito por `revert` em branch própria sob gate nominal.
`reset` e descarte de mudanças não são rotas de rollback desta PR.
