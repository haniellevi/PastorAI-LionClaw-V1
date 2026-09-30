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
limpa com Node 24 e `npm exec --offline -- vitest run src`. Ela documenta a
base limpa, não é arquivo versionado deste candidato e não prova o patch
pré-commit atual. A referência a `946a3b7` é `983/983` em 104 arquivos,
derivada de contagem anterior e não uma execução observada nesta rodada. A
contagem `986/986` anterior corresponde a execução local em snapshot externo
ao commit; sem vínculo documentado, ela não deve ser atribuída a um SHA. Também
não há prova para atribuir um oráculo LENTE posterior a logs antigos.

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

O `npm exec --offline -- vitest run src` pós-correção não fecha a suíte local:
`1000/1003` testes verdes em 103 de 104 arquivos, com três asserts em
`src/lib/m09-loopback-url.test.ts` recebendo stdout e stderr vazios. Nenhum
arquivo M09 foi alterado e a causa não foi estabelecida. O relato histórico de
`EPERM` de M09 está superado pelo comprovante limpo de `7c9b404`; ele não deve
ser usado para explicar esta observação atual sem nova evidência.

Essa execução local é restrita ao ambiente que a produziu. Em
`2026-09-30T22:40:30Z`, o Root reexecutou na fonte congelada o comando exato
`env PATH=/home/raniel-linux/.nvm/versions/node/v24.19.0/bin:/usr/bin:/bin npm exec --offline -- vitest run src`,
submetido à avaliação automática e aprovado com `1003/1003` testes em 104
arquivos, exit 0. A diferença entre as execuções não permite inferir causa.

Os testes não provam RLS, isolamento backend, provedor, deploy, flag, banco ou
dados reais.

## Estado e próximo gate

O candidato permanece sem commit, push, CI remoto ou merge. Este é o snapshot
pré-commit desta rodada, não o estado permanente da PR. A fonte fica quiescente
para revisão independente. Após um novo head, CI obrigatório e as revisões
requeridas, o próximo gate humano é a autorização nominal para merge da PR
#446. Esta rodada não concede esse gate.

Rollback permanece reversível enquanto o patch não tem commit: descartar as
mudanças somente sob direção autorizada. Após eventual integração, qualquer
reversão exige branch e gate próprios.
