# Release em lote, outubro de 2026

## Contraprovas da frente de fence incorporadas (06/11/2026; autoridade indisponível)

O handoff independente `writer-fence-20261106/DESIGN-HANDOFF.md` foi confrontado com o candidato49. Ele entrega desenho e contraprovas de cliente/predicados, sem mecanismo autoritativo global. A integração mantém `NativeFenceContract`, dispatchers, cliente Storage e os49pins nativos byteiguais; `admit()`/`validate_authority()` continuam recusando. Nenhum lock SQL parcial ou nova API/epoch/assinatura foi apresentado como solução global.

Foram incorporados nove testes em `deploy/tests/test_writer_fence_boundaries.py` e um passo CI isolado. O cliente `backend/app/services/storage.py` atual é byteigual ao pin APPafdf e à fixture da entrega, SHA256 `61d9319981d46d8aaa23023fdbf2500d7a79857fcc48cf733083d927bc649008`; os testes carregam esse arquivo diretamente com configuração/HTTP/PG/host fictícios. A cópia redundante de32.945bytes não foi adicionada e o patch recebido não foi aplicado. Não há teste congelando o hash do cliente: a equivalência é registro de proveniência da integração.

Os três casos Storage mostram o limite do transporte previamente autorizado: gates locais fechados não impedem o POST, resultado2xx observado após o deadline preserva o efeito confirmado e timeout deixa desfecho desconhecido. A conclusão posterior ao erro é uma possibilidade construída na fixture do provedor, não medição de commit/timing do Supabase real nem prova da autorização de uma rota completa. Cinco casos PG mostram exclusões de roles internas/subtração de conexões declaradas no contador de escritores desconhecidos; o controle positivo zero continua sendo amostra. `require_quiet` rejeita uma amostra explícita com sessão de escrita; nenhum desses predicados impõe contenção contínua.

O desenho exige inventário efetivamente fechado de projeto/conta, DB/buckets/prefixos/objetos, endpoints e principais; negação de novas mutações e reconciliação das já aceitas mesmo quando clientes reportam erro/timeout; custódia contínua desde antes da captura fresca até handoff sem lacuna ao handle exato do DDL. Liberar um lock SQL para permitir outro handle do migrador não pode reabrir escritores externos. SHARE em tabelas seria componente parcial para DML dessas relações, sem provar cobertura de sequências, de todo o DDL, de novas relações ou de Storage e sem sobreviver à perda da sessão. Não foi executado lock ou ensaio PostgreSQL físico nesta entrega.

Os15canais mínimos do contrato são obrigações conservadoras de inventário, não prova de uso ativo em produção. Auth, GraphQL, Edge/admin e outros emissores só podem ser declarados presentes/ausentes com evidência apropriada; protocolos de upload não são excluídos só porque o app não os usa. Gates de envio, Nginx, RLS, read-only por conexão e contagemzero não resolvem a autoridade de todos os planos. Fonte pública conferida: [read-only parcial](https://supabase.com/kb/troubleshooting/putting-a-project-in-read-only-mode-or-freezing-writes-during-a-migration-b5a2c7) e [controle de acesso Storage](https://supabase.com/docs/guides/storage/security/access-control). Não foi usada CLI nem alterada configuração/permissão Supabase.

Validação desta integração: nove casos novos mais os51contratos existentes passaram juntos; o passo CI exato passou nos nove sem processos/sockets/serviços reais dentro dos testes. As51repetições não são somadas como casos novos: cobertura local acumulada2572distintos, com as limitações e falha antiga do worker preservadas nos relatórios. Ruff e revisão independente aprovados. Não repetimos suítes nativas/physicals inalteradas.

O registro de integração e provas fica em `native-fence-handoff-integration-20261106`, fora do produto. Nenhuma leitura de `/opt/containerd` foi repetida ou contornada; não houve produção, Storage real, push/PR/branch remoto, workflow remoto ou Devinonline. O próximo avanço operacional segue dependente de autoridade nativa verificável e autorização do escopo real; sob a restrição atual a solução comprovável é preservar as recusas e tornar essas fronteiras regressões executáveis.

## Candidato49 para revisão por commit local (06/11/2026; publicação pendente)

Esta entrega consolida o candidato integrado em commit local, na worktree isolada `igreja12-a8-c2-integration`. Registro do SHA, auditoria do diff e descrição de PR ficam em `native-local-commit-20261106`, fora da árvore do produto. A publicação de branch/PR continua aguardando autorização específica; nenhuma ação externa de publicação é repetida nesta etapa.

O código nativo e os pins49 não mudam nesta consolidação. A evidência continua sendo2563casos distintos aprovados em etapas,51subtestes e3skips, com limites e falha anterior do worker preservados no relatório. Os registros abaixo de checkout não commitado descrevem a fase anterior ao empacotamento local. Checks verdes de62978386 não validam o novo commit: `backend-tests`, `frontend-ci`, `e2e-critical` e `rls-integration`, do app15368, precisam concluir com sucesso no SHA que vier a ser publicado. O gate posterior de main exata+cinco workflows permanece separado.

Factory/ORIGIN/DDL/A8/produção continuam fechados, por falta de autoridade contínua SQL/API/Storage. Não houve produção, push, PR, workflow remoto ou Devin online nesta consolidação.

## Prazo do provisionamento, diagnóstico CI e contrato da fence (06/11/2026; NO-GO operacional)

Candidato isolado na mesma worktree, agora com **49 fontes**, Plan `69583d125d49268c3644d227dac8d707e87d71809c69cf37d5c9879c791ac1ae`. Não houve reaplicação de patches. O módulo novo `first_transition_native_fence.py` entra nos pins; `NativeProcessBoundary` foi acrescentado ao módulo externo existente, sem alterar a AST da classe `NativeOuterDispatch`. Leitores V2/V3/settings canônicos permanecem intactos. Contrato C2 revisado `ad3c6da5e08bb06543c8047fadb634455f897f4fa3c122a9fdd658d3736e50aa`: apenas adapter mudou, AST fora de adapter_sources igual ao HEAD629 e outros28arquivos/checker9cc mantidos. O checker continua cobrindo29arquivos, não todo o comportamento49.

`NativeParentCloneProvisioner.provision_bounded(timeout_s=30,cleanup_budget_s=5,stop_budget_s=.3)` limita o caminho completo de criação/retorno da cápsula ou finalização de tentativa falha. Cada CLI, inspeção e propriedade arbitrária do runner roda em helper, sob deadline monotônico real; o pai registra o ID retornado antes do próximo comando. Sucesso mantém recursos HELD para o job/outer posterior. Falha reserva cleanup próprio sem repetir CREATE. CREATE sem ACK permanece UNKNOWN mesmo com inventário momentaneamente vazio; nunca declara limpeza completa por essa observação. Nenhum recurso é adotado de JSON, nome ou label.

Falhas/interrupções em __exit__ ou observações do pai após criação também passam pela finalização independente, no MESMO prazo. `recover()` só restaura o papel subreaper que a instância do PID proprietário adquiriu, após provar árvore vazia e started⇒reaped; não desativa papel alheio. Sem essa prova ou tempo restante, não abre outro helper nem muta recursos e registra `held_resources_pending=True`. A exceção/cancelamento original permanece sanitizada. Porta de cleanup original é consumida sem fabricar observação do filho. Bloqueios de kernel, tarefas assíncronas do daemon e criação sem ACK continuam impedindo promessa de cancelamento/limpeza absoluta; as flags de autoridade/hard-cleanup/fonte/A8/produção permanecem falsas.

`check_integrated_candidate.py` preserva o gate existente de main exata+cinco workflows e adiciona modo diagnóstico `--candidate-checkout`/`--repository`. Antes de qualquer GET e depois dele confere HEAD/status Git, recusa flags assume-unchanged/skip-worktree e entradas sparse, filtros ativos e alterações tracked/staged/untracked. Exige quatro contextos únicos do app15368, SHA/namespace exatos e completed/success; paginação incompleta ou ambiguidade recusa. É diagnóstico de check-runs, não prova da árvore ignorada, identidade workflow/path/event, autorização de deploy ou fence. Override de repository só existe no modo diagnóstico. Os22testes novos e20legados foram incluídos no CI local correspondente.

Consulta GitHub somente leitura observou os quatro checks **verdes somente no SHA62978386**. PR#618 continua aberto nesse head, destinado a `fix/nginx-http-https-window`; main observada é `f189aa495cdd8822f930aad3d8664bca7ec961fb`. As alterações49 não têm commit/ref remoto: o diagnóstico recusa este checkout como `candidate checkout has uncommitted changes`, com zero GETs. **Não disparar CI no SHA antigo para reclassificá-lo como evidência do candidato atual.** Sem push autorizado neste escopo, não é possível fechar os quatro gates remotos deste diff. A consulta e URLs estão em `native-ci-fence-20261106/remote-base-checks.json`.

`NativeFenceContract` define o limite inferior revisado de15rotas e2buckets (`whatsapp-media`, `church-logos`), preservando extras como unresolved e sem declarar inventário completo. Autoridade necessária deve possuir/excluir continuamente API/queue/cron/broadcast/SQLAlchemy, Nginx e Evolutionbridge separados, SQL externo/transações/DataAPI/sequências/DDL e StorageHTTPS/service_role/S3/signed/resumable/inflight uploads. Deve vincular projeto Storage à fonte SQL e manter custódia antes da captura fresca até handoff sem lacuna ao writer DDL exato. Leases, hashes/RR, observaçãozero, RLS, Nginx ou restrições do Postgres não cobrem todos esses caminhos. `admit()` e `validate_authority()` recusam sempre `native-fence-authoritative-mechanism-unavailable`, inclusive JSON alegando sucesso.

Validação: **2135 casos nativos +386 C2+42 diagnóstico/pipeline=2563 distintos aprovados**,51subtestes e3skips opt-in. Evidência em etapas: broad41 deu2128pass/1fail/3skip221,67s (um worker falhou antes do parser); o caso isolado no mesmo fonte passou0,55s, sem afrouxar assert, causa não confirmada. Após fechar P2 de saída/recuperação, os sete módulos afetados passaram382casos81,71s no fonte final, incluindo o caso anterior e seis casos novos. Coleção final2138, dos quais3skips; não somar382repetidos como casos adicionais. Cápsula C2 exata386pass2,44s; diagnóstico/pipeline42pass0,49s. Ruff75Python/diff-check aprovados. Revisão independente encerrou P2 de índice oculto, aquisição/saída do subreaper e finalização após interrupção; nenhum novo P1/P2 concreto no escopo. Logs anteriores e atuais preservados.

**Caminho crítico:** publicar sob autorização um commit/ref que contenha este diff exato, executar e conferir os quatro gates nesse SHA, e obter mecanismo/autoridade contínua SQL/API/Storage com inventário completo e handoff verificável. Kernel/daemon ou CREATE desconhecido exigem desfecho autoritativo antes de alegar cleanup. Até lá Factory/ORIGIN/DDL/produção seguem fechados, `source_unchanged_proven=False` e A8False. Não houve produção, Docker real nesta fatia, Storage real, push/deploy, disparo de workflows, Devin online ou envio privado externo. Provas físicas anteriores não foram reclassificadas.

**Histórico anterior:** candidato48 e suas provas abaixo precedem esta continuação49. Usar novo cumulativo sobre629 OU novo delta sobre candidato48 de SHAeaa17ac2; nunca combinar cumulativos ou reaplicar A8/C2 antigos.

## Recursos do pai, schema conjunto e wrapper externo (06/11/2026; NO-GO operacional)

Continuação na mesma worktree isolada `igreja12-a8-c2-integration`, sem reaplicar patches. **48 fontes**, Plan `698656e9735911662c4f01f0c110ff5c69c4fab1cc565ac3faf06fd4b5b3498a`. O único módulo adicional é `first_transition_native_outer.py`; leitores V2/V3/settings canônicos preservam bytes. Contrato C2 revisado `f721841f5954481d8ba98697a4ed0559a4ee7dda8eb1d38501fc4c27cefada16`: somente adapter mudou; AST fora de `adapter_sources()` igual ao HEAD629, outros28arquivos incluindo checker9cc intactos. O checker cobre29arquivos, não o comportamento nem todo o bundle48.

`NativeParentCloneProvisioner` cria explicitamente rede interna e container parado, registra apenas IDs retornados, congela o registro e entrega cápsula privada em memfd com quatro selos. `NativeParentCloneHandle` exige pin independente do registro/config/request/context/daemon; aceita a cápsula no único input selado, sem adoção de JSON de resultado. O job confere metadata HELD antes de tocar o provider e novamente antes do START, inicia somente o CID registrado depois do fechamento da origem e mantém restore/replay/comparadores estritos. O modo legado foi preservado. No modo pai `cleanup_verified=False`, `parent_cleanup_required=True` e `binding.parent_registry_digest` são obrigatórios; o evento filho `cleanup-finish` significa liberação do uso local, nunca ausência Docker. Somente o callback do pai após reap pode observar essa ausência.

O supervisor aceita extensões conjunta/pai apenas com seus pins independentes `joint_policy_sha256`/`parent_registry_sha256`; ausência de pin proíbe a extensão e presença exige o par completo. Campos/tipos/digests/limites e falsas alegações de autoridade são conferidos. Teste com emissor real do `NativeWindowJob`, TLS em loopback e custódia verifica o formato conjunto, sem promover retenção/recuperação Storage ou fence. Os seis argumentos posicionais anteriores dos pins continuam compatíveis.

`NativeOuterDispatch` executa o wrapper inteiro em fork e reserva prazo para outro fork de finalização do registro original. O pai Linux dedicado é temporariamente subreaper; pidfds e waitpid encerram/reapam também descendentes com sessão própria. Sucesso com descendente vivo recusa. Bloqueio C2/cleanup, pipe/fork falho, cancelamento e saída inválida são testados. Depois de quiescência comprovada, cleanup independe de main/job/IDs de JSON e acontece antes da revalidação do runtime; drift recusa o resultado sem suprimir limpeza. Os objetos originais também são consumidos no pai após as tentativas armadas, impedindo replay por wrapper novo ou chamada direta; nenhuma observação/evidência do filho é fabricada nos objetos originais.

Validação local: **2056 casos A8 distintos +386 C2 =2442 aprovados**,51subtestes e3skips opt-in. Foram duas etapas: regressão40módulos deu2055pass214,20s antes da última correção de consumo no pai; após reproduzir esse P2, os15casos do único módulo afetado passaram em10.63s no fonte final, incluindo o caso novo e bloqueio de replay. Não houve rodada única de2442casos nem soma de repetições como testes distintos. Cápsula C2 exata do CI:386pass2.44s; Ruff71Python e diff-check aprovados. Revisão independente encerrou os P2 de cleanup suprimido e reutilização pós-fork, sem novos P1/P2 no escopo. Logs preservados em `native-parent-outer-20261106`.

**Limites atuais:** provisionamento ocorre antes do wrapper e tem prazo próprio30s cooperativo; criação sem ID retornado fica UNKNOWN e não é adotada. Fechar o contexto fecha só o FD; preflight sem fork exige cleanup explícito do proprietário, enquanto tentativa armada consome as portas e não permite retry automático. O processo externo exige Linux/pidfd/subreaper, um thread, único reaper, ausência de filhos/customSIGCHLD/subreaper prévio e árvore inspecionável de até64filhos. Kernel não interrompível, tarefas remotas/daemon e código hostil escapando do modelo não ganham garantia de cancelamento. Os testes desta fatia não executaram Docker real nem novo ensaio físico de SQL/restore; provas anteriores pertencem aos bundles respectivos.

A fence ainda precisa cobrir API, queue/cron/broadcast e SQLAlchemy direto, ingressos Nginx e Evolution bridge distintos, SQL externo/transações abertas, Data API e StorageHTTPS/service_role/S3/signed uploads. RLS, Nginx, restrições do Postgres e zero sessões/leases observados não excluem todos esses caminhos. **Factory, ORIGIN, DDL e operação real continuam fechados**: `source_unchanged_proven=False`, `a8_window_proven=False`, `production_ready=False`. Os quatro gates CI remotos continuam pendentes. Sem produção, Storage real, push/deploy, Devin online ou envio privado externo.

**Histórico anterior:** candidato47 e suas provas abaixo precedem esta continuação48. Escolher o novo cumulativo sobre629 OU o delta novo sobre o candidato47 de SHAfaef6a35, nunca combinar cumulativos ou reaplicar A8/C2 originais.

## Dispatcher C2, gates e limpeza registrada (06/11/2026; NO-GO operacional)

A continuação usa a mesma worktree isolada `igreja12-a8-c2-integration`, sem reaplicar A8/C2. O bundle contém **47 fontes**, Plan `bf4d4bcb56666a56ebb0bdaed7df596cb8ea153d9333bd08a4cced803297ea59`. Os três módulos novos são `first_transition_native_dispatch.py`, `first_transition_native_gates.py` e `first_transition_native_cleanup.py`. O contrato C2 revisado passa a `f46aba34243cabbe00aecb62595faddc4789ba394a15455f35f62f21ca68cdb0`; só mudou o hash do adapter, cuja AST fora de `adapter_sources()` permanece igual ao HEAD629. Os outros28 arquivos do contrato, inclusive o checker confiável9cc, mantêm bytes. O contrato anterior recusa apenas o adapter; não é afrouxado para aceitar fontes diferentes.

`NativeC2Dispatcher` compõe a sessão C2 exata com `NativeSupervisedWindow`, em uso único. Antes de conter o host exige FD regular, legível, até2MiB e quatro selos; reconfere sua identidade após C2 e captura, sem fechar o FD do chamador. Sete gates observam ordem, request/context/Plan/manifest/runtime, identidade dos componentes, relógio monotônico/wall e emissão original do supervisor. Resultado alterado, clock substituído/regressivo, cancelamento ou emissor de cleanup divergente envenena a instância e impede reutilização. O lease C2 é liberado pela própria sessão antes de retornar; o recibo é uma observação pontual, não uma contenção global mantida durante captura. Nenhum marcador DDL é autorizado.

`NativeDockerCleanup` usa um registro imutável de IDs retornados pela criação **no pai**, com nonce próprio e pins de daemon, request/context, nome, imagem, rede e tmpfs. Antes de remover algo confere inventários independentes por request, namespace legado e nonce; recurso desconhecido, alias do host protegido, imagem/mount/porta/rede divergente ou worker não reapado recusa sem adotar órfãos. Remove somente IDs registrados e reconfere ausência e daemon. Evidência tipada é vinculada à observação original, não a JSON apresentado pelo chamador. Injeção de fake daemon permanece marcada como tal; mesmo o CLI Docker real não concede `daemon_cleanup_authoritative`, fence ou prazo externo rígido.

A prova física nova passou em **1,807s** com o supervisor real, resultado de job inteiramente fictício e cleanup Docker real. Um container novo **nunca iniciado** e uma rede interna próprios foram registrados pelo pai e removidos; ausência foi reconferida e não houve fallback do pai. O relatório `native-owned-cleanup-physical-20261106-a/report.json` fixa o mesmo Plan47, declara `source_capture_verified=False` e não executa SQL, captura, restore/replay ou app. Provas físicas antigas continuam com seus bundles37/34/27, sem reclassificação.

**Bloqueios concretos:** o `NativeWindowJob` ainda cria recursos no filho; falta protocolo de provisionamento/handoff para vinculá-los ao registro do pai. IDs/nonce desconhecidos são recusados, nunca adotados a partir do resultado do worker. Callbacks C2/cleanup e o wrapper completo ainda precisam de processo externo com prazo rígido; limite individual do CLI e validação de tempo decorrido não suprem isso. O parser do supervisor ainda recusa a extensão de job conjunto. Falta fence autoritativa de SQL direto/transações antigas/API/sequências/Storage e sua prova independente. `NativeWindowFactory`, recibo ORIGIN, DDL e despacho operacional permanecem fechados; `source_unchanged_proven=False`, `a8_window_proven=False` e `operational_ready=False`. Os quatro gates CI remotos continuam pendentes. Sem produção, push/deploy, systemctl/cron reais, alterações em Storage, Devin online ou envio privado ao Claude.

Validação local final: **1.947 casos A8 e386 C2 aprovados (2.333 distintos),51subtestes e3skips opt-in**. Não foi uma rodada única verde: os39módulos A8 deram1922pass/25fail em183,68s; todas as25falhas foram `probe-state-in-checkout`, pois o basetemp estava dentro do checkout de tarefas. Somente esses25casos foram repetidos em pasta própria fora de Git, sem editar runtime, com25pass0.77s. A cápsula exata do CI passou386casos2,38s. Logs originais e nodeids preservados. Ruff69arquivosPython e diff-check aprovados; revisão interna independente sem novos P1/P2 após corrigir FD legível, vínculos/relógios, revalidação do emissor original e latch de cancelamento. Sem CI remoto.

**Histórico anterior:** o candidato44 e as validações abaixo são anteriores ao dispatcher47. Para integração desta continuação usar um único cumulativo sobre629 OU o novo delta sobre o candidato44 de SHA813c0c6e, nunca reaplicar os patches A8/C2 originais ou combinar cumulativos.

## Candidato A8+C2 integrado em área isolada (06/11/2026; NO-GO operacional)

A integração está em `igreja12-a8-c2-integration`, separada da A8 congelada. Foi aplicado uma vez o cumulativo A8 `b8d31b112593edaf94f823012e99be368c7a65f2281952f5618492cda86c1181` e uma vez o C2 único `ea6cb2b96f6fe817782e82113e16247a47de57bba237c9a990c58a4dee065637`; nenhum delta antigo C2 foi combinado. A worktree original C2 e sua entrega permaneceram intactas.

Dos dez compartilhados, nove preservam bytes exatos; o adapter muda somente `adapter_sources()`, sem outra diferença AST. Seus sete módulos C2 agora participam dos **44 fontes** e do Plan `3248928efa5476711fc5303f258cbf8ef7cdce32908907fa44b736c171b8a54b`. Teste novo demonstra que mudar C2 invalida o Plan. O contrato antigo recusou somente o adapter, como esperado. Nova referência revisada: `eac37a1f794d0bff7391f441f85d355fb5ae558e019d221e16209bf7c1e40d19`; checker confiável permanece `9cc6448b0435c5005a03c3d0256fdacc4215ac43e6176ba8b1abbc124ed2c675`. O verificador cobre29arquivos e não concede autoridade sobre os44 nem sobre comportamento.

CI conserva A8 em seu comando próprio e C2 em cápsula de30arquivos (/tmp,29fontes+JSON), sem dotenv/plugins herdados e com rootdir/confcutdir isolados. Verificador confere fontes antes da cópia e a cápsula novamente. O step novo fixa `working-directory: .`, evitando herdar backend. A tentativa de misturar os46módulos em basetemp sob/home produziu145recusas C2 pela política explícita/tmp; a regra foi preservada, sem relaxamento de runtime. A cápsula e o comando real extraído do CI passaram nos386casos. Logs da tentativa e da correção permanecem para auditoria.

A validação física de7,463s do app/CA/PID/mounts pertence ao bundle37 anterior; é evidência reutilizável desse mecanismo, não execução física conjunta A8+C2. C2 continua exclusivamente de fixtures, sem despacho operacional, systemctl/cron reais, retomada, recriação ou remoção de legado. Lease cooperativo e zero writers observados não constituem fence SQL/API/Storage. `source_unchanged_proven=False`, A8 e `production_ready=False` permanecem. Os quatro gates remotos backend-tests/frontend-ci/e2e-critical/rls-integration ainda são exigência do release e não foram disparados.

Validação final local do candidato44: **1848 testes A8 +386 C2 aprovados (2234 distintos),51subtestes e3skips opt-in**. A8:156,30s/exit0 em36módulos; cápsula C2 extraída do CI:2,43s/exit0. Ruff63arquivosPython e diff-check aprovados. Revisão independente encerrou o P1 de working-directory do CI sem novos P1/P2; não houve merge/deploy nem execução dos quatro gates remotos.

**Histórico anterior:** os bundles37/34/27 abaixo precedem a composição44. A8 congelada permanece disponível separadamente; usar o patch integrado sobre629 OU o delta de integração sobre A8b8, nunca reaplicar C2 ou somar cumulativos.

## Bootstrap, mounts, PID e supervisão integrados em fixtures (06/11/2026)

Bundle congelado de **37 fontes**, Plan `968ddbcb25242f73f34540f265a3dbaa3a3f58f6e4e67d7395849bc62cf7ec50`. O bootstrap agora aguarda ACK antes de importar o app. O probe pinado confere SO_PEERCRED/PID1/UID e FD real; o controlador confere imagem, entrypoint Python absoluto, mounts RO, namespace, rede, hostPID/StartedAt e hashes antes/depois. Há nova observação da CA após ACK e antes/depois do smoke; chamada direta de start não contorna a admissão. Falha/cancelamento tenta parar somente o backend próprio, com ownership separado de readiness e PID0 fresco. Recibo público/digest entra no journal A9; não há adoção de processo anterior por uma instância nova.

`NativeSupervisedWindow` valida pedido/contexto/runtime real/argv e resultado JOB_SCHEMA, executa worker com inputmemfd selado e limite externo, preserva eventos próprios separados dos eventos do job e chama cleanup do pai após tentativa inválida/falha. O callback ainda é fronteira confiável: `daemon_cleanup_authoritative=False`, `cleanup_hard_deadline_verified=False` e processo externo completo ainda necessário. Conversão para ORIGIN_RECEIPT sempre recusa por falta de fence; extensão conjunta do job ainda não é aceita nesse parser estrito.

Prova física nova: **7,463s, passed=True**, imagem app pinada e PostgreSQL novos/próprios, rede interna sem portas publicadas, configuração fictícia de desenvolvimento e gates fechados. App respondeu health200 após ACK; CA foi observada viva novamente, stop confirmou PID0 e dois containers/rede tiveram ausência reconferida. Não houve migrations, restore/replay ou validação de baseline/ready/produção. Os ensaios anteriores recusados conservaram diagnósticos e limparam recursos; stdout de stop não é prova de fechamento, pois o CLI também imprime aviso de depreciação.

Regressão36módulos:1829passed/18failed/3skipped/51subtests,154,63s. As18falhas foram exclusivamente AF_UNIX path too long do fixture de admissão com basetemp longo; mesmo cenário reproduzido e corrigido somente no fixture (diretório /tmp curto privado),33passed3,19s depois. Cobertura distinta final:1847casos aprovados/3skips/51subtests, sem alegar uma rodada única verde. Ruff43fontes/testes e revisão independente local aprovados; a integração C2 terá validação própria. Não houve CI remoto.

A8/fábrica/produção seguem **NO-GO**, `source_unchanged_proven=False`. Bootstrap admitido em fixture não substitui fence SQL/API/Storage, autoridade do cleanup/recuperação ou os quatro checks CI do candidato de release. Próximo passo: C2 consolidado em cópia isolada, após comparar seus10compartilhados e revisar nova referência; não editar a frente C2 nem reaplicar seus deltas antigos. Devin online não foi utilizado.

**Histórico anterior:** os bundles34/27fontes e suas provas abaixo precedem esta integração.

## Holder conjunto e custódia de CA preparados; A8 fechada (06/11/2026)

O bundle passa a **34 fontes pinadas**. O exporter captura e confere os oito campos de identidade/transação; `holder_cursor()` executa o coletor no próprio backend do holder, sem substituir o importer dos leitores V2/V3. O Pulse continua do dump ao HTTP e à persistência sem reiniciar seu relógio; dump ou cleanup falho não expõe Pulse reutilizável. Divergência do holder fecha a sessão e impede adoção posterior.

O core conjunto e o leitor HTTPS do handoff foram incorporados com hashes conferidos; apenas os dois imports do hook receberam aliases locais. A composição nova é **exclusivamente sintética**: HTTPS em loopback, SQL em loopback ou endereços documentais RFC5737 e aliases fictícios. Endpoints nominais são recusados antes de abrir provider/holder porque não existe guard autoritativo. TLS é construído previamente com trust set copiado e pinado, IPs numéricos, request/context/policy/runtime pinados; guard, prazo e Pulse permanecem ativos durante a escrita. Não há nova entrada CLI operacional.

A projeção SQL até16MiB e o manifest até2MiB ficam em custódia própria, separados do dump100MiB/companion2MiB. Request/origem/janela/token/dump/hash vinculam o par; ambos são revalidados até depois da limpeza do clone. Há entrega por memfd selado e retenção privada dos parciais. Corpos HTTP são apenas conferidos e descartados; não há prova de retenção ou recuperação Storage nem replay da projeção.

`NativeCandidateCA` e um bootstrap fixo de processo único foram preparados para manter CA efetiva em memfd com quatro selos durante todo o app. O guard é instalado antes do import, restringe conninfo, verifica autenticação/TLS/identidade no mesmo handle, faz rollback e fecha conexões antes do FD. O observador confere FD/PID/startticks/selos/bytes reais em `/proc`, sem aceitar booleano de metadata. Multiprocess/exec não são admitidos. O bootstrap **ainda não está ligado ao CandidatePort**: faltam mounts/pins/entrypoint e vínculo independente do PID efetivo; `native-candidate-effective-ca-unproven` permanece antes do start.

`source_unchanged_proven=False`, `a8_window_proven=False` e `operational_ready=False` permanecem. Hash antes/depois, RR, Pulse e guard fictício não são fence. [Supabase descreve seu read-only como bloqueio parcial](https://supabase.com/kb/troubleshooting/putting-a-project-in-read-only-mode-or-freezing-writes-during-a-migration-b5a2c7): sessões antigas e Data API podem continuar escrevendo. Falta autoridade exclusiva que cubra SQL direto, transações abertas, API, sequências e Storage, além do recibo/handoff e supervisor operacional. Sem produção, Storage real, push/deploy ou envio privado externo. C2/preservação permaneceram sem edições desta frente; Devin só Desktop, não utilizado nesta fatia.

Validação final: **1.748 testes e51subtestes aprovados;3skips opt-in**,137,58s (33 módulos do CI), UID1000. Ruff de37arquivos Python e diff-check aprovados; revisão independente interna encerrou quatro P2 da continuação, sem novos P1/P2 no escopo testado. A prova física focada passou em2,302s: duas conexões TLS1.3 ao PG170006 próprio, Q_HOLDER8 real estável antes/depois da exportação, FD da CA observado duas vezes e fechamento/cleanup conferidos. Ela não iniciou app nem executou o job completo HTTP/clone. O relatório preserva essa limitação e a ausência posterior do único container/rede próprios. CI remoto não executado.

**Histórico anterior:** os testes físicos de27fontes abaixo precedem este bundle; não são prova física das novas34fontes.

## Transportes nativos e eventos da admissão (06/11/2026; NO-GO operacional)

O candidato fixa 27 fontes, incluindo `first_transition_native_events.py` e `first_transition_native_transports.py`. A construção permanece pura; não existe nova flag CLI de admissão, recibo JSON ou descoberta de credencial. `OriginWindowPorts` pode carregar o bundle tipado de consumidores; `run` usa seu endpoint pinado nos writers, `assemble` seleciona o migrador nativo e a política do candidato, mas `NativeWindowFactory` continua recusando antes de abrir o provider. Não substituir esse guard por sucesso de teste ou callback declaratório.

O provider é lido no máximo uma vez e congelado para todos os consumidores. Writers usam exatamente o hostaddr/port aprovados, sem resolver DNS. O observador limita connect ao mínimo entre o orçamento restante e8s, fechando uma conexão tardia. O migrador exige Python3.13 igual ao runtime configurado, raiz privada, primeira tentativa na ordem correta, TLS/autenticação e safety do perfil, identidade/V1/ledger/quietude/índices; só então muda o default RO da sessão e aplica o arquivo pinado no MESMO handle. Retorna ao modo RO/caminho protegido, verifica o estado e fecha. Falha consome o executor; não adota prefixo parcial, não repete nem troca de rota. Execução deve ocorrer em worker externo dedicado: os timeouts cooperativos não o substituem.

O candidato usa URL nativa com hostaddr, verify-full, CA explícita, channel binding, GSS/client-cert desativados, TLS mínimo e opções fixas; timeout5 corresponde ao `connect_args` do get_engine pinado. URLs dedicadas não vazias recusam até contratos próprios de role/credencial; não há fallback privilegiado inventado. `native_ca_override` é campo opcional do CandidateSpec e um arquivo público de mount, nunca contém URL/senha; o arquivo e o Compose precisam coincidir com a policy. Inspeção fresca projeta somente URLs/PG* e mounts. O mount RO é intenção, não custódia do inode efetivo: a verificação do CandidatePort permanece NO-GO antes do start enquanto faltar prova da CA no runtime durante toda a vida do processo.

Ensaio físico com PostgreSQL e containers próprios, imagens locais por digest, TMPFS/rede interna, TLS e linhas fictícios: 50,637s. Backup/clone/replay51 verificados; depois o novo migrador aplicou51 na própria fonte sintética. Ledger129/8CONCURRENTLY e catálogo final iguais aos do clone. Probe em container da imagem pinada usou get_engine real, validou conninfo antes do driver, selou a CA efetiva em memfd antes de login e observou TLS1.3/libpq170009. O único processo inicial era Python sleep; o app não foi iniciado. A HBA foi alterada apenas no PGDATA novo para admitir o IP desse peer próprio. Cleanup por IDs/labels/daemon removeu três containers e duas redes, com ausência reconferida. Isso não altera produção nem a worktree C2.

Os oito eventos reais são request, capture-start, source-frontends-closed, capture-finish, recovery-start, recovery-finish, cleanup-finish e result. Usam wall+monotonic, rejeitam mudança de relógio e excesso de orçamento e têm digest ligado ao binding do job. Frontend fechado não é atestado de backend ausente. O resultado continua JOB_SCHEMA, não ORIGIN_RECEIPT. `source_unchanged_proven=False` permanece obrigatório: antes/depois iguais, RR/shared snapshot, WAL/stats amostrados e sessões RO não provam ausência histórica de outro escritor. É necessária fence autoritativa que cubra também clientes diretos/API/Storage, com intervalo e handoff definidos. Nenhum WindowEvidence(allowed=True) fornecido pelo caller cria essa autoridade.

O handoff HTTP foi revisado em código/pins, sem objetos/tokens. Seu patch de outro adapter não foi aplicado. O Collector exige holder com oito campos (database/readonly/isolation/snapshot/backend/role/session_role/transaction_start), não o importer atual de três campos; exige ainda o mesmo Pulse através do dump e HTTP, sem rearmar o gap. PrivateMaterial pode conter projeção de16MiB, incompatível com companion de2MiB sem nova custódia. Antes de qualquer holder, ainda precisam ser admitidos guard real, request/runtime pins, IP/TLS e o vínculo SQL/projetoHTTP. Retenção de corpos/recuperação Storage e imutabilidade de provider não são provadas pelo transporte HTTP. Os nove testes originais não foram repetidos.

Regressão congelada:1.493passed,2skipped PostgreSQL opt-in,12subtestspassed,152.48s; Ruff/diff-check e revisão estática independente aprovados. CI remoto permanece pendente. Guardas reais, A8 e prontidão operacional continuam fechadas. Nenhuma produção, Storage, push, deploy ou Claude nesta continuação.

**Histórico da ponte e das primitivas (05/11):** as limitações descritas a seguir são as de cada incremento anterior; o estado atual é o acima.


**Leitores recuperados e integrados:** não subsiste o bloqueio de localização. Base canônica posterior ao R16: `CAPTURA-DIRETA-R4-20261104`; queries V2/V3/comparador V3 coincidem com R16, e inventário/settings usa a versão R4 gerenciada. Os quatro arquivos foram copiados byte a byte para `first_transition_native_v2.py`, `first_transition_native_v3.py`, `first_transition_native_v3_compare.py`, `first_transition_native_settings.py`. O wrapper `first_transition_native_readers.py` preserva os corpos canônicos de coleta/projeção do capture core R4 e de ACL do pacote lógico, com aliases locais, sem reaproveitar autorizações/pedido/dump/deadline históricos do input bridge. Plan e expectativa PG incluem essas cinco fontes: 23 no total; aplicação/SQL e executor permanecem nos mesmos pins. CI inclui os módulos e dois testes novos nas listas explícitas de lint/pytest.

Amostras privadas ficam serializadas com limite; resumos só têm hashes e contagens. `collect_source` usa o reader autenticado do mesmo snapshot e as queries canônicas, sem abrir login paralelo próprio. V2 compara catálogo/row_counts/settings; V3 compara todas as nove categorias, preservando ACL nula/vazia/explícita e identidades posicionais. A projeção LOGIN aplica-se somente ao esperado; o inventário observado do clone mantém os flags reais, evitando aceitação de LOGIN extra. Settings permanecem no inventário, sem suprimir automaticamente preload gerenciado nem alegar igualdade literal dos valores brutos. O wrapper endurece os tipos booleanos/escalares e não modifica os arquivos canônicos. Comparação não faz repair. Gate de replay exige comparação e índices válidos all-schema antes de observar/executar, valida V1 e identidade diferente da origem, usa replay único e verifica estado final. Deve ser composto no futuro runner com amostra/estado/replay do MESMO clone pinado, vinculados ao pedido/dump/companion; o gate isolado não consegue comprovar esse vínculo, isolamento, bytes restaurados ou limpeza e declara `a8_window_proven=False`.

**Supervisor externo local:** um worker Python explícito é lançado em sessão/grupo próprios, sem shell, com argv sem URI/senha, ambiente mínimo e FD de entrada opcional selado (sem segredo em env/argv). stderr é descartado, stdout limitado e privado; tempo após criação é observado externamente, inclusive worker bloqueado sem check cooperativo. Pai deve ser dedicado/single-thread e único reaper, sem processos/thread handlers concorrendo por waitpid; pidfd não é lock de PGID. O líder permanece unreaped até waitid/checagem de propriedade/SIGKILL do grupo próprio e verificação dos membros ativos, inclusive threads de líder zombie. Só depois é reapado; descendente abandonado, contexto de propriedade divergente ou ausência de prova de cleanup recusa o resultado e impede retry. Não há sinalização de grupo depois de reap. Criação inicial via Popen pode bloquear antes do monitor; worker confiável não pode escapar do grupo. Daemon Docker, volumes/redes/containers e backend remoto exigem suas próprias verificações de limpeza. Essas limitações impedem tratar o supervisor sozinho como prova completa de A8.

**Primitivas de conexão e snapshot implementadas:** a policy nativa independente restringe a um host DNS, IP canônico e porta; banco/role `postgres`, versão 170006 e perfil gerenciado existente. URI deve conter senha explícita e não pode trocar rota/service/options ou duplicar parâmetros; PG* herdado recusa. CA pública (até 64 KiB) em diretório 0700 de dono esperado tem tipo/permissões/links/hash conferidos, é copiada para memfd selado e usada por `sslrootcert=/proc/self/fd/<fd>` durante o handshake. Libpq recebe TLS verify-full, GSS disable, channel binding require, sslcertmode disable e startup RO/search_path/RLS/statement_timeout fixos. Antes de qualquer SQL, as informações nativas devem confirmar senha usada, TLS, parâmetros efetivos, versão e IDLE; não são hashes de senha nem atestação do binário servidor. Biblioteca sem suporte a sslcertmode disable recusa. Erros do driver e URI não entram em exceções públicas.

No holder: BEGIN RR/RO, timeout/safety SELECT fixo, V1 esperado e exportação; cada importer faz BEGIN e SET TRANSACTION SNAPSHOT parametrizado como primeira instrução seguinte, antes inclusive de SELECT set_config. Depois valida safety/V1 e hash de pg_current_snapshot; mantém holder aberto e aceita leitores sequenciais, rechecando INTRANS/RO/RR/hash após o coletor e antes do rollback. Leitores/tokens perdidos, contexto divergente ou orçamento cooperativo de 240 s vencido recusam e fecham recursos. Rollback/IDLE/close são conferidos quando possíveis, sem alegar ausência do backend remoto. O cursor continua parte do código nativo confiável; não é sandbox contra coletor malicioso que encerra/reimporta transações.

Os testes somente simulam o driver; CA fictícia não é certificado de TLS real. As primitivas não estão ligadas à fábrica/CLI, e kwargs seguros do conector não são propagados magicamente à URI bruta dos consumidores. Faltam admissão completa desses consumidores, queries canônicas V2/V3 sanitizadas e pinadas da frente de recuperação, dump com importação física/keepalive, isolamento/timeout externo do worker, restore/replay/limpeza do mesmo clone e validação nativa. Connect/statement timeout e relógio cooperativo não interrompem toda chamada bloqueada de driver/filesystem. Defaults locais adicionais do libpq (por exemplo CRL) e a compatibilidade de runtime/certificado devem integrar o ensaio isolado futuro; não foi acessado qualquer arquivo de credencial ou fonte real nesta entrega.

**Custódia nativa local implementada:** `NativeWindowArtifacts` é um componente explícito, sem ligação ao CLI ou `OriginWindowPorts`. Usa root previamente provisionado 0700 e dono esperado (root por padrão), diretório exclusivo `digest(request)`, nomes fixos `window.dump`/`companion.json`, openat/dirfd/O_NOFOLLOW em todos os ancestrais e arquivos exclusivos 0600. Captura por pipe não bloqueante, com limites de 100 MiB e 2 MiB, sem analisar o conteúdo opaco do companion como prova de origem. Mantém FDs, hashes e pins de identidade/metadados; verifica também os vínculos nominais.

`copy_verified` somente escreve no pipe de um futuro consumidor depois de copiar o artefato inteiro para memfd privado, verificar hash/par/vínculos e confirmar selos Linux de escrita/tamanho/novos selos; não há fallback sem selagem. Leitura posicional preserva offsets dos FDs originais. Revalidação após entrega recusa drift, e falha impede emissão de metadados posteriores. O componente não fecha os pipes do chamador, não remove artefatos nem reutiliza diretório; fecha seus FDs, inclusive staging, no fim/erro. O chamador deve conter/parar o restore e limpar seu clone se qualquer etapa falhar.

Deadlines monotônicos limitam esperas de pipes e recusam sucesso tardio; syscall de filesystem/fsync pode bloquear e ainda exige timeout externo do worker. Memfd exige kernel Linux com selos funcionais e capacidade para até 100 MiB de staging, além dos artefatos em disco. A custódia detecta drift acidental, sem alegar proteção contra root hostil. Não comprova status de saída do produtor, autenticação/TLS, snapshot comum, V2/V3 estritos, recovery/replay ou limpeza do clone. Esses componentes e a prova física continuam necessários; esta fatia não abre A8 nem resolve as pendências de outra frente.

A integração adiciona somente uma porta de composição Python confiável (`OriginWindowPorts`), sem flag de recibo JSON, import dinâmico ou descoberta de provedor. Seu contexto deve ser pinado independentemente pelo adaptador nativo revisado; `admit` deve recusar se algum consumidor direto da URI (inclusive migration/candidato) não impuser rota, CA, TLS e startup correspondentes. Congelar a URI não propaga essas políticas. Sem porta nativa, `run` mantém as recusas anteriores antes de segredo/host/diário, sem fallback ao backup V1.

Após contenção e quiescência, o pedido A8 durável precede uma única chamada ao provedor. O contrato valida vínculo ao pedido/contexto, snapshot e bytes dos artefatos, V2, todas as nove categorias V3 com deltas zero, contagens/configuração projetada, catálogo restaurado, identidade/digest do mesmo clone/replay51, índices válidos, isolamento e limpeza. São atestações de código confiável, não evidência física fornecida por JSON. O diário preserva somente a prova normalizada, revalidada antes e depois da quietude final; omitir o validador recusa, sem descartar a prova. Prova histórica, incompleta, divergente ou atrasada recusa antes do marcador DDL; pedido consumido não é repetido.

Limites locais: 1.200 s do recebimento até validação, 240 s até fim da captura, 60 s para início/intervalo das fases e 60 s de idade após recuperação. A validação só recusa resultados tardios; o provedor deve limitar IO e concluir limpeza, pois este contrato não interrompe um callback bloqueado. O ensaio sintético usa atestações explicitamente fictícias e não comprova TLS/rota, captura/recovery nativos ou prontidão A8. Implementação nativa, CI do candidato, evidências e autorização operacional continuam pendentes. Não repetir ensaios reais de outra frente para validar esta mudança local.


## Admissão de metadados da origem no controlador (05/11/2026)

O controlador inclui explicitamente os contratos de origem, captura e preflight autenticado no conjunto de18fontes que compõe o plano. `check-origin` recebe `--origin-contract 2`, `--origin-plan` e `--origin-observation`; `check-source-preflight` recebe `--source-request` e `--source-report`. Os argumentos devem ser completos, corresponder ao modo e selecionar um único perfil. `prepare` vincula os assessments ao window_digest; retirar ou substituir a seleção altera esse vínculo.

São verificações locais de consistência e freshness dos metadados, sem abrir provedor, credencial, conexão, captura, daemon ou diário. A origem schema2 exige o plano completo R16 e suas identidades/ledger/baseline; o relatório autenticado exige o perfil gerenciado explícito, plano do controlador correspondente, TLS e fechamento, dentro de60segundos. O PASS R19 histórico não é evidência fresca. O contrato não atesta os bytes de artefatos nem o binário gerenciado e não transforma uma declaração do chamador em autorização.

`run` com qualquer desses perfis recusa antes de acessar segredo/host. Captura HOST-DIRECT/schema4 e R4 não são reclassificadas como schema2 nem como recibo A8; também não há fallback automático ao caminho legado. `check`, `check-bindings` e `rehearse-backup` recusam flags incompatíveis. Captura nova no contexto da janela, recuperação/replay independentes e seus vínculos operacionais ainda dependem da implementação/evidência próprias. Nenhuma operação de produção é ativada por esta integração.

Os ensaios nativos e preflights históricos permanecem preservados nas frentes existentes, com seus horários e limites. A integração reutiliza essas provas apenas no escopo correspondente, inclui os dois novos arquivos de testes/lint no CI do controlador e valida o candidato exato antes do pacote preparatório. Não repetir restauração, captura ou replay51 para validar esta mudança de código.

## Decisão vigente A9 para a primeira transição (30/10/2026)

O dono aprovou preparar quatro candidatos e iniciar somente backend para smoke, com ingresso externo/interno comprovadamente bloqueado. Queue/cron/broadcast permanecem `created`, com StartedAt inicial e restart=no, até a retomada nominal A10. Não chamar `create_and_start` atual nem iniciar consumidores por dependência/Compose. O cron novo com gates fechados também poderia cancelar pendências; parar somente o cron legado não prova preservação na subida. Backend deve ser verificado contra manutenção/agendador no startup. A aprovação atual cobre implementação local em dois blocos e testes exclusivamente simulados, não execução desses comandos ou inventário em ambiente real. Nenhum novo gate é criado nem os existentes são abertos para passar testes.

**Rede dos candidatos nunca iniciados:** Docker pode deixar `NetworkID` vazio no estado `created`. A inspeção vincula o nome e o ID da rede por duas consultas restritas ao daemon, antes e depois da projeção dos contêineres. Cada candidato deve declarar somente essa rede e o modo nominal; a exceção de ID vazio exige StartedAt inicial, nenhum restart e restart=no. Ela vale também na retomada e nos checkpoints dos consumidores, que continuam nunca iniciados. O backend após start exige o ID efetivo. Rede ausente, renomeada, recriada, extra ou divergente recusa; não iniciar consumidores para obter um ID nem aceitar ID vazio sem essas provas. Com ID vazio e estado não-held (por exemplo, restart=always), a recusa é `candidate-network-mismatch`; a prova de rede não pode ser formada usando essa exceção. O ensaio local opt-in `deploy/tests/test_first_transition_candidate_network_docker.py` usa processos fictícios e limpa somente seus recursos identificados; não valida a aplicação nem autoriza janela real.

### Recuperação — API Python exata (somente local/sintética)

Sem CLI; nada executa no import. Os provedores (`connect`, `secret`, `ingress`, `writers`, `backup_proof`) são entradas da Fase 3 e aqui só existem como fakes de teste:

```python
from pathlib import Path
from first_transition_adapter import prepare
from first_transition_orchestrator import assemble, load_config
from initial_transition_files import Journal

config = load_config(Path('/caminho/first-transition.json'))  # só valores públicos
with Journal(Path(config.state_dir) / 'journal') as journal:   # mesmo diário em todo replay
    t = assemble(config, plan=prepare(Path(config.repo)), journal=journal, connect=connect, secret=secret,
                 ingress=ingress, writers=writers, backup_proof=backup_proof)
    r = t.recovery()      # só classifica: state, procedure, open_steps, legacy_resume_allowed; não age
    # conforme r['state']:
    #   not-started                                            -> nada a recuperar
    #   containment-partial / contained-pre-ddl                -> t.run()  (replay; contain() nunca re-sinaliza)
    #   contained-pre-ddl / resume-partial                     -> t.resume_legacy(t.host.resume_token())
    #   backup-window-used                                     -> sem novo pedido nem reuso; t.resume_legacy(...) e diário novo
    #   legacy-resumed                                         -> novo diário para nova tentativa
    #   ddl-ambiguous / ddl-failed / post-ddl-failed           -> parar; leitura read-only; restore do backup DA JANELA
    #                                                             (r['window_backup_id'], nunca o do A6), nunca automático,
    #                                                             ou correção por nova decisão
    #   candidate-ambiguous / candidate-failed                 -> parar sem desfazer; consumidores held; ingresso bloqueado
    #   a9-complete                                            -> manter; A10 exige autorização própria
```

**Entrada da janela (incremento 2, apenas código local, sem autorização operacional):**

- `first_transition_window.py prepare` recebe configurações públicas completas e o descritor explícito `--env-file`/`--env-var`; emite plan/window digests sem abrir credencial, banco, daemon ou diário. `--expect-plan-digest` e `--expect-window-digest` no modo `run` são checagens exatas contra erro, não aprovação humana; a autorização nominal continua externa à ferramenta.
- O mesmo `env_file_secret` (arquivo regular root-owned 0400/0600, sem symlink) alimenta observador, writers, `PGDUMP_URL` e `MIGRATION_DATABASE_URL` do filho. Nenhuma variável herdada ou `.env` de serviço é fallback. Modos operacionais e cada abertura de conexão recusam qualquer nome `PG*` herdado com o código fixo `database-libpq-environment`, antes de segredo/conexão/efeitos, sem revelar valores nem alterar `os.environ`; `prepare` continua puro. O Compose recebe `--env-file /dev/null` para impedir carregamento implícito; o candidato usa somente `PASTORAI_ENV_FILE` explicitamente configurado. Nunca registrar DSN ou conteúdo privado. A URI selecionada precisa conter identidade completa (host, usuário, senha e banco); service/options e campos de conexão alternativos recusam. O papel efetivo é conferido por leitura contra o usuário de migration do clone, owner do ledger e permissões básicas de CREATE/CREATEROLE, sem criar papel ou elevar privilégios na fonte.
- Antes do diário/contenção, conferir pacote/hash e layout/hold **já preparados**, binários/runtime, daemon/rede/bridge, IDs/escopos/Docker cruzados, imagens por digest/ID e revisão, plataforma e versões PG compatíveis, Compose efetivo com gates fechados/porta TCP 8000 em loopback e site nginx nominal presente em `nginx -T`. Ausência/incompatibilidade recusa, sem geração/reparo/download. O clone exige comando explícito com preload vazio ou somente módulos seguros permitidos; pg_cron/pg_net não integram esse perfil. Sites nginx complexos/ambíguos não são presumidos compatíveis.
- `window-init` é o primeiro evento e vincula configurações normalizadas da transição, backup e bindings e caminho/nome da variável da credencial, nunca seu valor. Replay não adota diário legado ou configuração diferente. Ingressos contidos são estados válidos de observação no replay; ambiguidades e falhas continuam decididas pelo controlador, sem retry/restore/retomada automáticos.
- `check-bindings` só observa e retorna não zero para escritor desconhecido positivo, recusa ou resposta inválida; ingresso aberto é observação válida, não quiescência. A entrada real exige `UnknownWriters` com o hook do incremento 1; a execução termina em A9 com `production_ready=False`, consumidores/ingressos contidos e A10 fora do escopo.

**Topologia nginx nominal:** validação pura exige um único `server` no nível zero, include de manutenção direto no server antes da única `location /`, um comando/chave por linha e exatamente um `proxy_pass http://127.0.0.1:8000`. Outros includes, passes, if/rewrite/return ou construções complexas recusam com `window-nginx-topology` para revisão manual, antes de IO externo. Observe/block/open repetem essa leitura fresca e a conferência existente do site em `nginx -T`; não abrem ingresso automaticamente. Dump e clone usam `--pull=never`, recusando imagem ausente sem download.

**Correções locais do incremento 3 (operação NO-GO):** roles NOVAS do clone são criadas NOLOGIN NOINHERIT, sem reproduzir privilégios/grants/senhas e sem corrigir silenciosamente roles preexistentes. O teste físico preparado reproduz as quatro identidades runtime somente no LocalDatabase sintético guardado. Projeção Docker descobre apenas variantes case-insensitive dos quatro gates, mantendo nomes para recusar variantes e duplicatas; arquivo com `export` e model Compose também recusam essas formas, mesmo fechadas. Readiness compara em memória o alvo de DATABASE_URL e das URLs opcionais preenchidas ao provedor único; revalidação privada do Env do backend criado ocorre antes da intenção de start. Só as formas PostgreSQL aprovadas e opções seguras são aceitas; overrides de rota e variáveis libpq recusam. Usuário/senha podem diferir, mas host normalizado/porta/banco devem coincidir; pooler Supabase também exige o mesmo sufixo de projeto no usuário. Não há equivalência presumida entre aliases, direto e pooler. Opcionais vazias/ausentes são NÃO AVALIADAS (somente contagem); nenhuma credencial é criada. URLs nunca integram diário/digests/saídas. Contagem de `server_name` considera o token nominal entre aliases.

**Projeções verificadas localmente:** campos Docker opcionais `State.Health` e `Mounts.Name` ausentes são representados como null, sem dispensar identidade/gates. Nomes nginx nominais entre aliases são comparados sem distinção de caixa e sem aspas externas. Os ensaios sintéticos não substituem o preflight integral do host.

**Limites:** testes simulados não provam acesso, permissões, capacidade, nginx/nft/Docker ou imagens reais, nem autorizam dados/produção. Arquivo nominal, sondas e sua correspondência em `nginx -T` não provam todos os outros sites/conf.d/listeners ou a configuração efetiva integral: **NÃO VERIFICADO operacional**, exige preflight nominal autorizado do host antes da janela. Endpoint ainda é resolvido na construção do binding; observações não dão atomicidade permanente. O código final do incremento 3 foi revisto pelo Claude sem P0/P1. A suíte PG17 sintética completa passou com 851 testes e 10 subtestes, sem falhas/skips, incluindo replay das 51 migrações. O primeiro ensaio, que falhou na migration 47 por INHERIT, permanece evidência histórica; o resultado final não constitui aceite A6 real nem substitui os quatro checks do CI do candidato. Comparar URLs é observação pontual de configuração, não prova criptográfica da conexão; `.env` dentro da imagem e configuração efetiva da aplicação são NÃO VERIFICADOS na prova A4/A5. Curingas/regex, outros listeners, porta 80, certbot, symlink e TLS fora do perfil nginx permanecem NÃO VERIFICADOS operacionalmente. A9 mantém health/gates conferidos e ingressos contidos; queue/cron/broadcast NUNCA iniciados; A10 exige autorização e aceite humano próprios em 20 conversas REAIS DISTINTAS, com capacidades desligadas NÃO AVALIADAS. A3 não implementa A10. Não executar estas operações a partir deste registro de desenvolvimento.

`t.run()` após `transition-failed` recusa (`transition-stopped`); após `ddl-marker`, `resume_legacy` recusa (`post-ddl-resume-forbidden`). Identidade de banco divergente após uma migration é registrada como ambígua (`definite=False`). Binding `writers`: devolve só escritores desconhecidos, isto é, fontes NÃO declaradas, e precisa devolver 0 em toda observação, inclusive na baseline com os quatro legados rodando. Fontes declaradas, nunca contadas: os quatro papéis legados do manifesto (a parada deles é provada à parte pelos estados do host: restart=no, saída 0), o observador e o filho de migration e, só a partir do início do backend no A9, o backend candidato. Consumidor candidato, outro container ou cliente externo contam e recusam. Zero sessões de escrita e zero leases no PostgreSQL são exigidos separadamente antes do `ddl-marker` e de cada migration; `observer_applications` nunca isenta sessão ativa no PostgreSQL.

Binding `backup_proof(request)`: chamado uma única vez por janela, depois da quiescência, com o pedido já gravado no diário (`transition-backup-request`: nonce novo, plano, identidade, baseline, config e digest do evento `transition-quiescent`). Deve devolver o recibo de um backup NOVO feito após esse pedido, com `request_digest` = digest do pedido, `backup_id` hex64 e os campos de restore/ensaio de clone de `validate_clone_receipt`. Um recibo do A6 não atesta o pedido e é recusado (`transition-backup-unbound`). O diário guarda só a cópia sanitizada do recibo, sem caminhos ou extras do provedor. Antes do `ddl-marker` ela é revalidada junto com a contenção e a quiescência, sem chamar o provedor de novo. Pedido sem recibo é ambíguo (`transition-backup-ambiguous`): não há nova solicitação automática, e uma segunda invocação nunca reutiliza a janela (`transition-backup-window-used`).

Prova de ledger (`LedgerProof`): compara ledger e impressão digital do catálogo do schema `public`. A impressão cobre relações/RLS/dono/ACL/views, atributos/defaults/generated/identity, constraints, índices/validade, triggers, rules, policies, funções, tipos/enums, sequências, extensões e privilégios, com hash no servidor. Ela prova igualdade do estado coberto agora, não que nunca houve DDL: objetos fora de `public`, objetos globais do cluster e alterações revertidas antes da observação não são cobertos. Ingresso: `ingress_blocked` e `ingress_open` são fatos separados (ambas as entradas bloqueadas/abertas). A retomada só conclui com ambas abertas, e o replay de uma abertura parcial abre apenas a entrada restante, com prova fresca.

## Fase 1 — transporte observado e consolidação enxuta (29/10/2026)

Sobre a `main` `64853268a4c1623f5b9d4906457335fcb7849931`, o plano de release passa a seguir os 5 pacotes de fase consolidados no `ROADMAP.md`, encerrando a construção de VM QEMU offline artesanal (A1/I0). O arquivamento dos artefatos temporários de `/tmp/igreja12-*-20261029/` fora do repositório é registro do operador e não foi reverificado nesta fatia.

- **Natureza desta fatia (A3 parcial):** contrato + encoder de comandos sobre driver fornecido pelo chamador. **Não** é executor real, inventário real, implementação de ingresso nem autorização operacional. A3 não está completa.
- **Contenção da fila durante a janela:** para evitar o cancelamento terminal de itens em `notification_outbox` pelo `cron-worker` ao fechar `ALLOW_REAL_SENDS=false`, a contenção da janela (Fase 4) para primeiro os quatro consumidores legados (`restart=no` + `SIGTERM` com espera de saída 0) antes da transição para o candidato com gates fechados. A verificação de quiescência ainda não tem ferramenta.
- **Contrato e transporte observados:** `ObservedHostTransport`/`ObservedHostContract` validam forma e identidades de metadados **reportados pelo driver** (dependências, serviços legados, escritores desconhecidos, contagens de filas, saúde); recibos são `evidence='driver-reported'`, `host_verified=False`, `quiescence_proven=False`. Contagens não comprovam conteúdo nem quiescência. `resume_legacy` pré-DDL revalida, antes de cada efeito e após cada observação, ausência de marcador DDL no diário, ingresso bloqueado e igualdade da fila antes do primeiro início efetivo (recibado, ou intencionado com `started` novo; `running` com `started` inalterado é recusado antes de efeitos). Cada efeito de retomada (`start`, `restart=always`, `open-ingress`) só é emitido após uma guarda pré-efeito aceitar a última observação do próprio transporte, sem nova leitura; sem guarda o transporte recusa. Não há atomicidade sobre driver/host: resta a janela entre essa observação e o efeito. A ausência de marcador no diário não prova ausência de DDL fora dele. O token `RESUME:` não é aprovação humana.
- **Composição proibida:** `LocalTransition` (banco local descartável) recusa `ObservedHostContract`, recibos `observed-host` e `LocalEvidence.observed` antes de observar o banco ou escrever no diário. Diários separados nos dois sentidos: `LocalTransition` (inclusive sem host) recusa diário com `observed-host-*` na construção e antes de cada execução; `ObservedHostContract` recusa diário com `adapter-*`/`local-host-*` antes de qualquer leitura ou efeito do port (marcador DDL mantém a recusa `post-ddl-resume-forbidden`).
- **Contenção parcial / saída anormal** (`exit≠0`, timeout de `wait`): recusa fail-closed, sem SIGKILL, retomada ou recuperação automática. O replay de `contain` não repete o sinal já intencionado para o mesmo papel, mas pode avançar a papéis seguintes após timeout (desligar restart, sinalizar e esperar outros serviços), portanto não é "sem efeitos". `resume_legacy` sobre contenção parcial recusa sem efeitos. A recuperação nominal manual é **bloqueador operacional** a definir e revisar.
- **Bloqueadores antes do Pacote 4:** driver real de inventário/ingresso/executor implementado e revisado; prova de BD (ledger) contra DDL; prova independente de ingresso/escritores; prova de fila/quiescência; procedimento de recuperação de contenção parcial; procedimento de recuperação de retomada parcial (serviços parcialmente de pé, ingresso bloqueado, sem recuperação automática).
- **Estado operacional:** nenhuma operação em VPS, banco de produção, Docker de produção ou publicação remota foi executada nesta Fase 1. `OPERATIONAL_AUTHORIZATION=BLOCKED` permanece ativo até os Pacotes 3 e 4 e os bloqueadores acima.


**Fechamento local em 30/10/2026:** 333 testes e 49 subtestes nas sete suítes sintéticas pertinentes (Python 3.13.15), Ruff e diff check aprovados. GPT-6.1-Sol High e Sarah Opus 5.5 High deram GO à PR parcial, sem P0/P1. Suíte completa dependente de PostgreSQL não verificada; CI obrigatório por SHA exato, com evidências na PR. P2 reconhecidas: port/diário do contrato observado como base de confiança; diagnóstico `adapter-failed` possível após contaminação de diário por callback no meio de execução local; matriz adicional de estados intermediários. O GO não é prova operacional. Pacote 1 autorizado nominalmente em 30/10/2026 cobre commit, push sem force e PR; sem merge, dispatch manual, deploy, reativação, VPS ou produção. Pré-publicação: DEV disabled_manually, DEV_PIPELINE_ENABLED=false, nenhum projeto Vercel ligado ao repositório, nenhuma publicação ativa nos projetos do painel e deploymentEnabled=false preservado.

## Fatia local — segurança do controlador (29/10/2026)

Base integrada `609952de`. Commit/push sem force e PR separada autorizados
em 29/10/2026, após reconferir suspensões; merge não autorizado.
Sem dispatch manual, deploy, reativação, novos ensaios físicos locais, VPS
ou produção. OPERATIONAL_AUTHORIZATION=BLOCKED para essas operações.
Pré-publicação: DEV disabled_manually e DEV_PIPELINE_ENABLED=false; painel
Vercel sem vínculo Git, nenhum projeto vinculado a este repositório na equipe,
nenhuma publicação em andamento; deploymentEnabled=false preservado.
Quatro checks obrigatórios app15368, strict=true e enforce_admins=true.
Abertura da PR aciona seis workflows de testes, incluindo recursos sintéticos
descartáveis no GitHub; não aciona publicação/deploy. Evidências de CI ficam
na PR por head exato; a validação local não as substitui.
Sinais SIGINT/SIGTERM/SIGHUP geram relatório e limpeza limitada; segunda
interrupção encerra a tentativa de limpeza. Subprocesso CLI próprio é encerrado
com espera limitada, nunca grupo alheio. Falha primária permanece fail.
CID ausente/vazio nunca é adotado por nome: preserva resíduo para recuperação
nominal. Mutação sem resposta confirmada deixa registro pending persistente;
mesmo ps vazio não comprova limpeza e retorna incomplete. Não apagar o registro
para forçar sucesso. Limpeza-only não resolve incerteza por conta própria.
Após decisão nominal sobre o resíduo, registrar o desfecho em relatório novo
e usar novo run/estado; preservar o estado incerto como evidência.
Remoção exige ID do cidfile do run, nome e label; varredura residual por label
apenas acusa recursos, nunca remove desconhecidos. Estado exclusivo persistente
0700 fora de árvores com marcador .git, sem symlink ou componentes ..; lock exclusivo e intent atômico antes de create; scope
vinculado a imagem/run/daemon. Primeiro sinal durante cleanup permite concluí-la;
segundo a interrompe. CLI em nova sessão, sinal durante spawn é diferido até
registrar o filho. Janela de reaping tem até dois segundos além do timeout.
Modos com efeito agora exigem --state-dir e --daemon-id além de --run-id/--report;
cleanup-only lê o estado original e exige relatório novo. Comandos históricos
sem esses argumentos não devem ser reutilizados. Nenhum desses modos executado.
Overrides remotos/contextos recusados antes de processos; config Docker vazia,
socket fixo e daemon nominal/Linux não-rootless conferidos antes de mutação.
Isso reduz uso acidental, não comprova isolamento: socket pode ser túnel e o ID
aprovado precisa pertencer a ambiente descartável. VPS/produção proibidos.
Snapshot inicial recusa com código fixo sem DDL ou detalhes de driver.
Pins SQL/executor, migrations e gates intactos; backup muda adapter_sources/
plan_digest, recibos anteriores recusados por plan-changed. Não contornar.
Testes só com doubles e sentinelas anti-processo/rede; PG, Docker, sinais reais,
SSH e provedores não executados. Validação local: 162 testes e 2 subtestes
aprovados; Ruff e git diff --check aprovados. CI automático acompanha a PR.
Revisão final Sarah e limites registrados na entrega.
Nenhuma nova autorização operacional é concedida pelo código/documento.

Quatro P2 corrigidos localmente: interrupção abortável somente durante
communicate, no máximo uma exceção por espera e sem substituir exceção em
propagação; poll/reaping protegidos; relatório exclusivo 0600 fora de checkout,
sem symlink ou ..; testes de symlinks, dono do lock e falhas concorrentes.
Pending correlaciona operação, índice, nome e ID conhecido. Cleanup informa
códigos sanitizados por recurso; registro antigo/inválido vira pending-unverified.
Nenhum texto arbitrário de erro/estado é copiado para o relatório.
Revisão Sarah Opus 5.5 high concluída: GO local, P0=0/P1=0/P2=0;
quatro P2 fechados por leitura dos bytes enviados. Revisora não executou testes.
Limites: sinal pode ser adiado até timeout; reaping pode falhar; sinal antes
de instalar handlers pode deixar relatório vazio, sem efeito Docker. Parecer
e manifesto no pacote local controller-safety-p2-20261029. Sem autorização operacional.


### Recuperação nominal de resultado incompleto (procedimento, não autorização)

1. Preserve state-dir, scope.json, intents, cidfiles, pending e relatório original;
   não edite ou apague registros para transformar incomplete em clean. Leia
   cleanup.details: índice/nome vinculam o item ao scope; pending-* indica
   resposta não confirmada; pending-unverified exige análise do registro original.
2. Antes de qualquer consulta ao runtime, apresente para aprovação o daemon
   descartável nominal, run_id, imagem, recursos e comandos exatos. Não inferir
   identidade pelo nome/label nem reutilizar esses comandos em VPS/produção.
3. Somente após aprovação, confronte metadados atuais com scope e CID completo.
   cleanup-only usa estado original e relatório novo, e remove apenas identidades
   comprovadas. CID ausente/vazio/trocado/symlink preserva o recurso; decisão
   manual deve identificar separadamente o recurso e autorizar eventual remoção.
4. Um pending continua bloqueando clean mesmo com inventário vazio: pode haver
   efeito tardio. Registrar decisão humana e evidência posterior de cada item
   em relatório separado. Não reciclar esse estado; uma nova tentativa usa
   novo run_id, novo state-dir e novo relatório, após aprovação específica.
5. Sem evidência suficiente, o encerramento permanece incompleto. SIGKILL,
   perda de energia, falha de disco, reaping que falha e troca adversarial de
   ancestrais de caminhos não são garantias cobertas pelos testes simulados.
   Diretórios ancestrais devem estar sob controle do operador aprovado.



## Estado vigente — #601 integrada e publicação da #602 autorizada (29/10/2026)

#601 integrada por merge commit `19eae0b0c140ea36d7ea93a5874867bf53c34f70`,
head autorizado `83f962a1`, sem bypass ou exclusão da branch. Os seis workflows
push da nova main passaram: backend40828306185, frontend40828306170,
E2E40828306164, RLS40828306174, tooling40828306177, sintético40828306165.
Nenhum dispatch manual executado. A PR601 havia aprovado 98 testes do adaptador
no CI, sem skips, com PostgreSQL descartável removido; isso não valida a #602.

Candidato #602: composição do head `af5158d5` com esta main; commit/push sem
force, base main e acompanhamento CI autorizados pelo dono em 29/10.
Conflitos de testes resolvidos preservando as duas séries; Vercel false global
herdado da main intacto. DEV disabled_manually e DEV_PIPELINE_ENABLED=false,
Vercel Git desvinculado e nenhuma publicação ativa na conferência pré-merge.
Código do probe não foi executado fisicamente. Apenas simuladores nos testes.
Validação local: 99 passed, 2 subtests, sem skips; testes PG ainda não executados
nesta composição. Resultados físicos/CI de 28/10 são históricos, não transferíveis.
Sarah Opus 5.5 high: GO local, P0=0/P1=0; revisão sanitizada sem ferramentas.
Pendências antes de ampliar/executar novamente o transporte: SIGTERM/SIGHUP do
controlador podem impedir finally e deixar fixtures com restart=always;
conferência residual por label ainda não implementada; snapshot inicial de backup
pode propagar erro de driver antes do marcador. Probe usa socket Docker local
sem guarda técnica de host: não executar em VPS. A allowlist explícita de
`deploy/package_backend_release.py` exclui `rehearse_first_transition_commands.py`.
Limites registrados, sem implementação/ensaio adicional nesta preparação.

CI do novo head pendente nesta gravação; evidências finais na PR #602.
Sem autorização de merge, dispatch manual, deploy, reativação, ensaios físicos
locais, acesso VPS ou produção.

Restam integração autorizada da #602 com CI do futuro head, proposta de topologia
sintética e aprovação nominal de qualquer execução operacional. 51 migrations
não foram aplicadas em produção. Transporte real/ingresso/filas, backup/restore
operacional, preflight atual, janela/SHAs/contingência e retomada do piloto seguem
pendentes. Registros abaixo são históricos e não concedem autorização vigente.


## Histórico — preparação e publicação da #601 antes da integração

#600 integrada por merge commit `60e29d142040ebc5b21c35af18884b2449321308`,
head autorizado `da1cc2e0`, sem bypass, git push manual ou exclusão da branch. Dono aceitou
explicitamente a lacuna histórica da main `ed7f4c10`; isso não cria CI retroativo.
Seis workflows automáticos event=push aprovados no SHA novo: backend
40822044870, frontend 40822045020, E2E 40822044871, RLS 40822044970, tooling
40822044886 e sintético 40822045064. Nenhum dispatch manual autorizado ou executado.

#601: dono autorizou commit/push sem force e base main, a partir do head
original `84366305` e da composição local com a main acima. Conflitos resolvidos preservando ensaio das 51 migrations no
clone, identidade cluster/OID/owner antes da limpeza FORCE, todos os testes das
duas séries e Vercel deploymentEnabled=false global herdado da main, sem alteração. Recibos de índices e recusa
de adoção sem recibo da #600 preservados. DEV continua disabled_manually e
DEV_PIPELINE_ENABLED=false; nenhum gate operacional alterado.

Validação do candidato: 85 testes/2 subtestes offline e Ruff aprovados;
nenhum banco/contêiner local executado. Testes PostgreSQL da composição ainda
não verificados: dependem de publicação autorizada e CI do futuro head.
Sarah Opus 5.5 high: GO de preparação local, sem P0/P1 após correção documental.
A limpeza FORCE também cobre clone reivindicado ainda sem marcador após falha
de COMMENT, somente no cluster privado descartável e com identidade preservada.
DDL de roles no clone afeta o cluster: não comprova criação independente na fonte.
Comando offline executado (Python 3.13, sem arquivo PG):
`PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 uv run --offline --no-project --python 3.13 --with pytest python -m pytest --noconftest -p no:cacheprovider -o addopts= -q deploy/tests/test_first_transition_adapter.py deploy/tests/test_first_transition_host_contract.py deploy/tests/test_backend_workflow.py deploy/tests/test_dev_pipeline.py`.
Ruff verificou adaptador, backup, contrato, transporte, launcher e os três
arquivos de testes do adaptador/PG/contrato, sem execução dos testes PG.
CI do novo head pendente nesta gravação; evidências finais na PR #601.
Sem autorização de merge, dispatch manual, deploy, reativação, ensaio físico
local, VPS ou produção.
Registros de autorização e resultados anteriores abaixo são históricos.


## Recuperação manual dos cinco workflows de teste

Estado: preparada sobre #600 `3e3375ed`; commit/push sem force na própria PR
e acompanhamento do CI automático autorizados pelo dono em 29/10. Evidências
do novo head serão registradas na PR após execução. Merge e dispatch manual
não estão autorizados; revisão externa permanece com Sarah Opus 5.5 high.
São cinco linhas `workflow_dispatch:`, uma em cada arquivo:
`backend-tests.yml`, `frontend-ci.yml`, `rls-integration.yml`,
`tooling-static.yml`, `synthetic-release.yml`. E2E já permite disparo manual.
O conjunto completo de CI continua sendo seis workflows: os cinco acima mais
E2E já existente. Estes cinco gatilhos novos não mudam a elegibilidade de DEV:
`check_integrated_candidate.py` consulta `event=push`; dispatch verde não
substitui push ausente/falho para promoção. Esse gate foi mantido byte-exato. Tooling-static integra os seis workflows
acompanhados, mas não integra a lista de cinco exigida pelo gate DEV existente.
Dispatch aprovado fornece evidência para revisão humana, sem tornar DEV elegível.
Jobs, scripts, versões, permissions `contents: read`, timeouts, triggers de
push/PR e concorrência ficam iguais. Nenhum workflow de publicação/monitor
é habilitado, editado ou disparado; não há encadeamento `workflow_run`.
Vercel/DEV e gates continuam suspensos conforme decisão vigente.

### Dependências e limite do SHA

1. Commit/push na própria #600 está autorizado nesta etapa. O push acionará
   os testes de PR já existentes, inclusive PG/containers efêmeros no runner,
   e produzirá um novo head cujo CI terá de ser conferido.
2. Merge depende de autorização nominal separada, sem bypass, e de decisão
   explícita sobre a lacuna histórica da main `ed7f4c10`.
3. Depois de integrado, os gatilhos ficam na branch padrão. O push da nova
   main normalmente aciona os testes; só repetir manualmente se necessário,
   autorizado e sem execução concorrente do mesmo workflow na main.
4. Isso não dá workflow_dispatch ao commit antigo `ed7f4c10` nem reconstitui
   o evento perdido. Um run sobre uma nova main prova apenas o SHA novo.
   Não usar checkout de um input SHA sob workflow de outro commit como prova
   de que o run/check pertence ao SHA antigo.

Referências oficiais: [execução manual](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
e [REST workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).
A API documenta `ref` como branch ou tag. A proposta usa `--ref main`, sem
prometer dispatch por SHA avulso ou criar tags/branches auxiliares.

### Comandos futuros — NÃO executados nesta preparação

Após autorização de dispatch na main já integrada, preencher o SHA completo
revisado. Primeiro conferir os metadados e runs ativos (queued, pending,
waiting ou in_progress); se houver qualquer execução do workflow na main,
não disparar outra. A concorrência existente cancela execução anterior.

```bash
repo='haniellevi/PastorAI-LionClaw-V1'
expected_main='<SHA_COMPLETO_DA_MAIN_INTEGRADA_E_AUTORIZADA>'
test "$(gh api "repos/$repo/git/ref/heads/main" --jq .object.sha)" = "$expected_main"
for workflow in backend-tests.yml frontend-ci.yml rls-integration.yml tooling-static.yml synthetic-release.yml; do
  gh api --paginate "repos/$repo/actions/workflows/$workflow/runs?branch=main&per_page=100" \
    --jq '[.workflow_runs[] | select(.status != "completed") | {id,event,head_sha,status}]'
done
```

Somente após confirmar listas vazias e o término dos runs de push, executar
um workflow por vez. Repetir o procedimento para cada um dos cinco nomes acima.
Registrar workflow, ator esperado, instante anterior ao comando e URL/ID se
retornada. Não presumir que a CLI sempre retorna o ID; nunca escolher apenas
"o último run". Havendo mais de um candidato compatível, parar e identificar
a execução inequivocamente antes de contar qualquer resultado.

```bash
workflow='backend-tests.yml' # repetir para os outros quatro arquivos
expected_actor="$(gh api user --jq .login)"
test "$(gh api "repos/$repo/git/ref/heads/main" --jq .object.sha)" = "$expected_main" || exit 1
dispatch_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
gh workflow run "$workflow" --repo "$repo" --ref main || exit 1
gh run list --repo "$repo" --workflow "$workflow" --branch main \
  --event workflow_dispatch --commit "$expected_main" --created ">=$dispatch_started" \
  --json databaseId,workflowName,headBranch,headSha,event,createdAt,status,conclusion,url
```

Para cada ID efetivamente criado, acompanhar e conferir:

```bash
run_id='<ID_DA_EXECUCAO_CRIADA>'
gh run watch "$run_id" --repo "$repo" --exit-status
gh run view "$run_id" --repo "$repo" \
  --json databaseId,workflowName,headBranch,headSha,event,createdAt,status,conclusion,url
gh api "repos/$repo/actions/runs/$run_id" \
  --jq '{id,workflow_id,path,head_sha,head_branch,event,created_at,actor:.actor.login,repository:.head_repository.full_name,status,conclusion,html_url}'
```

Aceitação: cada um dos cinco workflows deve ter `headSha == expected_main`,
`headBranch == main`, workflow/caminho esperado, repositório correto,
`createdAt >= dispatch_started` (relógio local deve estar sincronizado;
se houver desvio, investigar o ID e horário do servidor, sem escolher por recência), ator igual ao registrado e evento
`workflow_dispatch`, `status == completed`, `conclusion == success`;
registrar IDs e URLs, jobs obrigatórios e app_ids esperados. Revalidar a main
no fim. E2E também precisa de sucesso no mesmo SHA (push ou dispatch), sem
transferir o resultado de `ed7f4c10`. Se a main mudar entre consultas ou um run
resolver outro SHA, parar e não contá-lo para o alvo autorizado. Não há trava
atômica entre consulta e dispatch: a checagem do run é obrigatória. Runs de PR
podem usar merge de teste; conferir pais/árvore e não chamar isso de CI da main.

Revisão final Sarah / Claude Code `claude-opus-5-5`, esforço high: GO para
este plano local sobre `3e3375ed`, P0=0/P1=0. Sarah leu pacote sanitizado e não
executou testes. Duas sugestões futuras no gate DEV (filtro local de evento e
paginação) não alteram este diff; o gate permanece byte-exato. Sem commit,
push, merge, dispatch ou novas autorizações operacionais.

### Recursos, efeitos, recuperação e limpeza

Usa GitHub-hosted ubuntu-24.04, minutos de Actions, downloads de dependências,
Docker/PG17 descartáveis e artefatos de teste. RLS usa quatro shards e um
agregador; synthetic-release faz troca/recuperação de processos apenas em
containers sintéticos do runner. Não acessa VPS ou dados reais. Não é um ensaio
físico local. Limpeza existente dos recursos efêmeros e descarte do runner
permanecem; conferir os logs de cleanup. Não promete retenção zero de artefatos.

Falha, cancelamento ou timeout não contam como verde. Investigar logs do SHA,
sem afrouxar critérios/gates. Não repetir enquanto houver run ativo. Cancelar
ou repetir uma execução exige escopo autorizado; não cancelar automaticamente
trabalho alheio. Retirar só os cinco gatilhos seria uma futura mudança de código
revisada/autorizada; não desabilitar workflows inteiros e não reativar DEV/Vercel.

Validação desta preparação: parsing YAML e comparação estrutural com o head;
retirar a única linha adicionada reproduz os bytes anteriores de cada workflow.
65 testes e 30 subtestes de contratos offline passaram; três cenários com
fetch simulado confirmaram que dispatch não substitui evidência push no gate DEV
(push ausente, push falho e push aprovado). Nenhum teste de runtime, banco,
container ou comando de dispatch foi executado. Corrida entre consultas ainda
existe; run cancelado/ambíguo não conta. Preferir push e usar dispatch só como
recuperação evita custo e cancelamentos desnecessários.

**Correções da revisão automática da #600 — 29/10:** retomada compara presença
e definição (hash de pg_get_indexdef) dos índices concorrentes com recibos do
diário; divergência recusa sem reparar. Índice concorrente sem recibo após crash recusa retomada; não adota definições
sem prova. Reobservação final confere os recibos antes de declarar conclusão.
Backup sintético captura cluster/OID/proprietário antes de marcar o clone;
limpa falha de comentário somente com identidade preservada. Falha antes de
capturar identidade mantém recusa de limpeza, exigindo recuperação nominal.
Sete regressões PG adicionadas para o CI; nenhum banco local executado.
Subprocesso do teste SIGKILL agora desabilita bytecode. Testes offline do Codex:
50 aprovados e 10 subtestes; Sarah revisa o diff sanitizado, sem executar testes.
Main ed7f4c10 tem E2E manual aprovado (40814255271); cinco workflows sem runs
no SHA exato, sem dispatch. Não declarar main verde nem transferir checks de
árvore equivalente. Publicação e correções da #600 autorizadas, merge não.

**Atualização vigente — #599 integrada em 29/10/2026.** Merge commit
`ed7f4c10104f4537b8918000c0868992245b9429`, head autorizado `9e0dbda9`.
Checks obrigatórios verdes, sem bypass e branch preservada. Vercel/DEV seguem
suspensos. A atualização da #600 sobre esta main foi autorizada para commit/push normal,
base main e CI, sem merge ou publicação das demais PRs.
Conflito Vercel resolvido preservando deploymentEnabled=false global da main;
o bloqueio antigo por branch da #600 não substitui a suspensão global.
Código do adaptador e SHAs pinados afdfb78d/37c7d68d preservados. Leitor Git
com modo estrito opt-in e empacotador da #599 preservados. Resultados do novo head na PR #600; checks anteriores não validam este candidato.
Sarah Opus 5.5 high: GO para futura publicação/CI, sem P0/P1;
50 testes e 10 subtestes offline aprovados, Ruff aprovado. CI de push da main ausente; E2E manual aprovado, cinco workflows
ainda não executados no SHA exato. Main não declarada verde. SHAs pinados comprovados
ancestrais da nova main; recibos antigos não validam o novo digest dos módulos.
Chave PGDG segue obtida da fonte oficial por HTTPS sem fingerprint pinado;
client 17 sem patch fixado: risco residual de suprimento restrito ao runner efêmero.
Consulta oficial: https://wiki.postgresql.org/wiki/Apt. Não é gate operacional. Sem deploy, reativação, novo ensaio
físico local, VPS ou dados de produção. Registros divergentes abaixo são históricos.

**Revisão Sarah — Opus 5.5 high:** orientação vigente do dono: trabalhar
com Sarah como revisora crítica e cética, confrontando seus achados com evidências,
sem concordância automática. Sua revisão não concede autorização operacional.
Na #599, revisão inicial pediu recusa de arquivos inesperados, permissões
explícitas e prova do empacotador real no CI. Correções: exclusão documental
explícita, diretórios 0755 e extração com permissões do pacote, Python 3.13.14
fixado no workflow manual e execução da CLI real sobre o SHA do CI.
35 testes e 10 subtestes locais passaram, Ruff aprovado; sem ensaio físico.
A hipótese de diretórios root impedirem appuser foi limitada pela evidência
de chown no Dockerfile; ainda assim as permissões agora são determinísticas.
Inventário atual: backend/app somente Python; fora de Python/SQL nas árvores
selecionadas existe apenas backend/migrations/README.md. .env.example aparece
só como comentário do Compose, não é dependência executada do pacote.
O build físico histórico de afdfb78d não valida este head; nenhum novo build
físico foi executado. CI/revisão finais constam na PR #599 e não autorizam merge.

**Atualização vigente — #598 integrada em 28/10/2026.** Merge commit
`beb194f930eecd5bf7df744bd6e23eaa88d04b4b`, head autorizado
`083c3f9ec720af1dfe3917980f4b68499c4a920b`. Seis workflows verdes no
head e na main anterior antes do merge, sem bypass e com branch preservada.
A #599 foi composta localmente sobre essa main, sem conflitos, preservando
seu código original `b3d93473` e as suspensões Vercel/DEV da main.
Validação local em Python 3.13: 26 testes e 8 subtestes passaram; Ruff aprovado.
Atualização autorizada para commit/push sem force push, base main e CI da #599.
Nenhum merge ou publicação das demais PRs autorizado. Resultados do novo head
na [PR #599](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/599);
checks antigos não validam o novo candidato. Os registros
anteriores são históricos quando divergirem deste estado. Nenhum deploy,
reativação, novo ensaio físico local, acesso à VPS ou dados de produção.
SQLs e aplicador pinados nos ensaios anteriores não são repinados.

**Atualização vigente — #597 integrada:** main
`940ac49ef82eedf7a67da666fab8435c12f7d760`, merge commit do head `8542e991`,
seis workflows verdes antes da integração. Proteções e suspensões preservadas.
#598 preparada sobre essa main, sem conflitos; atualização autorizada para
commit/push sem force push, base main e acompanhamento do CI;
código/fixtures idênticos ao head original `37c7d68d`. Validação
offline em Python 3.13: 46 testes unitários, Ruff e sintaxe aprovados. Apenas documentação de
estado reconciliada. Resultados do novo head na PR #598; nenhum merge adicional ou publicação das
demais PRs autorizado. Sem deploy, reativação ou ensaio físico local.
SQLs e aplicador pinados nos ensaios anteriores não são repinados por este merge.


**Atualização vigente de integração — 28/10/2026:** #603 integrada pelo merge
`e2eb2d04f08caf46f676a4f560acc77a61c5e351`. Proteção da main agora exige somente
backend-tests, frontend-ci, e2e-critical e rls-integration (app_id 15368), com
strict=true e enforce_admins=true; demais regras preservadas. Vercel Git segue
desconectado e DEV desabilitado com variável false. Publicações não reativadas.
A #597 foi composta sobre a main resultante, preservando suspensão, painel e
documentos; sua atualização recebeu autorização de commit/push sem force push
e CI próprio. Resultados do novo head na PR #597; não transferir checks antigos.
Nenhum merge da #597 nem publicação/merge das demais PRs autorizado. As seções
de preparação anteriores são histórico. Não repinar SQL/aplicador por causa
desta atualização.


## Suspensão das publicações automáticas — aplicada, integração pendente

Decisão do dono em 28/10: suspender publicação automática do painel e promoção
DEV antes da integração #597–#602. Autorização posterior cobriu suspensão remota,
verificação e, depois dela, commit/push/PR e CI. Não cobre merge, deploy, novos
ensaios físicos locais, VPS ou dados de produção.

Resultado verificado em 28/10/2026: workflow `380485201` desabilitado manualmente;
variável booleana antes ausente agora false; vínculo Git do projeto
`prj_e0hSMDbhUty2OK372oPcSQBXBKGE` desconectado. Metadados confirmam mesmo projeto,
seis domínios e último deployment `dpl_AeABTdSidFDtNVSXumMeTfm857Wb`, READY.
Nenhuma publicação pendente foi encontrada; não houve cancelamento. Não foi
feito teste funcional do site ou acesso a dados de domínio.
O conector não expõe a desconexão; usada CLI oficial Vercel 65.5.0 em cache
temporário, com autenticação existente sem exibir credenciais. Comando aplicado:

```bash
vercel git disconnect --project prj_e0hSMDbhUty2OK372oPcSQBXBKGE --scope raniel-levis-projects --yes
```

Mudança versionada: `frontend/vercel.json` com `git.deploymentEnabled=false`
(todas as branches, incluindo previews); `dev-synthetic.yml` sem `workflow_run`,
apenas `workflow_dispatch`, mantendo main, variável habilitadora e verificação
dos checks do candidato. Workflows de CI não são modificados. Isso não interrompe
o painel já servido nem os serviços existentes. Não bloqueia publicação manual
via CLI/API/deploy hooks; esses caminhos continuam fora da autorização.

### Procedimento autorizado e executado — registro e reconferência

1. Confirmar por metadados o projeto Vercel do painel
   `prj_e0hSMDbhUty2OK372oPcSQBXBKGE`, equipe `raniel-levis-projects`, vínculo Git,
   configuração do workflow DEV e execuções de publicação em fila/andamento.
   Não ler variáveis secretas, logs pastorais, VPS ou dados de domínio. Registrar
   o estado anterior da variável booleana e se ela estava ausente.
2. Suspender somente o workflow de publicação DEV e definir a variável como false:

   ```bash
   gh workflow disable dev-synthetic.yml --repo haniellevi/PastorAI-LionClaw-V1
   gh variable set DEV_PIPELINE_ENABLED --body false --repo haniellevi/PastorAI-LionClaw-V1
   ```

   Não desabilitar GitHub Actions globalmente. Isso não cancela execução já
   iniciada: se houver uma, parar a sequência e apresentar ID, estado e impacto
   para decidir cancelamento/recuperação, sem acessar o host.
3. No projeto Vercel confirmado, Settings → Git → Disconnect (ou CLI acima): desconectar
   temporariamente somente o vínculo Git do painel. Efeito: parar publicações
   automáticas por Git, incluindo previews das outras branches; preservar
   projeto, domínios e deployment atualmente servido. Não remover integração
   GitHub da organização nem excluir/pausar o projeto. Se a interface/capacidade
   disponível divergir, reapresentar a ação concreta antes de substituí-la.
   Publicações já iniciadas e deploy hooks exigem avaliação separada.
4. Conferir por metadados workflow desabilitado, variável false, vínculo Git
   desconectado e ausência de publicações pendentes. Registrar evidências;
   não presumir suspensão apenas por sucesso do comando.
5. Após confirmação, publicação da PR autorizada: [PR #603](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/603)
   independente sobre main, com CI. Reutiliza o lock de auditoria já corrigido
   na #597 (msgpack 1.2.3, arquivo idêntico); runtime da aplicação inalterado. Seu merge exige autorização própria. Integrá-la antes
   de #597–#602, preservando `deploymentEnabled=false` ao resolver o conflito
   esperado com os arquivos adicionados nas #600–#602. A #597 também atualiza
   ROADMAP: preservar a decisão vigente e os demais registros novos.

### Recuperação e retomada

Falha parcial mantém as suspensões já efetuadas; não reativar automaticamente
para desfazer uma etapa. Registrar exatamente o que foi aplicado e o que falta.
Não apagar deployment, domínio, imagem, volume ou dado. Suspender automação não
é desligar o sistema em uso, nem prova de contenção de filas.

Para retomar futuramente, obter autorização específica: restaurar o vínculo Git
registrado somente com as regras Vercel revistas na main; reabilitar o workflow
DEV apenas quando desejado, preservando o modo manual e a variável false até
aprovação de publicação. Reativação automática exigiria outra mudança de código.
Uma reconexão pode gerar eventos: antes dela, conferir regras, commits e filas.
Não reverter cegamente toda a PR, pois isso reintroduziria os gatilhos automáticos.

Referências: https://vercel.com/docs/project-configuration/git-configuration e
https://vercel.com/docs/cli/git. Consultadas somente como documentação pública.

Atualizado em 27/10/2026: a seção "Plano e prévia atual" vale para o candidato
`afdfb78d71a53f2861632806e13cdda4662d7d63`. As seções datadas de 24/10/2026
(`main` em `354a83d`) e anteriores são históricas.

Este runbook prepara a janela de release das migrations acumuladas e do
backend. Ele não autoriza nem executa acesso a PROD. Use também o
[runbook de produção](PRODUCTION-RUNBOOK.md), o
[runbook de backup](BACKUP-FIREWALL-RUNBOOK.md), o
[manual do release de backend](../../deploy/BACKEND-RELEASE-MANUAL.md) e o
[aplicador de migrations](../../backend/migrations/README.md).

## Plano e prévia atual (27/10/2026) — pronto para revisão, não para execução

**Estado: PLANO REVISADO (Codex + segunda opinião independente), NÃO
para execução**, porque o adaptador real da transição inicial ainda não existe
(ver "Bloqueador principal"). O planejamento continua no `ROADMAP.md`; esta é
a seção operacional do runbook existente, não um plano paralelo.

**Autorização:**
- **Já autorizado pelo dono em 27/10:** preparar este plano e fazer as
  leituras somente leitura usadas abaixo.
- **Aguardando aprovação:** toda ação de escrita em PROD, ou seja, backup de
  janela, contenção, migrations, deploy e smoke com efeitos.
- **Forma da aprovação:** uma única autorização nominal futura pode cobrir a
  lista exata das 51, as ações da janela descritas aqui e os SHAs explícitos
  (aplicação e adaptador). Não é preciso confirmar migration por migration.
  Nada é aplicado agora.

- **Candidato proposto da aplicação:** `afdfb78d71a53f2861632806e13cdda4662d7d63`,
  a `main` com #577–#596. Os quatro checks da `main`, o head da #596 e a
  Vercel estão aprovados.
  - **Manifesto das 51:** conferido em 27/10, com nome, flag CONCURRENTLY e
    SHA-256 por arquivo. Os 51 hashes conferem com os blobs do candidato.
  - **Se a `main` ou o candidato mudarem:** renovar o SHA, as evidências e o
    manifesto antes de aprovar.
- **Alvo:** o Supabase PROD e a VPS `srv2031318`.
- **Datas:** as seções datadas de 24/10 e anteriores são históricas.

### Prévia de impacto para aprovação futura

| Item | Antes, conferido em leitura | Esperado após o release aprovado |
|---|---|---|
| Igreja, acesso mestre e Pessoa | 1 de cada, vínculo utilizável | Preservar os mesmos registros e vínculo |
| Planos e papéis administrativos | 4 planos, 2 papéis, 1 admin de plataforma | Preservar cadastro de planos e papéis do acesso |
| Migrations ativas | 78 aplicadas, 51 pendentes | 129 registradas, nenhuma ativa pendente |
| Login | `auth_sessions` ausente | Tabela criada; sessões antigas sem `jti` exigem novo login |
| Identidades privadas | 4 roles ausentes | 4 roles NOLOGIN; provisionamento e ativação separados |
| VPS | Instalação legada, 4 serviços | Aplicação no SHA aprovado, layout rastreável e 4 serviços saudáveis, condicionado ao adaptador revisado |
| Redis, fila de falhas | 2 itens | Preservados; nenhuma limpeza ou tentativa de reenvio neste release |
| Correção de acesso duplicado | Cancelada, zero duplicidades | Não executar; apenas reconferir ausência antes do índice único |

Esta é uma **prévia de impacto**, não aplicação nem ensaio completo do lote
atual. As migrations acrescentam tabelas, funções, RLS e grants e restringem
privilégios de banco conforme a lista abaixo; preservar papéis do usuário não
significa manter todos os grants antigos. Não há novo reset autorizado.

### Fatos lidos em 27/10 (somente leitura, sanitizados)

Leitura de 27/10, por volta de 15:20 UTC, sem PII nem UUIDs. **Não é a
execução integral de `release_preflight.py`.**

**Banco (PostgreSQL 17.6)**
- **Sessão de leitura:** transação `REPEATABLE READ READ ONLY`, com role capaz
  de contornar RLS e tabelas centrais presentes.
- **Migrations:** 129 ativas no candidato, 78 registradas no ledger, 51
  pendentes e 0 desconhecidas. As 5 pausadas (`OPERATIONAL_AUTHORIZATION=BLOCKED`)
  ficam fora da seleção e nenhuma delas está aplicada.
- **Dados:** `invalid_cell_links=0` e duplicidade `(igreja_id, pessoa_id)`
  com 0 grupos, **depois do reset feito externamente pelo dono**.
- **Objetos ainda inexistentes, como esperado antes das migrations:**
  - `public.auth_sessions`;
  - as quatro roles de runtime (`private_storage_runtime`,
    `private_send_runtime`, `private_summary_runtime` e
    `queue_worker_runtime`);
  - os 10 contratos privados SECURITY DEFINER.

  Ausência aqui não é achado de dono: esses contratos serão examinados pelo
  preflight depois da aplicação.
- **Contagens agregadas:** 1 igreja, 1 usuário, 1 Pessoa, 4 planos, 2 papéis e
  1 platform admin. O usuário mestre é utilizável e está ligado a uma Pessoa
  da mesma igreja; há 1 admin de igreja utilizável e 1 platform admin
  utilizável.
- **Preservação de configurações, planos e permissões:** é uma alegação humana.
  As contagens não provam igualdade de conteúdo.
- **Backfills e filas no banco:**
  - backfills das migrations 1 e 2: **0 candidatos** cada (consulta agregada
    dos predicados, somente leitura);
  - `messages`, `notification_outbox` e `work_queue`: 0 linhas;
  - índices inválidos em `public`: 0; FKs `NOT VALID`: 0.
- **Configuração do agente:** 1 registro, com 1 `ativo`. A configuração viva
  da Jev **não foi lida**.
- **`statement_timeout=10s`:** foi `SET LOCAL` da própria consulta de leitura.
  **Não é** limite verificado da sessão que vai aplicar, nem configuração
  global. O valor efetivo para a DSN do aplicador não foi verificado.
- **Checagem de tabelas esperadas no backup:** 0 esperadas e 0 ausentes,
  porque cobre só o recorte posterior à base de 14/10.

**VPS `srv2031318`**
- **Containers:** `backend`, `queue_worker`, `cron_worker` e
  `broadcast_worker` estão `running`, todos na mesma imagem
  `sha256:4a65f30e…b241`, sem label de revisão e com `restart_count=0`.
  - Os três primeiros iniciaram em 24/10 às 01:13 UTC; o broadcast, avulso,
    em 23/10 às 20:54 UTC.
- **Topologia:** 3 serviços no projeto Compose `pastorai` (`backend`,
  `queue-worker`, `cron-worker`) e o `broadcast_worker` avulso, sem labels
  Compose.
  - Os quatro têm `restart=always`, 0 montagens e 1 rede.
  - Espaço livre em `/opt`: 32,59 GiB.
- **Redis (só agregados, sem ler conteúdo):**
  - `pastorai:webhooks` 0 e `pastorai:webhooks:retry-scheduled` 0;
  - SCAN de processing completo, com 0 chaves e 0 itens. É uma foto pontual;
  - `pastorai:webhooks:dead`: **2 itens, preservados**. Ficam intocados e fora
    do escopo de replay, limpeza ou leitura deste release.
- **Layout legado:** existe `/opt/pastorai-lionclaw`. Não existem
  `/opt/pastorai-current` nem `/opt/pastorai-releases`.
- **Saúde da API:** `/health` respondeu 200.
- **Gates por serviço, lidos e não alterados:**
  - `ALLOW_REAL_SENDS=true` nos quatro serviços;
  - `BREVO_SEND_MODE=live` em backend, queue e cron; ausente no broadcast;
  - `BROADCAST_ASYNC_ENABLED=false` nos quatro;
  - `ASAAS_BILLING_ENABLED` ausente, e ausência não prova `false`;
  - `QUEUE_WORKER_DATABASE_MODE` ausente. No **candidato**, o default é
    `legacy`. O modo efetivo do código **instalado** não foi verificado, e
    não se infere que seja igual.
- **URLs dedicadas:** nenhum dos quatro serviços tem
  `PRIVATE_STORAGE_DATABASE_URL`, `PRIVATE_SEND_DATABASE_URL`,
  `PRIVATE_SUMMARY_DATABASE_URL` ou `QUEUE_WORKER_DATABASE_URL`.
- **Backup:** o manifesto sanitizado está `verified`, com `completed_at`
  27/10 06:16:06 UTC (o cron diário).
  - A ordem relativa entre esse backup e o reset **não foi verificada**.
  - Nesta etapa não houve conferência nova de checksum.
  - O checksum do backup de 26/10 é anterior ao reset e não prova o estado
    atual.

### Configuração do publicador manual (metadados de 27/10)

- O Environment `backend-production` existe; duas regras de proteção foram
  retornadas. Não foram alteradas nem contornadas.
- As variáveis `BACKEND_DEPLOY_ALLOWED_ACTORS` e
  `BACKEND_DEPLOY_SAFE_BASE_SHA` estão presentes no Environment. Valores e
  validade efetiva não foram conferidos; ausência no nível de repositório não
  significa ausência no workflow.
- Os quatro secrets esperados (`BACKEND_DEPLOY_HOST`, `BACKEND_DEPLOY_USER`,
  `BACKEND_DEPLOY_SSH_KEY`, `BACKEND_DEPLOY_KNOWN_HOSTS`) **não foram encontrados
  nos metadados dos escopos Environment e repositório consultados**. Eventual
  herança fora desses escopos não foi comprovada. Nenhum valor secreto foi lido.
- Antes de usar o workflow manual normal, o operador precisa configurar e
  validar essas entradas pelo canal seguro em GitHub → Settings →
  Environments → `backend-production`, sem enviar chaves ao chat. Isso não
  substitui o adaptador da primeira transição; uma execução manual pelo acesso
  SSH existente precisa de procedimento e escopo próprios revisados.
- Nenhum workflow foi disparado, secret criado ou configuração alterada.

### O que deixou de valer (histórico preservado abaixo)

- **Duplicidade e reconciliação:** a duplicidade de vínculo Pessoa lida em
  24/10 e a reconciliação excepcional por `reconcile_team_pessoa.py` foram
  **canceladas pelo dono em 27/10** e **não se aplicam a este release**. Depois
  do reset, a leitura mostra 0 grupos. As seções "Bloqueios concretos",
  "Reconciliação excepcional" e o ensaio de transição continuam como
  histórico.
- **Números antigos:** "46 pendentes", "124 ativas" e o ensaio de
  incompatibilidade 78→124 descrevem o candidato `354a83d`. **Não provam
  nada sobre 129.**
- **Decisão de 23/10:** a decisão do dono de aplicar as quatro migrations
  antigas continua valendo e não é reaberta aqui. As conferências de dados
  delas, abaixo, continuam obrigatórias.

### Bloqueador principal: adaptador real da transição inicial

**Ensaio SQL local — retomada de 27/10/2026:** os blobs de SQL e de
`backend/scripts/migrate.py` do candidato exato `afdfb78d71a53f2861632806e13cdda4662d7d63`
foram executados em PostgreSQL **17.6**, num container novo com `--network none`
e dados sintéticos. O cliente usou a rede desse container, sem porta publicada
nem montagem do repositório. A seleção histórica foi reproduzida com 78
migrations (antes de `20261015`, exceto as quatro ausentes conhecidas), seguida
das 51 pendentes em ordem lexical, uma chamada de `cmd_apply` por arquivo.
Resultado: **78 + 51 aplicadas, ledger exato de 129, zero pendentes, zero
índices inválidos e quatro roles de runtime NOLOGIN**. As oito migrations
concorrentes usaram `transactional=False`; as demais usaram transação.
O container PostgreSQL e o cliente foram removidos ao final, sem sobras sob
o identificador do ensaio.

Esse ensaio usa o executor do candidato, **sem** os rascunhos locais de
`--lock-timeout`. Prova a sequência SQL nesse banco sintético, não o adaptador
operacional, a imagem nova do backend, restauração, compatibilidade de retorno
ao legado, dados/ACLs/pooler do Supabase, preservação integral dos cadastros
reais ou autorização para produção. Os bloqueios abaixo continuam abertos.

- **O script de release não serve para a primeira virada.**
  `deploy/backend-release.sh` recusa o estado legado: sem `releases/<SHA>` e
  `current`, sem checker anterior e sem label de revisão.
- **O código de transição é só sintético.** `deploy/initial_transition.py` e o
  ensaio `deploy/rehearse_initial_transition.py` (seção "Transição inicial
  integrada legado→atual") rodam apenas em instalação sintética, com
  `production_ready=false`. **Não são deploy de PROD liberado.** O ensaio
  integrado usa 46 migrations, catálogo de 124 e uma etapa de reconciliação.
- **Antes de qualquer janela, ainda falta:**
  - adaptar o procedimento ao candidato (51 pendentes, 129 ativas, sem etapa
    de reconciliação e com duplicidade revalidada em zero);
  - adaptar à topologia real: três serviços Compose e o broadcast avulso;
    Nginx, montagens, Redis e Evolution compartilhados; outros sites do host;
  - ensaiar em instalação sintética e passar por revisão independente.
- **Ainda não feito:** transporte real e ensaio físico da instalação completa.
  A preparação local de banco e host simulado está comprovada na seção abaixo;
  ela não autoriza operação de código ainda não validado no ambiente real.
- **SHA do adaptador:** quando for implementado, fixar um SHA próprio e
  revisado do executor, registrado junto ao SHA da aplicação.
- **Controlador sintético:** proibido executá-lo em PROD, assim como remover
  ou contornar as guardas dele.
- **Pacote do release — preparado para PR própria, CI/revisão pendentes:**
  `deploy/package_backend_release.py` substitui o arquivo de diretórios inteiros
  por seleção explícita de blobs do commit exato. Inclui Python da aplicação,
  SQL das migrations e os arquivos necessários ao build/check/deploy; exclui
  configuração privada, scripts administrativos, testes e ferramentas de DEV.
  Recusa caminhos protegidos nas árvores selecionadas antes de ler blobs;
  links simbólicos selecionados são recusados antes da leitura do próprio link;
  não usa conteúdo do checkout nem atributos `export-ignore`/`export-subst`.
  O manifesto registra SHA do commit e SHA-256 de cada arquivo. A alteração
  do workflow preserva os gates de ator, ancestralidade, SHA e disparo manual.
  O workflow da main permanece inalterado até integração autorizada.
  Ensaio local do candidato `afdfb78d`: 404 arquivos no pacote, SHA-256
  `7e363d73f4fd255d6ffacf9550f6118c56aad9aa6fc604b4ee182a43de65be03`;
  build Docker do target `production` aprovado e 396 arquivos da imagem
  conferidos por hash, zero divergências, em contêiner sem rede e somente leitura.
  Nove testes do empacotador e 17 do workflow aprovados. Regressão de release,
  topologia e Compose: 157 testes e 216 subtestes aprovados, sem skips.
  Isso prova composição
  e build locais; não prova prontidão da transição legada nem autoriza release.
- **Proibido como atalho:** fabricar SHA anterior, label, symlink ou diretório
  `releases/` como "prova" de estado anterior.

### Adaptador: preparação local e próximos passos

A continuação atual cobre código, simuladores, PostgreSQL local descartável e,
na etapa histórica de 28/10, commit/push e PR com CI para revisão; a composição atual exige nova autorização.
Não cobre merge, deploy, leitura remota ou qualquer operação em produção.
Worktree `first-transition-20261027/PastorAi-1.0`, branch
`feat/first-transition-adapter-20261027`, base `37c7d68d` (PR #598), publicada
na [PR #600](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/600).
CI de `8ef92e3a7cfdb75e9c366a168ddff415962a8b5b` aprovada: quatro checks
obrigatórios, estático e ensaio sintético. Head após esta atualização documental
é validado novamente e registrado na descrição da PR.
Bloqueio histórico por branch superado pela suspensão global da main.
O controlador sintético anterior e suas guardas continuam intactos.

**Aconselhamento arquitetural inicial (28/10):** Claude Opus 5.5, configurado com esforço
high, confirmou nos metadados `claude-opus-5-5` em duas rodadas. A consulta foi
sobre padrões públicos, sem código ou fatos operacionais privados. Na tentativa inicial, o envio de
código foi recusado pela revisão automática por falta de autorização explícita
para esse payload/destino; não foi realizado naquele momento. O parecer é arquitetural e genérico,
não revisão independente destes arquivos. Codex avaliou a aplicabilidade ao código.

**Atualização da revisão de código:** após a autorização explícita do dono,
os sete arquivos novos e resumo sanitizado foram enviados ao Opus 5.5 high,
sem ferramentas ou acesso ao restante do repositório. Houve três rodadas de
revisão privada; a final concluiu **sem bloqueador local**. Os hashes dos sete
arquivos revisados estão no relatório derivado em `output/release/`. O parecer
não aprova produção nem o transporte real, que continua fora do ensaio.

A decisão é preservar aplicador, ledger e diário existentes, com portas estreitas
para os efeitos. Não criar uma nova estrutura de governança. Índice inválido ou
existente sem ledger provoca parada; não há DROP, adoção ou REVOKE automático.
Contagens e metadados são sinais, não prova de conteúdo preservado.

| Entrega local | Evidência e limite |
|---|---|
| Plano por artefato exato | Aplicação `afdfb78d71a53f2861632806e13cdda4662d7d63`, aplicador `37c7d68d60b6f86cfb1fe75d4c720530537845d6`; 78 de base + 51 pendentes, oito concorrentes. SHA-256 do preflight e dos seis módulos locais (novos e reutilizados) vinculados ao plano/diário. Mudança do plano bloqueia retomada. |
| Preflight completo pré/pós | Script existente pelo SHA da aplicação, transação READ ONLY, `row_security=off`, search_path e timeouts fixos. Saída restrita a contagens; sem renderizar UUIDs ou mensagens brutas. Testes negativos de owner inseguro e role sem visibilidade de RLS. Não valida permissões/pooler reais. |
| Dump/restore sintético real | Ferramentas PG17, banco inteiro fictício para incluir extensões, clone UUID marcado, catálogo normalizado/contagens e preflight conferidos. Testes de arquivo corrompido e disco cheio simulado. Clone e arquivo temporário removidos. `archive_persisted=false`, `content_verified=false`: não é backup operacional, prova integral dos payloads, dos volumes, mídia, Storage ou Redis. |
| Matriz de interrupções | SIGKILL real só no subprocesso do ensaio: antes/depois da intenção, antes do commit, depois do commit e antes do recibo. Ledger esperado 78/79; retomada converge a 129. Não prova perda de energia, falha de storage ou todos os interleavings. |
| Índices e ledger | Índice inválido é preservado e bloqueia retry. Ledger fora de ordem/regredido, intenção/hash ou identidade divergentes bloqueiam execução. Sem reparo, restore por cima ou retomada automática do legado. |
| Contrato de host | Apenas simulador: três serviços Compose e broadcast avulso, ingresso bloqueado antes da drenagem, restart=no antes do SIGTERM, espera e saída limpa, identidade/gates/mounts/redes/suporte estáveis e recusa de writer desconhecido. Recibo vinculado ao fluxo de banco e reconferido a cada migration. Nenhum transporte real, start, SSH ou cliente Docker existe nessa porta. |
| Filas | TYPE/PTTL/LLEN/ZCARD em chaves explícitas e processing informado. Sem KEYS/SCAN ou leitura de conteúdo da dead. Testado apenas com simulador; `content_verified=false`. Não certifica preservação integral nem quiescência do Redis compartilhado. |

**Resultado histórico da preparação anterior à composição (CI em `8ef92e3a`; SHA do ensaio local não revalidado):** **68 testes aprovados em 138,20s**,
Ruff aprovado. Gates de aptidão/backfill permanecem zero até sua migration,
inclusive na retomada após SIGKILL. Colisão com índice, tabela ou sequência
homônima é recusada antes do marcador. Dados fictícios não vazios e uma tabela
FORCE RLS tornam observável a exclusão de dados no dump. Retry é obrigatório
para execução incompleta pós-marcador; falhas antigas resolvidas não bloqueiam
replay concluído. `adapter-failed` é diagnóstico; `run-start/complete` determinam
a exigência de retry. O marcador referencia seq/digest do recibo de restore.
Inclui fluxo integrado host simulado → preflight → dump/restore fictício →
51 migrations → preflight final; quatro roles NOLOGIN; repetição idempotente;
drift do host após o primeiro commit bloqueando a próxima migration. Só
PostgreSQL descartável e subprocessos do ensaio foram executados; os recursos
do ensaio foram removidos. Revisão independente local: concluída nos sete arquivos enviados; CI do adaptador em `8ef92e3a`: **aprovada**, 68 testes em 154,49s e limpeza
confirmada. O primeiro CI falhou por ausência do client PG17; o workflow passou
a instalar pelo repositório oficial PGDG, sem mudança no adaptador.

**Reproduzir:** usar Python 3.13 já preparado com pytest/psycopg2, ferramentas
PG17 em `/usr/lib/postgresql/17/bin` e imagem local `postgres:17.6`. Executar
`python deploy/rehearse_first_transition_database.py --python <python-do-ambiente-de-testes>`.
O launcher usa tmpfs, porta loopback, credencial fictícia, ambiente limpo e
marcador de propriedade. Não instala dependências, não inicia aplicação/Redis
nem executa transporte real de host. Só metadados saem do ensaio de restore.

**Continuação local autorizada em 28/10 — validada localmente:** as 51 são aplicadas
também no clone restaurado antes do marcador. O helper exige endpoint local
UUID e marcador de propriedade; confere ledger 78→129, oito concorrentes,
invariantes a cada arquivo e preflight final. O recibo vincula o digest dos SQLs
e o resultado do clone ao diário. A fonte é reconferida por catálogo/contagens;
falha de replay elimina o clone e impede o marcador da fonte. Os testes cobrem
colisão transacional e interrupção de replay, sem reparar índices ou adotar ledger.
Clone e fonte pertencem ao mesmo cluster descartável: DDL de roles é global ao
cluster. A reconferência não prova isolamento de roles globais, payloads ou ACLs;
um restore operacional precisará de ambiente isolado adequado e autorização.

`SimulatedHostTransport` traduz o contrato para chamadas estruturadas a um driver
obrigatório com modo `local-simulation`: observação sanitizada, bloqueio semântico
de ingresso, `docker update --restart=no <id>`, `docker kill --signal=TERM <id>`
e `docker wait <id>` com timeout até 30s. São dados enviados ao simulador, não
comandos executados no host. Não existe executor de processos, SSH, start,
deploy nem implementação presumida de Nginx/Evolution. A identidade é reconferida
antes dos efeitos simulados; o contrato existente valida topologia/gates e diário.

**HISTÓRICO — revisão da fatia publicada em `84366305` em 28/10:**
Os resultados abaixo não validam a composição atual sobre `60e29d14` e não
concedem autorização atual de commit/push. Opus 5.5 high revisou os oito arquivos
em duas rodadas. O parecer final não encontrou bloqueadores locais e condicionou
o aceite à suíte integral verde. Condição cumprida: **91 passed em 260,03s,
zero skips**, Ruff, YAML/Bash e diff check aprovados. Naquela revisão, os oito arquivos eram
idênticos ao snapshot do parecer; essa identidade não vale para o candidato atual. Banco descartável removido.

Achados incorporados: validação explícita do recibo antes do marcador e na
retomada, comparação do catálogo final normalizado entre clone e fonte,
limpeza `DROP DATABASE ... WITH (FORCE)` no helper somente após nonce exato conferido,
limite de 600s no launcher e 120s nos filhos SIGKILL, limpeza de clones UUID
marcados por formato UUID válido no fixture do cluster privado do launcher, docstring sobre roles globais corrigida
e timeout do transporte sanitizado. Testes adicionais cobrem recibos inválidos,
catálogo divergente, cliente remanescente, endpoints de clone e ordem completa
clone51→recibo→marcador→fonte51. Um journal da versão anterior é recusado por
`plan-changed`; não editar o diário para contornar essa guarda.

O parecer não aprova produção. Na preparação local posterior (base `84366305`),
as sugestões restantes foram implementadas: erros do snapshot final viram
`clone-source-schema-check-failed`, sem detalhes do driver, e o recibo exige
identidade de clone diferente da fonte e declaração explícita de DDL global.
Testes negativos adicionais cobrem identidade, plano e flags divergentes.
Registro superado de 28/10, antes da revisão: essa diff ainda não tinha revisão externa ou CI; nenhuma chamada remota foi
feita nesta preparação. A consulta de clientes continua estrita; não relaxá-la
para resolver eventual corrida de encerramento de conexão. Estatísticas
assíncronas não são prova de quiescência, payloads ou ACLs.

A colisão comprovadamente falha na quinta migration do clone, com ledger 78
na fonte e nenhum marcador. Falha injetada na terceira também mantém a fonte
e remove o clone. O caminho de sucesso comprova 51 aplicadas, oito concorrentes
e ledger 129 no clone antes de prosseguir na fonte fictícia.

Registro histórico de 28/10: branch `feat/first-transition-clone-transport-20261028`, base `4eea5393`.
O dono autorizou revisão Opus desta nova fatia e, se aprovada, commit/push em
PR separada para CI. A revisão específica foi concluída; publicação autorizada
após os 91 testes verdes. A PR depende da #600; o resultado do head exato fica
na descrição da nova PR.
Preview da nova branch desabilitado; nenhum merge, deploy ou acesso à VPS/produção.
Resultados de revisão e CI do head publicado ficam na descrição da PR.
Próximo passo: revisão da diff e proposta de ensaio físico isolado do transporte,
com comandos, recursos e limpeza, antes de conectar qualquer driver real.
Reproduzir a validação local pelo comando acima; o launcher cria
somente PostgreSQL em tmpfs, porta aleatória loopback e remove seu contêiner/clones.
Riscos locais: lock, índice concorrente incompleto ou processo interrompido;
recuperação: conservar diagnóstico sanitizado e descartar somente os recursos
marcados do ensaio. Nenhum dado de produção entra nesse teste.

Para a janela futura, os comandos de banco, **não autorizados para execução**, são:
`python scripts/migrate.py status`, seguido de
`python scripts/migrate.py apply <arquivo-da-lista-exata> --yes --lock-timeout 2s`
para cada transacional, ou
`python scripts/migrate.py apply <arquivo-NT-da-lista-exata> --yes --no-transaction`
para as oito concorrentes. Usar o executor `37c7d68d`, SQL de `afdfb78d`, conexão
fornecida apenas no ambiente seguro e encapsulamento de saída revisado; nunca
URL em argumento ou saída bruta. Os comandos reais de contenção/backup/deploy
só serão definidos após implementar e revisar o transporte e obter autorização
para inspecionar identidades atuais. Não existe CLI de produção neste adaptador.

Ambiente futuro: janela nominal da instalação legada, com writers contidos,
backup novo e restore aprovado **antes** da primeira DDL. Riscos: indisponibilidade,
locks, backfills sobre dados vivos e índice NT parcial. Antes de DDL, retorno só
com baseline/imagem/ledger inalterados comprovados; após DDL, manter contenção,
parar no primeiro erro e corrigir adiante, sem DROP/adoção/restore automático.
Autorizações separadas: integração das PRs; inspeção remota sanitizada; ensaio
físico além de PG local; janela de contenção/backup/51 migrations/deploy; retorno
do piloto. Apresentar identidades, comandos e impactos concretos antes de cada
operação arriscada. A autorização de publicação desta PR não cobre essas etapas.

**Plano restante, em ordem:**

1. (Histórico de 28/10, anterior à composição atual.) Revisão dos sete arquivos concluída com Opus 5.5 high, sem bloqueador
   local. Publicação e CI autorizadas em 28/10, em PR dependente da #598.
   `backend-tests` inclui a suíte do adaptador pelo launcher; quantidade e resultado
   dependem do CI do head exato. Usa imagem PG17 por digest e
   ferramentas PG17; checkout completo fornece os dois commits revisados. O parecer genérico anterior foi complementado
   pela revisão privada explicitamente autorizada; não confundir os dois.
2. (Histórico publicado em `84366305`.) Ensaio dos 51 no clone e transporte de comandos simulados implementados
   localmente naquela etapa e validados naquele snapshot. A validação PG da
   composição atual está pendente no CI do futuro head. Revisar esta nova diff;
   depois preparar um driver real contra o contrato estreito, sem remover as
   guardas do controlador sintético. Preparar a comparação entre observação
   real e contrato; não inventar revisão Git da imagem legada, nomes ou layout.
   Sob o escopo atual, testar o código desse transporte só com doubles.
3. Antes de um ensaio físico além do banco descartável, apresentar o comando,
   recursos, efeitos esperados e limpeza, e obter ampliação explícita do escopo.
   Um simulador não atesta que Nginx, mounts, Redis ou Evolution reais se comportam
   dessa forma. Nenhuma inspeção remota está autorizada nesta continuação.
4. Só então preparar a janela concreta: SHAs revisados, identidades e escopo
   observados sob autorização, ingresso/writers contidos, backup novo e prova de
   restore adequada, preflight real sanitizado, contingência após DDL e smoke
   sem efeitos. Backup que pausa recursos compartilhados e suas consequências
   precisam de decisão nominal. A proposta concreta vem antes da execução.
5. Merge, deploy, DDL real e retorno do piloto são decisões próprias. Não
   abrir/fechar gates, alterar privilégios, reparar índice, restaurar banco ou
   iniciar serviços para obter aprovação de um teste. Depois da primeira DDL,
   permanecer contido e corrigir adiante; retorno ao legado não demonstrado.

O término local continua `database-verified`, `services=simulated-held`,
`host_verified=false` e `production_ready=false`. Não há transição de produção
pronta para disparar. A revisão Opus cobre o snapshot dos sete arquivos;
o wiring de CI, documentação e remoção de um espaço final no helper de backup
acrescentados depois são conferidos pelo Codex (sem mudança semântica do código).

Limites residuais da revisão: os contadores reutilizados precisam corresponder
às condições dos SQLs do candidato; os casos semeados não representam todos os
estados possíveis de dados reais. O restore no mesmo cluster não prova
comparação integral de payloads, triggers, ACLs ou roles globais. Intent de
SIGTERM sem recibo, com processo ainda vivo, resulta em espera limitada/recusa;
não há re-sinalização ou escalada automática. Exit code 0 continua exigido até
um ensaio real autorizado demonstrar o comportamento do alvo.

### Ensaio local de comandos — histórico de 28/10, sem nova execução autorizada

Escopo executado após aprovação explícita: testar **somente o codificador de comandos compartilhado com
`SimulatedHostTransport`** contra quatro processos Python fictícios no Docker
local. Não conectar um executor real ao contrato que exige simulação. Não é
ensaio dos workers reais, Compose, ingresso, filas, banco ou entrega a provedor;
nenhum provedor é chamado. Essas provas continuam pendentes em fatias próprias.

Preparado em `deploy/rehearse_first_transition_commands.py`, branch local
`feat/local-transport-rehearsal-20261028`, base `84366305`. O modo padrão imprime
JSON sem iniciar processos, consultar Docker ou criar relatório. Só `--execute`
inicia recursos; `--cleanup-only` apenas remove fixtures próprias. O dono
autorizou especificamente este ensaio e sua limpeza; não autorizou ações remotas.

Imagem local consultada apenas por metadados, sem execução:
`sha256:602bd2aff0fd122ec9161a5c1cbb5b10b8551be472633ec36e560914849fc96f`,
tag local `igreja12-release-package:afdfb78d`, sem volumes declarados. A imagem
não será baixada, construída, publicada ou retagueada; falta local provoca recusa.
A entrada da aplicação é substituída por Python isolado com `signal/sys/time`,
que só imprime `fixture-ready`, espera SIGTERM e sai com 0.

**Recursos e impactos aprovados:**

- Quatro contêineres com prefixo
  `igreja12-transport-probe-bcf190b5d3864e3ca760c0b2b0d2b801-`, um por papel.
- `--network=none`; nenhuma porta, rede criada, volume, montagem, segredo ou
  socket dentro dos contêineres. Healthcheck da imagem desabilitado; somente a
  fixture Python é executada. Rootfs somente leitura, usuário 65534,
  capabilities removidas e `no-new-privileges`.
- Cada fixture limitada a 128 MiB sem swap adicional, 0,25 CPU e 32 PIDs;
  total máximo de 512 MiB, 1 CPU e 128 PIDs. Logs locais de até 1 MiB por fixture.
  Há pequeno uso de disco para metadados e logs do Docker.
- Configuração Docker temporária vazia, ambiente construído e socket explícito
  `unix:///var/run/docker.sock`; sem contexto remoto ou configuração `.env`.
- Setup cria/inicia apenas fixtures. Depois: `update --restart=no`, conferência,
  `kill --signal=TERM`, `wait` limitado e conferência de saída 0/sem reinício.
  `restart=always` inicial existe só para provar sua remoção; não altera serviços reais.
- Limite global da execução de 180s; limpeza com até 5s por comando (até 80s
  de timeouts para quatro recursos, mais overhead). Relatório JSON sanitizado
  em `/tmp`, criado exclusivamente, sem sobrescrever arquivo existente.

**Comando da execução aprovada (registro; relatório não é sobrescrito):**

```bash
umask 022
/tmp/pastor-retomada-597-venv/bin/python \
  /home/raniel-linux/.codex/worktrees/first-transition-20261027/PastorAi-1.0/deploy/rehearse_first_transition_commands.py \
  --image sha256:602bd2aff0fd122ec9161a5c1cbb5b10b8551be472633ec36e560914849fc96f \
  --run-id bcf190b5d3864e3ca760c0b2b0d2b801 \
  --report /tmp/igreja12-transport-bcf190b5d3864e3ca760c0b2b0d2b801-retry.json \
  --execute
```

**Limpeza e recuperação:** `finally` procura somente os quatro nomes planejados,
confere o label de propriedade UUID e remove pelo ID com `docker rm -f`.
Troca de propriedade ou indisponibilidade do Docker deixa relatório `incomplete`;
nunca remover recurso não reconhecido, executar prune ou limpar por prefixo amplo.
O uso de força limita-se às fixtures fictícias aprovadas, inclusive uma que
não tenha respondido ao sinal. Nenhuma imagem, rede, volume ou recurso alheio
é removido. Configuração Docker temporária é apagada; relatório é preservado.
Em SIGKILL do próprio controlador ou falha de energia, `finally` não é garantido:
reconciliar os mesmos nomes/labels pelo comando específico abaixo, também parte
da aprovação específica recebida; ele não inicia processos de fixture nem toca recursos alheios.

```bash
/tmp/pastor-retomada-597-venv/bin/python \
  /home/raniel-linux/.codex/worktrees/first-transition-20261027/PastorAi-1.0/deploy/rehearse_first_transition_commands.py \
  --image sha256:602bd2aff0fd122ec9161a5c1cbb5b10b8551be472633ec36e560914849fc96f \
  --run-id bcf190b5d3864e3ca760c0b2b0d2b801 \
  --report /tmp/igreja12-transport-bcf190b5d3864e3ca760c0b2b0d2b801-cleanup.json \
  --cleanup-only
```

**Resultado físico: PASS, quatro fixtures e limpeza `clean`, zero falhas.**
Todos os processos saíram com 0; restart policy `no` conferida antes do sinal,
nenhum reinício e nenhum recurso planejado remanescente. Consulta independente
`docker ps` restrita ao label UUID confirmou zero contêineres.
`host_verified=false` e `production_ready=false` permanecem: este é um ensaio
do codificador e das operações Docker sobre processos fictícios, não prova de
contenção completa, filas, providers, Compose ou workers reais.

As duas primeiras tentativas recusaram o start porque o driver de logging local
não aceita compressão com `max-file=1`; ambas terminaram com limpeza `clean`.
A correção adiciona `--log-opt=compress=false`, sem aumentar o limite de um
arquivo local de 1 MiB por fixture. Os nove testes de comandos foram repetidos
após a correção: **9 passed em 0,05s**, Ruff e diff check aprovados. A preparação
anterior teve **106 passed em 277,79s** no launcher PG, com remoção do banco;
nenhum teste PG foi repetido por essa alteração exclusiva do logging do ensaio.

Relatório final: `/tmp/igreja12-transport-bcf190b5d3864e3ca760c0b2b0d2b801-retry.json`;
cópia sanitizada e manifesto dos arquivos em `output/release/transport-command-execution.json`.
A autorização seguinte cobre revisão Opus 5.5 high, correções, commit/push, PR
separada sobre #601 e CI. Não cobre novos ensaios físicos, merge, deploy, VPS ou
produção. Opus identificou e foram corrigidos: argumento posicional inválido no
launcher do CI e `--run-id` ausente em execução/limpeza. A identificação explícita
agora é obrigatória antes de abrir relatório ou executar comandos. Novos testes
com doubles validam recusa sem escopo, socket/ambiente fixos e não sobrescrita do
relatório; **78 passed, 2 subtests passed**; revisão final Opus 5.5 high sem bloqueadores locais, Ruff e diff check aprovados offline.
O ensaio físico não foi repetido. Consultar a [PR #602](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/602),
branch `feat/local-transport-rehearsal-20261028` para o SHA e resultados finais de CI.

### Histórico — ordem proposta em 28/10, superada pelo estado vigente no topo

Consulta GitHub de 28/10 confirmou #597–#601 abertas e sem merge, com seis
workflows verdes em cada head abaixo. A PR nova deve permanecer sobre #601.
Ordem linear sugerida: **#597 → #598 → #599 → #600 → #601 → #602**.

| PR | Base/dependência registrada | Conteúdo e observação |
|---|---|---|
| #597 | main | Plano/runbook/painel e correção da auditoria. Primeiro da sequência. |
| #598 | #597 | Executor de migrations com lock timeout e fixtures corrigidas. |
| #599 | #597 | Empacotador por allowlist; independente da #598. Pode inverter posição com ela. |
| #600 | #598 | Adaptador local e CI; depende do executor revisado. |
| #601 | #600 | Replay no clone e transporte simulado; head `84366305`, CI verde. |
| #602 | #601 | Correções de recibo/erros, encoder compartilhado e ensaio de comandos com quatro fixtures sintéticos. |

Heads consultados: #597 `d0382051`, #598 `37c7d68d`, #599 `b3d93473`,
#600 `4eea5393`, #601 `84366305`. Não representam um candidato integrado.

Quando houver autorização de integração, reconfirmar heads/checks e bases no
GitHub. Após cada pai integrado, retarget da dependente para main, resolver
sobreposição de documentos/workflows e rodar os quatro checks no novo candidato.
Não transportar aprovação de CI entre SHAs. A autorização precisa tratar também
situação histórica de 28/10, superada pela suspensão global: o bloqueio então de preview
vale somente para as branches #600/#601 e desta fatia, não desabilita deploy da
main. `dev-synthetic.yml` também pode promover DEV após CI da main se
`DEV_PIPELINE_ENABLED` estiver habilitado; estado não verificado e nenhum acesso
DEV autorizado. Backend permanece manual (`workflow_dispatch`). A decisão de
merge deve tratar esses efeitos antes de qualquer integração. Não repinar silenciosamente o SQL `afdfb78d`
ou executor `37c7d68d` após merges; mudança de artefatos exige revisão/ensaio.

### Fases e condições

Na etapa histórica de 28/10, a autorização então vigente cobria revisão externa, código,
testes offline, publicação no GitHub e CI. Não cobre novos ensaios físicos ou
acesso à VPS/produção. Leituras de ambientes registradas em 27/10 são históricas. A fase 1 e qualquer
operação real das fases 2 a 7 exigem autorização nominal para ambiente, SHAs,
escopo, janela e operador. A fase 8 é uma decisão separada.

0. **Preparação local (agora).**
   - Revisar esta prévia (Codex e segunda opinião).
   - Atualizar o ROADMAP, a cargo do Codex.
   - Implementar o adaptador real e ensaiá-lo em instalação sintética, com
     revisão.
1. **Leituras pré-janela, somente leitura.**
   - Rodar `release_preflight.py` completo no SHA aprovado, pelo operador
     no ambiente seguro e fora de qualquer sessão de modelo, ou por um
     encapsulamento revisado que retenha a saída bruta no próprio processo
     remoto. Ele pode imprimir UUIDs quando há achados: nunca encaminhar
     stdout/stderr bruto ao modelo, docs, CI ou arquivos locais. Compartilhar
     apenas código de saída, contagens e metadados explicitamente aprovados.
     Com qualquer achado, parar sem copiar as linhas. Ainda não foi executado.
   - **Revalidar** imediatamente antes da janela o que já foi lido em 27/10:
     backfills 1 e 2, filas no banco e no Redis, configuração do agente e
     topologia. Revalidar não equivale a dizer que nunca foi lido; as fotos de
     27/10 são pontuais.
   - Revalidar a contagem segura da migration 10 (Pessoas com `apto_proxima_cd`
     verdadeiro): a leitura de 27/10 às 15:29 UTC retornou 0 candidatos.
2. **Contenção e quiescência antes do backup.** Parar explicitamente os quatro serviços, pelos IDs
   (backend, queue, cron e broadcast avulso), com política de reinício
   persistida antes do SIGTERM.
   - Bloquear o ingresso da API, inclusive o caminho direto Evolution →
     backend. Segundo a leitura estática de 24/10, o webhook chega em
     `backend:8000`.
   - **Quiescência:** nenhuma escrita de aplicação, humana ou em background,
     fora do escopo das migrations aprovadas. As DDL e DML das próprias
     migrations são a exceção prevista.
   - Não presumir que todos os writers estão parados nem que as filas estão
     limpas. Revalidar.
   - Os 2 itens da `dead` do Redis ficam intocados.
   - Preservar a imagem retida, os volumes, o Nginx, as montagens, o Redis, a
     Evolution e os outros sites.
   - Gates não mudam por esta prévia. `backend-release.sh` exige os quatro
     gates fechados, mas o piloto está com envios abertos: fechar gates (o que
     é terminal para pendências) ou pausar com preservação de fila é decisão
     nominal própria.
3. **Backup da janela, com os writers já contidos.** Exige um backup novo, autorizado e feito
   imediatamente antes das migrations, após a contenção e a comprovação de
   quiescência. Manter a contenção até o fim: nenhum writer da aplicação pode
   alterar o estado entre o backup e a primeira DDL. Se houver escrita ou
   retomada não prevista, parar e renovar a conferência/backup sob o escopo
   autorizado; nunca assumir equivalência do estado.
   - **Impacto conhecido:** o script do repositório
     (`deploy/backup-production.sh`) roda `CHECKPOINT` e
     `docker pause pastorai_evolution pastorai_evo_postgres pastorai_redis`
     durante a cópia dos volumes. Ingestão do WhatsApp e tudo o que depende do
     Redis ficam parados nesse intervalo.
   - **Não medido:** a duração da pausa. O script instalado na VPS não foi
     comparado com o do repositório nesta etapa.
   - **Conferências:** `status=verified`, SHA-256 do pacote e itens previstos.
   - **Limite:** checksum não prova restore. A prova de restore é um passo
     separado, num ambiente isolado.
4. **Reconferência imediatamente antes da primeira DDL.**
   - Ledger com exatamente as 78.
   - Pendentes iguais à lista abaixo.
   - Duplicidade 0 e `invalid_cell_links=0`.
   - Contagens agregadas dos backfills conferidas.
   - Nenhum vestígio de DDL.

   Se algo falhar **antes da primeira DDL**, só se retoma o legado com a
   baseline comprovadamente inalterada: mesma imagem, ledger 78 e nenhum
   objeto novo.
5. **As 51 migrations**, por `migrate.py`, uma por invocação, na ordem abaixo,
   parando no primeiro erro.
6. **Pós-migrations.**
   - `migrate.py status` e preflight de novo, sob a mesma proteção de saída
     da Fase 1 (sem stdout/stderr bruto ao modelo, docs, CI ou arquivos locais;
     só códigos, contagens e metadados aprovados). Agora os contratos privados
     existem e são examinados: um achado `private_definer_dono_sem_bypass`
     exige decisão nominal, nunca elevar dono para ficar verde.
   - Deploy do candidato **pelo adaptador revisado**.
   - Smoke sem efeitos.
7. **Falha depois da DDL.**
   - Manter tudo contido e corrigir adiante.
   - **Sem rollback automático de banco e sem restore por cima de PROD**, salvo
     nova prova e nova aprovação.
   - Voltar ao legado depois da DDL não está demonstrado para 129.
8. **Retorno do piloto.** É uma etapa nominal separada, sem ampliação.
   - **`AgentConfig`:** o único registro ativo é **preservado** como está, a
     menos que uma decisão nominal de manutenção exija mudança inevitável.
   - **Jev:** **não faz parte** do retorno do piloto. A ativação fica fora do
     escopo deste release, e o DPA vem antes de qualquer lista de igrejas.
   - **Roles de runtime:** podem continuar NOLOGIN e inativas no piloto, com o
     comportamento fail-closed descrito abaixo. Provisioná-las é decisão
     futura própria.

### Lista exata das 51 pendentes (ordem lexical de `migrate.py`)

Modo `tx` = transação padrão do aplicador; `NT` = `--no-transaction`, exigido
pelas **8** com `CREATE INDEX CONCURRENTLY` fora de comentário. Todas as 51
foram conferidas no código do candidato, e 45 declaram `lock_timeout='2s'`
(as quatro de julho/setembro e `20261023_110000`/`_120000` não declaram).

| # | Migration | Finalidade | Modo |
|---|---|---|---|
| 1 | `20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql` | backfill: Pessoa com vínculo ativo em célula passa a ser no mínimo "membro" (**muda dados**) | tx |
| 2 | `20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql` | reclassifica a Pessoa do número conectado ao WhatsApp para fora de "membro" (**muda dados**) | tx |
| 3 | `20260925_183811_preserve_platform_admins_on_tenant_deletion.sql` | preserva platform admins na exclusão de igreja | tx |
| 4 | `20260926_120446_platform_jev_settings.sql` | tabela de configuração da Jev, vazia e fechada (não liga Jev, não exige DPA) | tx |
| 5 | `20261016_180000_prayer_requests.sql` | pedidos de oração próprios (V4) | tx |
| 6 | `20261017_180000_visit_events.sql` | evidências de visita a célula | tx |
| 7 | `20261017_180100_consolidacao_atribuicoes_aceite.sql` | convites e aceite explícito de consolidação | tx |
| 8 | `20261017_210500_uv_turmas.sql` | turmas UV | tx |
| 9 | `20261017_220000_uv_presencas.sql` | presença UV | tx |
| 10 | `20261017_230000_uv_marcos_conclusao.sql` | marcos e conclusão UV; marca `origem_aptidao_cd='legado'` onde `apto_proxima_cd` (**muda dados de Pessoa**) | tx |
| 11 | `20261018_010000_cd_catalogo_turmas.sql` | catálogo e turmas CD | tx |
| 12 | `20261018_020000_cd_matriculas.sql` | matrículas CD | tx |
| 13 | `20261018_030000_cd_presencas.sql` | frequência CD | tx |
| 14 | `20261018_040000_cd_conclusoes_certificados.sql` | conclusões e certificados CD | tx |
| 15 | `20261018_050000_enviar_avaliacoes.sql` | avaliações Enviar | tx |
| 16 | `20261018_060000_enviar_nomeacao.sql` | nomeação Enviar | tx |
| 17 | `20261018_070000_enviar_abertura.sql` | abertura de célula sem origem | tx |
| 18 | `20261018_080000_enviar_reforcos.sql` | valida FK de célula (`invalid_cell_links` precisa ser 0) | tx |
| 19 | `20261018_090000_exclusao_privada.sql` | exclusão privada de conversa | tx |
| 20 | `20261018_100000_enviar_reencontro.sql` | marco de Reencontro | tx |
| 21 | `20261018_110000_cd_equivalencias_versoes.sql` | equivalências entre versões CD (atualiza tabelas CD criadas no lote) | tx |
| 22 | `20261018_120000_prayer_message_privacy.sql` | privacidade do histórico de oração; protege `conversations.ultima_mensagem` de conversas de oração (**muda dados**) | tx |
| 23 | `20261018_130000_conhecimento_oficial.sql` | conhecimento oficial | tx |
| 24 | `20261018_140000_conhecimento_trechos.sql` | trechos e busca lexical | tx |
| 25 | `20261019_090001_exclusao_privada_pessoa_igreja.sql` | exclusão privada por Pessoa ou igreja | tx |
| 26 | `20261019_110001_conhecimento_exclusao.sql` | exclusão de documento oficial | tx |
| 27 | `20261019_120001_private_conversation_summaries.sql` | resumos privados (sem consumidor ativo) | tx |
| 28 | `20261020_100000_prayer_audio_privacy.sql` | áudio de oração só para pastor | tx |
| 29 | `20261020_200000_private_resume.sql` | retomada de resumo (desligada) | tx |
| 30 | `20261021_100000_responsabilidades_setor.sql` | responsabilidades por setor | tx |
| 31 | `20261022_100000_private_erasure_requests.sql` | pedidos de exclusão de memória | tx |
| 32 | `20261023_100000_ai_usage_force_rls.sql` | FORCE RLS em uso de IA | tx |
| 33 | `20261023_100001_ai_usage_tenant_created_idx.sql` | índice de uso de IA | **NT** |
| 34 | `20261023_110000_operations_outbox_pending_metrics_fn.sql` | função de métrica da outbox | tx |
| 35 | `20261023_110001_notification_outbox_pending_created_idx.sql` | índice da outbox pendente | **NT** |
| 36 | `20261023_110002_notification_outbox_retry_created_idx.sql` | índice da outbox em retry | **NT** |
| 37 | `20261023_110003_notification_outbox_expired_lease_idx.sql` | índice de lease expirado | **NT** |
| 38 | `20261023_110004_messages_pending_agent_created_idx.sql` | índice de intenções de IA pendentes | **NT** |
| 39 | `20261023_110005_work_queue_pending_created_idx.sql` | índice da `work_queue` | **NT** |
| 40 | `20261023_120000_auth_session_revocation.sql` | `auth_sessions` e logout no servidor | tx |
| 41 | `20261025_100000_team_pessoa.sql` | índice único de vínculo Pessoa + auditoria (falha se houver duplicidade) | tx |
| 42 | `20261027_100000_reset_settles_erasure_requests.sql` | reset de Pessoa liquida pedidos pendentes (**não autoriza reset**) | tx |
| 43 | `20261028_100000_private_memory_overview.sql` | inventário de memória privada (admin) | tx |
| 44 | `20261028_100001_private_erasure_requests_overview_idx.sql` | índice do inventário | **NT** |
| 45 | `20261028_100002_private_resume_delivered_overview_idx.sql` | índice de retomadas entregues | **NT** |
| 46 | `20261029_100000_reset_settles_church_erasure_requests.sql` | reset da igreja liquida pedidos (**não autoriza reset**) | tx |
| 47 | `20261030_100000_private_storage_worker_identity.sql` | role `private_storage_runtime` (NOLOGIN) + contratos | tx |
| 48 | `20261030_110000_private_upload_attempt_witness.sql` | testemunha de upload de áudio (depende da 47) | tx |
| 49 | `20261030_120000_private_send_release_identity.sql` | role `private_send_runtime` + liberação de envio | tx |
| 50 | `20261030_140000_private_summary_runtime_identity.sql` | role `private_summary_runtime` + ciclo de resumo | tx |
| 51 | `20261030_160000_queue_worker_runtime_identity.sql` | role `queue_worker_runtime` (modo dedicado opcional) | tx |

**Exemplos de aplicação — NÃO EXECUTADOS, nem autorizados:**

```bash
# No host/sessão autorizados, na cópia exata do SHA aprovado, a partir de backend/.
# A URL só entra pelo ambiente seguro, nunca por argumento, arquivo do repo ou log:
set +o history; read -rs MIGRATION_DATABASE_URL; export MIGRATION_DATABASE_URL
python3 scripts/migrate.py status
python3 scripts/migrate.py apply 20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql --yes
# ... um arquivo por invocação, na ordem da tabela ...
python3 scripts/migrate.py apply 20261023_100001_ai_usage_tenant_created_idx.sql --yes --no-transaction
# ... até 20261030_160000_queue_worker_runtime_identity.sql ...
python3 scripts/migrate.py status
unset MIGRATION_DATABASE_URL
```

Regras de aplicação:
- **Uma migration por invocação.** Parar no primeiro erro e preservar o
  estado para decisão do dono.
- **Proibido:**
  - script concatenado ou laço cego;
  - `apply_migrations` nativo do Supabase, ledger nativo, MCP ou SQL manual;
  - `--no-transaction` fora das 8 marcadas.
- **`lock_timeout`:** o `'2s'` das migrations e o `lock_timeout` de sessão que
  o aplicador extrai nas `NT` não se contornam. Se der timeout de lock, parar.
  Nova tentativa só depois da decisão, nunca aumentando o timeout por conta
  própria.
  O executor de `migrate.py --lock-timeout` acrescenta padrão de 2s
  nas 43 transacionais, incluindo as seis sem limite no SQL. As oito `NT`
  mantêm o `SET lock_timeout` inicial do arquivo. Antes de usar esse executor
  numa janela, fixar e revisar seu SHA e conferir os comandos que alteram o
  limite nos 51 SQLs: a validação antes/depois não impede alteração temporária
  durante o SQL. Chamadas diretas de `cmd_apply` precisam passar
  `lock_timeout=2000` explicitamente; seu padrão continua 0 por compatibilidade.
  Em 27/10, Python 3.13.15: 46 testes unitários e seis testes reais em PG 17
  descartável passaram. Cobrem cancelamento de lock, rollback de DDL/ledger,
  restauração do limite após commit e índice concorrente. Essa prova isolada
  não autoriza produção.
  Replay adicional local de 27/10: base de 78 pelo caminho original
  (`lock_timeout=0` na chamada direta), seguida das 51 com o rascunho atual:
  43 transacionais com `lock_timeout=2000`, oito concorrentes com o limite
  do SQL; ledger exato de 129, zero pendentes e zero índices inválidos.
  Ambiente limpo, Python 3.13.15, PG 17 descartável em loopback, sem dados reais.
  Nesse primeiro ensaio, a base histórica não passou com o novo padrão:
  `SET TRANSACTION ISOLATION LEVEL` conflitava com a consulta inicial.
  Correção local posterior: `SET LOCAL` e `SHOW` substituem os SELECTs
  anteriores à migration, preservando seu isolamento. Dois testes reais
  falharam antes e passaram depois (SERIALIZABLE e REPEATABLE READ).
  Validação posterior em PG 17.6 descartável: **60 testes** (46 unitários +
  14 PG), replay **78→129** e instalação **0→129** pela CLI, ambos com ledger
  exato de 129, zero pendentes/índices inválidos e quatro roles NOLOGIN.
  Padrão de 2s preservado; somente a histórica `20260827_175634` recebeu
  `--lock-timeout 5s`, compatível com o limite que ela declara; as oito
  pendentes concorrentes seguiram com `--no-transaction` e seu limite SQL.
  Esses ensaios não definem timeouts para PROD. Executor local verificado:
  SHA-256 `df5f93254bdfbebd64d078b79abdbe4d139ea39e1cac0de4c647ba1fd646ac60`.
  Preparado para PR própria; revisão e CI do commit publicado ainda necessárias.
  Nenhuma operação real.
- **Falha numa `NT`:** pode deixar índice `INVALID`. Seguir o comentário do
  próprio arquivo ("check validity before retrying") antes de qualquer nova
  tentativa.
- **`statement_timeout`:** o valor efetivo da sessão do aplicador (pela DSN
  dele) não foi verificado. Os 10s de 27/10 eram `SET LOCAL` de uma consulta
  de leitura. Conferir antes da janela, sobretudo para os backfills e os
  índices. Não alterar sem decisão.

### Migrations de 30/10 (47–51): efeitos e provisionamento

- **O que criam:**
  - quatro roles `NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS`, sem senha;
  - funções SECURITY DEFINER com `GRANT EXECUTE` só para a própria role;
  - `REVOKE ALL` dessas funções de `public`, `anon`, `authenticated` e
    `service_role`.
- **Revogações de `authenticated`:** a 47 tira `UPDATE` em
  `private_deletion_tasks`; a 49 tira `DELETE` em `private_deletion_sends`.
- **Idempotência:** nenhuma é idempotente. Reaplicar é recusado, e role
  preexistente com atributos ou privilégios mais amplos também é recusada,
  nunca "reparada".
- **Dono dos contratos privados:** é a role que aplica. Se ela não tiver
  SUPERUSER ou BYPASSRLS, as funções falham fechadas. O preflight
  pós-aplicação acusa `private_definer_dono_sem_bypass`.
- **Contenção:** segundo o próprio arquivo, a 49 torna obrigatória a contenção
  do queue worker e de quem entrega respostas, porque código anterior que
  apague envio falha (`DELETE` negado).
- **LOGIN, senha e URLs (`PRIVATE_*_DATABASE_URL`, `QUEUE_WORKER_DATABASE_URL`)
  são provisionamento nominal separado**, não parte das migrations.
- **Sem URLs, o candidato não exige nada no boot.** Em `app/config.py`, todas
  têm default vazio e falham fechadas por funcionalidade:
  - limpeza privada de Storage e posse de upload de áudio não rodam;
  - a posse de envio fica retida, com recibos pendentes;
  - a geração de resumo privado não roda (já está desligada);
  - o queue worker continua em `legacy`, o default.
- **Valor inválido de modo:** qualquer valor de `QUEUE_WORKER_DATABASE_MODE`
  diferente de `legacy`/`dedicated` faz o worker recusar iniciar.
- **Modo `dedicated`:** é opcional e exige decisão própria. Nenhuma dessas
  URLs é obrigatória no boot do candidato.

### Escopo de risco de dados e preservação

- **`pessoas`:**
  - **o que muda:** o tipo (migrations 1 e 2) e `origem_aptidao_cd` (10);
  - **migrations 1 e 2:** 0 candidatos cada na leitura de 27/10, pela
    consulta agregada dos predicados completos. Revalidar na janela;
  - **migration 10:** acrescenta `origem_aptidao_cd` e marca `'legado'` nas
    linhas antigas com `apto_proxima_cd` verdadeiro. A consulta agregada de
    27/10 às 15:29 UTC retornou **0 candidatos**; revalidar na janela;
  - **qualquer contagem maior que 0:** um humano avalia fora do LLM antes da
    autorização. Não inferir 0 a partir do reset;
  - **atenção:** hoje existe **uma única Pessoa, ligada ao usuário mestre**.
    A reclassificação (2) não pode atingi-la por coincidência com o número
    conectado. Conferir explicitamente antes.
- **`conversations.ultima_mensagem`** (22): conversas de oração passam a
  mostrar texto protegido, e as mensagens são vinculadas em
  `pedido_oracao_mensagem`.
  - O alcance depende de `pedido_oracao_proposta`, criada pela migration 5
    dentro do próprio lote e hoje ausente, e de `messages`, com 0 linhas em
    27/10. A consulta de 15:29 UTC também confirmou 0 conversas e ausência das
    tabelas de proposta e vínculo de oração.
  - Não dá para contar antes por SQL nominal. Com a quiescência garantida,
    nenhuma proposta nova surge entre a 5 e a 22. Revalidar `messages` na
    reconferência.
- **FK de célula** (18) e **índice único de vínculo** (41): exigem
  `invalid_cell_links=0` e duplicidade 0 na reconferência.
- **Preservação:**
  - repetir as contagens agregadas antes e depois: igreja, usuário mestre
    utilizável ligado à Pessoa, papéis, platform admin, 4 planos e permissões;
  - essas contagens não provam conteúdo idêntico.
- **Logout:** depois do deploy, tokens sem `jti` recebem 401 (migration 40 +
  código), e todas as sessões caem. **Avisar a equipe antes da janela.**
- **Migrations de reset** (42, 46): só ajustam o que um reset faz quando
  executado. **Não autorizam nenhum reset.**
- **Smoke:** sem envio, cobrança, broadcast nem mutação fora do escopo. Login
  cria sessão e POSTs têm efeito, então precisam constar na descrição da
  janela. **Nada disso é feito agora.**

### Pendências reais antes de pedir autorização de janela

1. Adaptador real da transição inicial, com ensaio sintético e revisão
   independente.
2. Backup de janela autorizado, com checksum conferido. Prova de restore à
   parte.
3. `release_preflight.py` completo no SHA aprovado, executado fora do modelo
   ou sob encapsulamento remoto revisado de agregados, sem stdout/stderr bruto
   contendo UUIDs. Com achado, parar sem copiar linhas. Revalidar na janela os
   fatos de 27/10: backfills 1, 2 e 10 em 0,
   filas, Redis, configuração do agente e topologia.
4. Decisão nominal de contenção e gates. Os quatro consumidores já estão
   identificados.
5. `statement_timeout` efetivo e atributos da role do aplicador, que precisa
   ter SUPERUSER ou BYPASSRLS como dono dos contratos.
6. Pacote por allowlist preparado e validado na #599; falta integração autorizada
   e reconferência do pacote/imagem para os SHAs exatos escolhidos na janela, sem
   abrir conteúdo protegido. Não tratar CI da PR como prova de deploy.
7. Aviso de logout à equipe.
8. Aprovação nominal única da janela, cobrindo as 51, as ações e os SHAs
   (aplicação e adaptador). Registrar antes da execução o início UTC, o
   operador e a duração máxima numérica em minutos, fundamentada no ensaio;
   ao excedê-la, manter a contenção segura e pedir decisão, sem retomada ou
   reabertura automática. Não há janela nem duração operacional aprovadas agora.

Fora deste release: provisionar logins de runtime (opcional) e ativar a Jev.

## Estado e gates

O registro de 14/10 informa 78 migrations aplicadas e quatro pendentes:
`20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql`,
`20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql`,
`20260925_183811_preserve_platform_admins_on_tenant_deletion.sql` e
`20260926_120446_platform_jev_settings.sql`. Os quatro arquivos continuam ativos
em `migrate.py::migration_files()`. `deploy/backend-release.sh` monta o manifesto
com todas as migrations ativas, e `deploy/check_backend_schema.py` bloqueia o
release se qualquer nome esperado faltar em `public.schema_migrations`.

**Decisão do dono (Raniel, 23/10/2026, no chat): opção (1), aplicar as quatro.**
Elas ficam ativas no manifesto e são aplicadas na ordem lexical global. O deploy
só é autorizado quando todas as migrations ativas do SHA candidato estiverem
registradas no ledger do ambiente alvo. A decisão vale só para a escolha da
opção; não autoriza aplicar nada: cada migration em PROD continua exigindo
autorização nominal própria, backup verificado antes e SHA registrado.

Condições por migration, acordadas com o Codex em análise só de leitura:

| Migration | Condição antes de aplicar |
|---|---|
| `20260711_023515` (backfill de tipo "membro") | **Conferir antes.** Muda dados de pessoas reais e não tem reversão automática. O operador roda a consulta de candidatos da seção "Consultas de conferência" (somente `SELECT`), o dono vê quem mudaria (sem exportar telefone) e só então autoriza. Guardar id, igreja e tipo original fora do repositório para eventual reversão. |
| `20260711_152127` (número de atendimento deixa de ser "membro") | **Conferir antes.** Mesma regra: consulta com o final de 4 dígitos do telefone, e o dono confirma que o alvo é o número conectado, não uma pessoa. Guardar o tipo anterior. |
| `20260925_183811` (usuário de plataforma sem igreja) | Sem conferência de dados: não altera linhas. Necessária para a exclusão de igreja. Rollback exige tratar os `igreja_id` NULL. |
| `20260926_120446` (configuração da Jev) | Cria tabela vazia e fechada. A Jev continua desligada: aplicar não abre gate, não insere chave nem lista de igrejas; ativação segue sujeita a DPA e gates próprios. |

Se a conferência de uma das duas primeiras mostrar candidato inesperado, parar,
não aplicar e voltar ao dono. O Codex sugeriu excluir a quarta enquanto a Jev
estiver pausada; o dono decidiu aplicar, e a exclusão exigiria um SHA candidato
revisado à parte, com risco maior do que uma tabela vazia. Não inferir aplicação
pelo número 78.

As migrations com `OPERATIONAL_AUTHORIZATION=BLOCKED` continuam fora da
seleção de `migrate.py`; não remover o marcador nem aplicá-las neste release.
O preflight e o deploy precisam usar o SHA exato aprovado da `main` e o ledger
`public.schema_migrations` do banco correto. Pendências e gates lidos em
24/10: ver "Bloqueios concretos". Backup real: não verificado.

Manter fechados em todos os quatro serviços (`backend`, `queue-worker`,
`cron-worker` e `broadcast-worker`):

- `ALLOW_REAL_SENDS=false`;
- `ASAAS_BILLING_ENABLED=false`;
- `BREVO_SEND_MODE=off`;
- `BROADCAST_ASYNC_ENABLED=false`;
- `AgentConfig.ativo=false` para cada igreja incluída;
- Jev sem `TYPESAFE_API_KEY` e sem igrejas em
  `JEV_SHADOW_TRIAGE_IGREJA_IDS`.

Todos esses gates continuam desligados durante o lote. Não imprimir `.env`,
credenciais ou valores secretos. `stuck_flow` permanece desligado até existir
credencial dedicada. O script de deploy existente confere os quatro gates de
serviço; `AgentConfig.ativo` e Jev continuam sendo verificações independentes.
Executar qualquer etapa em PROD exige autorização nominal do dono. Nenhum
resultado local prova PROD.

Esses gates fechados são condição da janela futura. A leitura de 24/10 mostra
o piloto vivo com gates abertos (ver "Bloqueios concretos"); chegar à janela
exige contenção e autorizações próprias. Isso não é ordem para fechar gates
agora.

## Bloqueios concretos em PROD (leitura de 24/10/2026)

**Histórico (27/10).** Os números abaixo (124/46) e a duplicidade são de 24/10.
A reconciliação foi cancelada pelo dono e, depois do reset, a leitura mostra
0 grupos. Ver "Plano e prévia atual".

Leitura somente leitura autorizada pelo pedido da sessão; nenhum deploy,
migration ou restart foi executado. Sem PII, UUIDs, `.env` ou valores secretos.

1. **Migrations pendentes.** Comparação de nomes pelo CLI Supabase em
   transação somente leitura: 124 migrations ativas no SHA `354a83d`, 78
   registradas em `public.schema_migrations`, 46 pendentes (exatamente as 4
   antigas e as 42 do lote) e 0 entradas desconhecidas. A migration de logout
   `20261023_120000` está pendente e `public.auth_sessions` não existe.
2. **Duplicidade de vínculo Pessoa.** Consulta agregada equivalente aos dois
   checks de dados do preflight, em `REPEATABLE READ READ ONLY` com
   `bypassrls=true`: `invalid_cell_links=0` e
   `duplicate_user_person_groups=1`. Não é a execução integral de
   `release_preflight.py` e não retornou UUIDs nem PII. Bloqueia
   `20261025_100000_team_pessoa.sql` e o lote até reconciliar pelo fluxo
   administrativo autorizado (passo 3 da sequência), sem SQL de escrita
   automático, e repetir o preflight.
3. **Gates abertos no piloto vivo.** `docker inspect` com allowlist restrita
   aos quatro gates de serviço, sem ler `.env`:
   - `backend`, `queue-worker` e `cron-worker`: `ALLOW_REAL_SENDS=true`,
     `BREVO_SEND_MODE=live`, `BROADCAST_ASYNC_ENABLED=false`;
     `ASAAS_BILLING_ENABLED` ausente.
   - `broadcast-worker`: `ALLOW_REAL_SENDS=true` (entrada duplicada),
     `BROADCAST_ASYNC_ENABLED=false`; `BREVO_SEND_MODE` e
     `ASAAS_BILLING_ENABLED` ausentes.

   Ausência não prova `false`; defaults efetivos não verificados.
   `AgentConfig.ativo` e Jev: não verificados. Fechar gate não equivale a
   pausar fila e pode cancelar pendências; a contenção para a janela exige
   plano e autorização nominal próprios.
4. **Instalação sem rastreio de versão.** Backend e workers usam imagem criada
   em 02/10/2026 sem label de revisão; `/opt/pastorai-current` e
   `/opt/pastorai-releases` ausentes; instalação em `/opt/pastorai-lionclaw`,
   sem Git. O primeiro release por `deploy/backend-release.sh` exige uma
   transição inicial testada a partir desse estado. Não inventar SHA anterior
   nem contornar guardas do script; o plano de volta depende dessa transição.
   Ver "Transição inicial da instalação atual".

## Transição inicial da instalação atual

**Estado: PREPARAÇÃO, não pronta para execução.** Complementa a sequência
deste runbook; não autoriza nenhuma etapa nem é plano paralelo.

**Ponto de partida (leitura de 24/10).** Instalação em `/opt/pastorai-lionclaw`,
sem Git, sem `/opt/pastorai-releases` nem `/opt/pastorai-current`; imagem
`sha256:4a65f30e…b241` sem label de revisão, cujo ID coincide com o recibo de
manutenção de 02/10. Comparação somente leitura dentro do backend vivo com o
`candidate_manifest` de `maintenance-profile.json` (`app/*.py` e
`requirements.lock`, sem copiar conteúdo): 148 esperados, 148 iguais,
0 ausentes, 0 diferentes, 0 inseguros. Isso comprova a identidade desse
recorte com `07a3f4d`; não comprova a imagem inteira, a configuração nem os
workers. Brevo `live` foi confirmado pelo dono e é preservado.

**Requisitos antes de qualquer janela**, cada um com evidência revisada:

1. **Release ativo verificável.** `deploy/backend-release.sh` recusa executar
   sem `/opt/pastorai-releases`, sem `/opt/pastorai-current` resolvendo para
   `releases/<SHA de 40 caracteres>` com `deploy/`, configuração privada,
   `check_backend_schema.py` e manifesto de `migrate.py` daquele SHA e, na
   promoção por imagem, sem label de revisão igual ao SHA ativo. Chegar a esse
   estado exige procedimento revisado e ensaiado em ambiente sintético. Criar
   symlink, diretório ou label não prova o SHA anterior e não deve ser usado
   como prova.
2. **Base de recuperação.** O código ativo é o backport de manutenção
   `07a3f4d` (sobre `eb5a09b`), cujo contrato de 02/10 tinha 70 entradas no
   ledger; hoje há 78. Conciliar essa diferença antes de usar o contrato de
   manutenção como checker anterior. Release legado sem checker exige plano de
   recuperação revisado, sem copiar o checker candidato para a árvore antiga
   ([manual do release](../../deploy/BACKEND-RELEASE-MANUAL.md)).
3. **Identidade dos quatro serviços.** O recibo de 02/10 mantinha os workers na
   imagem legada; a leitura de 24/10 mostra os quatro na imagem da API.
   Registrar a identidade de cada serviço antes de definir o estado anterior.
4. **Gates e filas.** O script exige os quatro gates fechados em todos os
   processos antes do preflight; o piloto vivo está com envios abertos. Fechar
   `ALLOW_REAL_SENDS` cancela pendências de forma terminal. Antes da janela:
   inventário somente leitura das filas, decisão nominal de Raniel entre pausa
   que preserve fila (exige código e testes próprios) ou outra contenção, e
   plano de aviso/tratamento das pendências.
5. **Banco.** Backup verificado, reconciliação da duplicidade e preflight sem
   achados, conforme a sequência do release.

Leitura complementar de 24/10: Docker Compose 5.6.0 e `timeout` presentes;
backend, queue e cron têm labels Compose do projeto `pastorai`, mas broadcast
não tem labels de projeto/serviço. O procedimento deve identificar e conter
explicitamente cada consumidor; não presumir cobertura dos quatro por Compose.
Os dois backfills de julho retornaram 0 candidatos cada na consulta agregada
dos predicados completos, somente leitura. O único grupo duplicado tem igreja
e não envolve liderança ativa nesse instante. Revalidar esses fatos na janela;
nenhuma conta foi escolhida e nenhuma linha foi alterada.

**Recuperação**, escolhida antes da janela por decisão nominal de Raniel:

Ensaio local de 24/10: baseline operacional nominal de 78 seguido das 46
pendentes e reconstrução independente de 124 produzem catálogos idênticos.
A guarda aditiva recusa `previous schema contract changed`: há mudanças em
RLS, constraints, grants e função existentes, além de triggers, índices únicos
e FKs novos sobre relações antigas. O runner de `07a3f4d` também não seleciona
o mesmo conjunto das 78 entradas operacionais; contagem igual não prova
manifesto igual. Nenhuma migration pausada foi executada no ensaio.
Com dados fictícios, 10 verificações confirmaram recusa de duplicidades
ativo/revogado e ativo/ativo, atomicidade da falha, índice e isolamento da
auditoria; os dois backfills de julho tiveram 6 testes aprovados. A correção
dos vínculos nesses testes é exclusiva da fixture, não procedimento de PROD.

O painel atual não resolve a duplicidade no backend legado: a rota
`PUT /team/{usuario_id}/pessoa` não existe em `07a3f4d`; revogar mantém o
vínculo. A rota nova depende da auditoria criada pela própria migration que
recusa duplicados. O procedimento nominal foi integrado pela PR #572 (`830decc1`),
compartilhando as regras humanas, com auditoria atômica, testes e revisão
independente. A execução real continua pendente de escolha privada das contas,
backup, contenção e autorização nominal. Nenhuma conta pode ser escolhida automaticamente.

- **(A) Voltar à imagem atual depois das migrations:** só é alternativa se
  `deploy/schema_compatibility.py` comprovar, com catálogos reconstruídos das
  migrations nominais (nunca capturados do banco vivo e rotulados como
  esperados), que o schema resultante preserva o contrato do código ativo.
  Sem essa prova, não usar.
- **(B) Corrigir adiante com contenção:** manter os gates fechados, conter os
  processos afetados, preservar schema e evidências e preparar correção
  revisada; compensação de banco só com autorização própria.

Nenhuma das duas garante rollback universal: migrations não são desfeitas
automaticamente, cancelamentos de fila são terminais e a reversão das
migrations 1 e 2 depende do registro guardado fora do repositório.

## Autorizações nominais

Complemento de identidade (24/10): o ID completo da imagem viva coincide com
o [recibo sanitizado de manutenção de 02/10](../performance/2026-10-02-backend-maintenance-production.json),
associado ao candidato `07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02`.
O header público atual informa `unknown`; não houve comparação integral de
arquivos nesta consulta. O perfil antigo de manutenção exige exatamente 70
migrations e não pode ser reutilizado automaticamente com as 78 atuais.
O recibo preservava workers legados e Brevo `off`; a imagem comum aos quatro
serviços e Brevo `live` em três são diferenças atuais. Raniel confirmou em
24/10 no chat que Brevo `live` está autorizado; preservar o estado atual.
A mudança das imagens dos workers ainda não foi esclarecida. Essa confirmação
não autoriza testes de envio, fechar gates, recuperar imagens ou alterar
configuração; a contenção para a janela continua exigindo procedimento próprio.

Cada ação de PROD exige autorização própria de Raniel, com ambiente, SHA,
escopo e operador registrados. A autorização para uma etapa não se estende à
seguinte.

| Etapa | Quem autoriza | Quem executa e registra |
|---|---|---|
| Gerar e validar backup | Raniel, dono | Operador nominal da janela, com acesso autorizado à VPS e ao projeto Supabase |
| Consultar estado e rodar preflight | Raniel, para uma leitura somente leitura no alvo identificado | Operador nominal, usando role com `BYPASSRLS` e sem imprimir a URL |
| Reconciliar um achado | Raniel e admin/pastor nominal da igreja afetada | Responsável autorizado pelo fluxo administrativo aprovado para aquele registro |
| Aplicar migrations | Raniel, para a lista exata aprovada e SHA | Operador nominal, uma migration por invocação de `migrate.py` |
| Deploy do backend | Raniel, para o SHA completo e janela | Operador nominal pelo workflow manual existente |
| Smoke pós-deploy | Raniel, para o SHA e janela | Operador nominal, somente com chamadas sem efeitos externos |
| Plano de volta | Raniel, para a volta ao SHA anterior | Operador nominal; script de release, sem rollback de schema |

Registrar autorizações e recibos fora deste repositório, sem PII ou segredos.
Este documento e o merge do código não são autorizações operacionais.

## Sequência do release

1. **Backup verificado antes de qualquer migration.** Com autorização nominal
   de Raniel, o operador executa
   o procedimento instalado `/usr/local/sbin/pastorai-backup.sh` conforme o
   runbook de backup. Confere que o manifesto sanitizado informa
   `status=verified`, que o SHA-256 do pacote confere e que o pacote contém o
   dump `supabase-prod-public.dump` e os demais itens previstos. Registra hora,
   nome do artefato e SHA-256, sem copiar o pacote ou conteúdo de PROD para este
   workspace. Se o pacote ou o checksum falhar, parar.
2. **Preflight inicial.** Na cópia exata do SHA aprovado, com acesso de banco
   fornecido pelo canal autorizado e nunca por argumento ou log, executar:

   ```bash
   python3 backend/scripts/release_preflight.py
   ```

   O comando lê `MIGRATION_DATABASE_URL` do ambiente seguro, inicia transação
   `REPEATABLE READ READ ONLY`, recusa role que não contorne RLS e executa
   somente `SELECT`. Guarda a saída sanitizada. As migrations são listadas em
   `migrate.py::migration_files()`; `APLICADA` e `PENDENTE` preservam a ordem
   lexical do aplicador. `sem_arquivo` conta entradas do ledger sem arquivo
   ativo. A base `20261014` limita a verificação das tabelas esperadas no
   backup; o preflight reporta todas as migrations ativas do aplicador.
   Qualquer achado de FK, duplicidade, tabela ausente ou entrada sem arquivo
   interrompe o lote até decisão humana nominal. Pendências só são aplicadas
   depois da decisão sobre as quatro antigas e sobre a lista nova. Exit `0`
   significa apenas ausência desses achados; não significa schema liberado,
   migrations concluídas ou release pronto. Exit `1` exige reconciliação; exit
   `2` indica que o preflight não conseguiu verificar o alvo. Para autorizar o
   deploy, nenhuma migration ativa do manifesto do SHA candidato pode faltar no
   ledger; aplique todas ou use a opção de exclusão em SHA revisado descrita em
   Estado e gates.
   A checagem da FK reproduz o par `(igreja_id, celula_id)` que será validado
   pela migration `20261018_080000`; a checagem de duplicidade usa
   `(igreja_id, pessoa_id)` não nulo, como o índice da #543.
   A linha `private_definer_contracts` lê só `pg_catalog`, sem chamar funções,
   os contratos privados SECURITY DEFINER com `row_security=off` da lista fixa
   `PRIVATE_DEFINER_CONTRACTS`: cinco da #587, dois da `20261030_110000`
   (`private_storage_begin_upload_attempt` e `private_storage_upload_witness_due`,
   acrescentados na integração com a #584) e três da #588 (migration
   `20261030_140000`, integrada): dez. Os três da #588 são
   `private_summary_runtime_due_tasks`, `_sources` e `_reserve`, cujo próprio
   corpo lê tabela com FORCE RLS. `_snapshot`, `_requester` e `_credential`
   também declaram `row_security=off`, mas leem diretamente só tabelas sem
   FORCE, que um dono também dono dessas tabelas opera legitimamente sem
   BYPASSRLS: ficam fora para não gerar falso positivo, desde que o dono da
   função também seja dono dessas tabelas ou tenha BYPASSRLS (se não for, a
   função falha fechada, sem vazamento, e o preflight não acusa); os logins da
   aplicação seguem sem BYPASSRLS. O resolvedor `queue_resolve_instance` da #590
   segue a mesma regra. A dependência do dono
   de funções aninhadas, como `private_summary_origin_valid`, também fica fora:
   ela herda `row_security=off` do chamador, e o preflight olha só o
   `proconfig` da própria função.
   Nenhum banco de PROD foi verificado com a lista nova. Achado (`private_definer_dono_sem_bypass`,
   só assinatura e dono) quando o dono de um contrato presente não tem
   SUPERUSER nem BYPASSRLS: nesse estado a função falha (42501) e, por exemplo,
   envios ficam com ownership retida e limpezas pendentes. Contrato ausente,
   como antes de aplicar a migration dele, sai em `nao_verificados` e não é
   achado nem atestado. `examinados` conta só assinaturas presentes no
   catálogo; não atesta a definição (um contrato que perdeu SECURITY DEFINER
   ou `row_security=off` é contado sem achado). Por isso o preflight anterior
   às migrations não cobre funções pendentes: depois de aplicação nominalmente autorizada, repetir o
   preflight somente leitura para examinar as que passaram a existir. O achado
   não se corrige elevando dono para deixar verde nem com mudança automática
   de privilégios; exige decisão nominal. A checagem não prova ACL, corpo,
   segurança das funções nem sessões abertas antes de uma troca de atributo.
   Outras funções SECURITY DEFINER, inclusive a métrica da outbox de operações
   que também declara `row_security=off`, ficam fora deste contrato.
   Um teste em PG sintético compara o catálogo com a lista: toda função de
   `public` com SECURITY DEFINER e `row_security=off` precisa ser contrato ou
   exclusão explícita (cinco: a outbox, os helpers de resumo `_snapshot`,
   `_requester` e `_credential` e `queue_resolve_instance` da #590; 15 definers
   `row_security=off` classificados), então um definer novo esquecido falha.
3. **Reconciliação manual antes da #543** (histórico; em 27/10, 0 duplicidades
   depois do reset e reconciliação cancelada; resta só a reconferência). Antes de aplicar
   `20261025_100000_team_pessoa.sql`, confirmar zero duplicidades da chave
   `(igreja_id, pessoa_id)`. Qualquer duplicidade de igreja/pessoa exige
   reconciliação manual pelo fluxo administrativo autorizado. O operador entrega
   ao dono e ao admin/pastor da igreja afetada somente contagens e UUIDs; não
   usar exclusão em lote, SQL de escrita, merge automático ou escolha do agente.
   Repetir o preflight depois da reconciliação. Só seguir com zero violações de
   FK e unicidade, zero tabela ausente e destino explícito para cada entrada
   `sem_arquivo` e migration pendente que afete o lote.
4. **Migrations por `migrate.py`.** Com a lista aprovada, conferir primeiro
   `python3 backend/scripts/migrate.py status`. Aplicar uma migration por vez,
   na ordem apresentada e com registro nominal da saída:

   ```bash
   python3 backend/scripts/migrate.py apply <arquivo.sql> --yes
   ```

   Para as migrations marcadas `CONCURRENTLY` na tabela abaixo e a migration
   anterior à base indicada após a tabela, usar as invocações exatas com
   `--no-transaction` listadas ali. Para as demais, manter a transação padrão.
   Não usar `apply_migrations.py`, SQL manual, wrappers catalog-bound,
   `--no-transaction` sem requisito explícito da migration, nem tentar fazer um
   teste passar abrindo gate. Antes da #543, repetir a checagem de duplicidades
   `(igreja_id, pessoa_id)`. Em erro, parar no primeiro arquivo e preservar o
   estado para decisão de Raniel. Depois da lista aprovada, repetir `status` e
   o preflight somente leitura. Nenhum item aprovado deve permanecer pendente;
   resolver nominalmente qualquer divergência antes do deploy. O segundo
   preflight verifica também se as tabelas criadas pelas migrations já
   registradas desde 15/10 existem em `public`, schema inteiro coberto pelo
   dump de backup.
5. **Deploy do backend.** Depois do banco e dos preflights, Raniel autoriza
   separadamente o SHA completo de 40 caracteres. O operador usa o workflow
   manual **Backend release** da `main`; ele chama
   `deploy/backend-release.sh` na VPS. Manter o mesmo SHA que foi aprovado e
   inspecionado. Não disparar workflow durante esta preparação.
6. **Smoke sem efeitos.** Com os gates acima fechados, conferir `/health` e
   `/ready` públicos e no loopback, `docker compose ps`, CORS e isolamento das
   portas 8000/8080, seguindo a seção 8 do runbook de produção. Usar somente
   GETs e conta de teste previamente aprovada. Não testar envio, cobrança,
   broadcast, recuperação que possa contatar usuário, WhatsApp nem Jev. Se
   saúde ou readiness falhar, seguir o plano de volta sem reabrir gates.
7. **Gates continuam fechados.** Conferir os quatro processos depois do
   restart, `AgentConfig.ativo=false` por igreja e Jev inativo. Registrar
   confirmação sem mostrar valores secretos. O smoke não autoriza ativação.
8. **Plano de volta.** Em falha, Raniel decide nominalmente a recuperação e o
   operador usa o rollback de código do `deploy/backend-release.sh`, que
   verifica a compatibilidade do SHA anterior antes de retomar os serviços.
   Migrations não são desfeitas automaticamente. Preservar banco, backup e
   evidências. Corrigir adiante ou preparar uma compensação de banco revisada
   sob autorização própria. Nunca restaurar dump por cima de PROD como
   rollback improvisado.

### Critérios de contenção — provas operacionais ainda pendentes

A contenção do legado precisa identificar explicitamente backend, queue,
cron e broadcast: este último não tem labels Compose na leitura de 24/10.
Parar somente workers não bloqueia escritas humanas nem webhooks na API.
Antes de autorizar uma janela, ensaiar com dados fictícios o bloqueio de
entrada, término gracioso dos quatro processos, ausência de novas escritas
após a parada e preservação de gates e pendências. Verificar também políticas
de reinício e supervisores; uma leitura isolada de `Running=false` não prova
contenção durável.

O ensaio deve recusar identidade trocada/ausente, registrar timeout sem
promover release nem retomar automaticamente, e incluir trabalho em curso
na fronteira do provedor simulado. Retomada pré-DDL e recuperação pós-DDL
são provas diferentes: a recusa de compatibilidade entre 78 e 124 migrations
continua impedindo prometer retorno automático ao legado. Pendências podem
expirar durante a janela; preservar filas não garante elegibilidade futura.

Leitura estática do Git `07a3f4d` (não confirma configuração viva): Evolution
aponta diretamente para `backend:8000/whatsapp/webhook`; bloquear só o proxy
externo não contém esse ingresso. Queue termina o item atual depois do sinal;
cron pode terminar o tick inteiro, incluindo etapas posteriores ao sinal;
broadcast cerca a próxima requisição, mas permite concluir a já iniciada.
Os quatro serviços declaram `restart: always`, sem prazo de parada explícito.
O ensaio precisa medir término real e tratamento do efeito ambíguo, não apenas
recebimento de SIGTERM. Configuração viva de supervisor e retry externo seguem
não verificados.

Consulta SSH somente leitura em 24/10 às 17:22 UTC confirmou nos quatro
containers vivos `restart=always`; `StopSignal` e `StopTimeout` não constam
explicitamente na configuração inspecionada. A consulta projetou somente
esses campos e nomes, sem ler variáveis de ambiente. Isso não comprova o
prazo efetivo de término nem ausência de outros supervisores. Nenhum serviço
foi parado ou reiniciado.

A segunda opinião independente do Claude Opus acrescentou três cenários ao
ensaio: provedor simulado que reenvia ou não webhooks recusados, reinício por
supervisor e envio concluído com commit ainda pendente. Não presumir retry de
provedor real nem reenvio seguro de efeito ambíguo. A retomada com gates
preservados pode drenar o acúmulo e também é um efeito externo a autorizar.
Testes de reboot/daemon devem existir apenas em infraestrutura sintética
isolada, nunca reiniciando o Docker do host compartilhado.

A recusa do checker de compatibilidade aditiva não prova que todo caminho do
legado falharia; prova que o retorno automático não está demonstrado e não
pode ser oferecido como recuperação garantida.

Esse é um requisito de preparação local, não uma autorização ou procedimento
executável em produção. Nenhum gate deve ser fechado para realizar o ensaio.

## Reconciliação excepcional de vínculo duplicado

**Histórico (27/10): cancelada pelo dono e não aplicável ao release atual.**
Depois do reset, há 0 duplicidades. Não pedir UUIDs nem DSN, e não executar
`reconcile_team_pessoa.py` para este release.

**Estado: preparação.** Código e testes sintéticos; não executado em nenhum
ambiente real. Não autoriza a operação.

O backend ativo não tem a rota de desvincular, e a migration
`20261025_100000_team_pessoa.sql`, que cria a trilha `team_pessoa_eventos`, só
pode ser aplicada sem duplicidades. Para esse impasse,
`backend/scripts/reconcile_team_pessoa.py` desvincula **um** acesso escolhido
nominalmente e mantém o outro. Ele nunca escolhe sozinho.

**Escopo:** a leitura de 24/10 encontrou um único grupo duplicado, com duas
linhas no maior grupo e sem liderança ativa. A ferramenta trata exatamente esse
formato (duas contas) e recusa qualquer outro.

**Momento:** usar a ferramenta de um SHA fixado e revisado, **antes** de
aplicar as 46 migrations pendentes; os testes sintéticos rodam sobre o
baseline real de 78 migrations. Da reconciliação até a criação do índice único
por `20261025_100000`, manter contidos os writers que criam ou alteram vínculo
Pessoa (convites, ativação, gestão de equipe), não apenas durante a transação
da ferramenta. Repetir o preflight imediatamente antes da migration.

- **Prévia (padrão):** transação `REPEATABLE READ READ ONLY`; nada é travado
  nem alterado. Emite `CONFIRMACAO=DESVINCULAR:<sha256 do payload>`, código
  técnico sem UUIDs ou dados pessoais que muda com qualquer campo aprovado.
- **Aplicação (`--aplicar`):** exige igreja, pessoa esperada, conta a manter,
  conta a corrigir, admin ativo da igreja, operador ativo em
  `platform_admins` (pode ser o próprio admin, se tiver os dois papéis
  atuais), id de operação UUID, SHA exato de 40 caracteres e, na entrada
  padrão, a linha exata emitida pela prévia. Tudo é revalidado no servidor,
  sob trava, na ordem Igreja → Pessoa → acessos → papel `admin` →
  `platform_admins`. Revogação concorrente desses papéis faz a operação
  esperar e, se confirmada, recusar.
- **Recusa:** se o grupo atual não for exatamente as duas contas aprovadas
  (resolvido ou com mais linhas), se a conta a manter não for acesso ativo
  utilizável, se a pessoa liderar célula ativa, se a role não ignorar RLS, se
  faltar schema ou auditoria, ou se `lock_timeout` sair de 1–30000 ms. Só o
  vínculo muda: papéis não são sincronizados, e status, papéis, dono e
  número de admins são conferidos antes do commit.
- **Auditoria:** uma linha em `platform_audit_log` com UUIDs, operação, SHA e
  hash do payload, na mesma transação. Falha da auditoria desfaz tudo. Não
  cria tabelas.
- **Idempotência:** o mesmo id com o mesmo conteúdo retorna `JA_APLICADA`
  somente se admin e operador ainda estiverem autorizados; o mesmo id com
  outro conteúdo é recusado.
- **Saída:** só códigos, contagens e o código de confirmação. A conexão vem
  apenas de `TEAM_PESSOA_RECONCILE_DATABASE_URL`, aceita só URL `postgresql`,
  sem `.env` nem configuração da aplicação; erros de parser ou driver saem
  como código fixo, sem DSN. O script não integra o catálogo do agente.

**Autenticação:** o script não autentica pessoas. UUIDs informados não são
login; a ferramenta só confere que eles têm, agora, os papéis exigidos. Quem
executa responde pela sessão nominal autorizada (credencial de banco e acesso
ao host), registrada fora do repositório com nome, horário e SHA.

**Limite de concorrência:** as travas da Pessoa, dos acessos, do papel
`admin` e da allowlist bloqueiam quem altera esses registros durante a
transação (a FK também trava a Pessoa). `lock_timeout` (5 s por padrão, máximo
30 s) faz a operação desistir em vez de esperar; nesse caso nada muda.
Caminhos que alterem `app_users` sem travar Igreja ou Pessoa não são
serializados; a verificação posterior recusa divergências visíveis até ali.
Depois do commit, só a contenção de writers impede uma nova duplicidade.

A execução em PROD exige backup verificado, autorização nominal de Raniel e do
admin da igreja para as duas contas, operador nominal e SHA registrados.
Anexar a saída sanitizada da prévia ao registro nominal antes da aplicação;
o token vincula os argumentos, mas sozinho não prova que a prévia foi executada.

## Logout no servidor (migration 20261023_120000)

A migration `20261023_120000_auth_session_revocation.sql` precisa estar aplicada
antes do código novo. Os logins de igreja em `auth.py` e de plataforma em
`platform_admin.py` registram o `jti` na tabela; sem ela, esses logins falham.

Tokens antigos sem `jti` passam a receber `401` quando o backend novo entra.
Isso encerra as sessões de todos os usuários e admins da plataforma no deploy;
comunicar essa saída à equipe antes da janela.

A ordem é migration, backend e frontend. Aplicar a migration por
`backend/scripts/migrate.py`, depois publicar o backend e, por último, o
frontend que chama o logout no servidor. A execução em PROD exige backup
verificado e autorização nominal de Raniel para o SHA, ambiente e janela.

Se for necessário voltar, reverter backend e frontend ao SHA anterior. O SQL
mantém o rollback comentado; qualquer remoção do schema deve seguir o processo
de migration com autorização nominal. Sem o código novo, tokens emitidos pelo
backend novo continuam válidos no fluxo antigo até expirarem. Migration aplicada,
rollback de código e release são etapas distintas; não executar nenhuma etapa
em PROD com base apenas neste registro.

## Migrations do lote posteriores à base de 14/10

Conferi `backend/scripts/release_preflight.py`, integrado pela #563
(`61e84383`): `BASELINE_DATE=20261014` limita a
checagem de tabelas esperadas no backup, enquanto o relatório percorre
`migrate.py::migration_files()` e classifica cada arquivo como aplicada ou
pendente. Essa função exclui migrations pausadas e ordena os nomes
lexicalmente. A tabela contém as 42 migrations ativas posteriores à base no
checkout atual, na ordem de aplicação; não afirma que estejam aplicadas em
PROD. Cada rollback resume o comentário da migration e exige reversão de
callers, preservação de dados e migration compensatória aprovada via
`backend/scripts/migrate.py`; não executar SQL de rollback manualmente.

A main atual já integra #556, #558, #560, #561, #562 e #568. As #556, #558 e
#560 não adicionam migrations; #561 adiciona a migration de reset privado da
igreja ao fim da lista, #562 adiciona as seis migrations de métricas e índices
operacionais abaixo, e #568 adiciona a migration de logout no servidor. As origens de cada arquivo foram conferidas no histórico
Git.

A busca literal `grep -il 'concurrently' backend/migrations/*.sql` encontrou
`20260701_014654_evt6_google_event_dedup_index.sql`,
`20260808_011500_messages_outbound_provider_id_uidx.sql`,
`20261023_100001_ai_usage_tenant_created_idx.sql`,
`20261023_110001_notification_outbox_pending_created_idx.sql`,
`20261023_110002_notification_outbox_retry_created_idx.sql`,
`20261023_110003_notification_outbox_expired_lease_idx.sql`,
`20261023_110004_messages_pending_agent_created_idx.sql`,
`20261023_110005_work_queue_pending_created_idx.sql`,
`20261028_100001_private_erasure_requests_overview_idx.sql` e
`20261028_100002_private_resume_delivered_overview_idx.sql`. A migration
`20260701_014654` só cita `CONCURRENTLY` em comentário e executa `CREATE UNIQUE
INDEX` comum; as outras nove executam `CREATE INDEX CONCURRENTLY` ou
`CREATE UNIQUE INDEX CONCURRENTLY`. `20260808_011500` antecede a base de 14/10,
por isso não integra esta tabela, mas também exige `--no-transaction` se estiver
pendente. As oito posteriores à base estão identificadas nas linhas da tabela.

| Ordem | Origem | Migration e efeito | Rollback resumido |
|---:|---|---|---|
| 1 | #484 | `20261016_180000_prayer_requests.sql`: persiste propostas e pedidos próprios de oração com RLS. | Drenar respostas, preservar pedidos confirmados e autorização; manter gates fechados e remover schema só por compensação aprovada. |
| 2 | #487 | `20261017_180000_visit_events.sql`: registra evidências de visitas a células com auditoria. | Reverter callers, preservar evidências; remover tabela e funções por compensação aprovada. |
| 3 | #488 | `20261017_180100_consolidacao_atribuicoes_aceite.sql`: persiste convites e aceite explícito de atribuições. | Suspender writers, preservar histórico privado e restaurar a função de revisão V3 antes de remover schema. |
| 4 | #492 | `20261017_210500_uv_turmas.sql`: cria turmas, atividades, responsáveis e matrículas da UV. | Reverter callers, preservar registros de formação e remover as tabelas em compensação. |
| 5 | #493 | `20261017_220000_uv_presencas.sql`: cria presença atual e histórico imutável das aulas UV. | Reverter callers, preservar histórico e remover tabelas, triggers, funções e constraints em compensação. |
| 6 | #494 | `20261017_230000_uv_marcos_conclusao.sql`: registra marcos e conclusões UV e a origem da aptidão. | Reverter callers, preservar marcos e históricos; remover tabelas, triggers, funções, constraint e coluna em compensação. |
| 7 | #497 | `20261018_010000_cd_catalogo_turmas.sql`: cria currículo, módulos, aulas, turmas, calendário e responsáveis CD. | Reverter callers, preservar catálogo, calendário e responsáveis; remover tabelas em compensação. |
| 8 | #498 | `20261018_020000_cd_matriculas.sql`: cria matrículas CD e snapshots de eventos de estado. | Reverter callers, preservar matrículas e eventos; remover dependências em compensação. |
| 9 | #499 | `20261018_030000_cd_presencas.sql`: cria frequência CD atual e histórico imutável. | Reverter callers, preservar histórico e remover tabelas, triggers, funções e constraints em compensação. |
| 10 | #500 | `20261018_040000_cd_conclusoes_certificados.sql`: registra conclusões, certificados e revogações CD. | Reverter callers, preservar conclusões e certificados; remover triggers, funções e tabelas em compensação. |
| 11 | #503 | `20261018_050000_enviar_avaliacoes.sql`: persiste avaliações humanas e eventos privados de aptidão. | Restaurar callers, preservar decisões e eventos; remover objetos em compensação. |
| 12 | #504 | `20261018_060000_enviar_nomeacao.sql`: adiciona solicitação versionada de nomeação de líder. | Restaurar callers e preservar histórico; reverter constraints e índices em compensação. |
| 13 | #505 | `20261018_070000_enviar_abertura.sql`: permite solicitação de abertura sem origem, sem backfill. | Restaurar callers, preservar solicitações e eventos; nunca apagar histórico nem rebaixar líderes. |
| 14 | #505 | `20261018_080000_enviar_reforcos.sql`: valida a FK de célula e reforça isolamento da solicitação. | Manter a FK validada; só restaurar estado anterior da validação por compensação aprovada. |
| 15 | #509 | `20261018_090000_exclusao_privada.sql`: cria exclusão privada durável de conversa e derivados. | Conter consumidores, drenar tarefas e preservar recibos; conteúdo apagado não é restaurável. |
| 16 | #510 | `20261018_100000_enviar_reencontro.sql`: registra evidência de Reencontro como marco oficial. | Reverter callers, preservar marcos e revogações; reconciliar duplicidades antes de reverter constraints. |
| 17 | #511 | `20261018_110000_cd_equivalencias_versoes.sql`: registra equivalências entre versões de currículo CD. | Reverter callers, preservar evidências e vínculos de certificados; remover view, tabelas e função em compensação. |
| 18 | #515 | `20261018_120000_prayer_message_privacy.sql`: restringe leitura do histórico de oração por igreja e papel. | Reverter consulta do backend junto com o schema, preservar recibos/tarefas #509 e manter gates fechados. |
| 19 | #513 | `20261018_130000_conhecimento_oficial.sql`: cria documentos, versões e operações de conhecimento oficial. | Parar callers e preservar documentos; não remover schema se houver documentos ou operações. |
| 20 | #516 | `20261018_140000_conhecimento_trechos.sql`: cria trechos transacionais e busca lexical autorizada. | Parar callers, preservar snapshots e citações; remover dependências em compensação. |
| 21 | #518 | `20261019_090001_exclusao_privada_pessoa_igreja.sql`: adiciona exclusão privada por pessoa ou igreja com recibos. | Conter consumidores, preservar recibos/barreiras e restaurar a função de #515 antes de compensar; conteúdo apagado não é restaurável. |
| 22 | #524 | `20261019_110001_conhecimento_exclusao.sql`: registra exclusão definitiva de documentos e citações oficiais vinculadas. | Parar callers e preservar auditoria; conteúdo apagado não é restaurável nem deve ser recriado. |
| 23 | #526 | `20261019_120001_private_conversation_summaries.sql`: cria resumos privados operacionais sem consumidor ativo. | Parar e drenar workers, preservar recibos e restaurar a função de exclusão anterior antes de remover schema. |
| 24 | #529 | `20261020_100000_prayer_audio_privacy.sql`: restringe áudio de oração ao pastor, inclusive compartilhamentos legados. | Restaurar políticas/funções só após aprovação pastoral; preservar associações e tarefas privadas. |
| 25 | #531 | `20261020_200000_private_resume.sql`: habilita retomada explícita de resumo, desligada por padrão. | Conter consumidores e restaurar a função anterior de invalidação; manter retomada desligada. |
| 26 | #530 | `20261021_100000_responsabilidades_setor.sql`: registra responsabilidades por setor e vigência sem conceder acesso. | Restaurar callers e preservar histórico; remover tabela e função em compensação aprovada. |
| 27 | #535 | `20261022_100000_private_erasure_requests.sql`: registra pedidos de exclusão privada e decisões do admin. | Parar consumidores e preservar pedidos, decisões e recibos; não compensar enquanto houver pedido pendente. |
| 28 | #544 | `20261023_100000_ai_usage_force_rls.sql`: força RLS na tabela de logs de uso, mantendo a política existente. | Restaurar apenas o comportamento anterior de FORCE RLS; manter RLS habilitada e a política. |
| 29 | #544 | `20261023_100001_ai_usage_tenant_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa logs de uso por igreja e data. | Conferir validade e remover índice com `DROP INDEX CONCURRENTLY` em migration compensatória. |
| 30 | #562 | `20261023_110000_operations_outbox_pending_metrics_fn.sql`: agrega métricas pendentes por igreja para admin ativo. | Remover a função por compensação após conter callers; a remoção também elimina seu ACL. |
| 31 | #562 | `20261023_110001_notification_outbox_pending_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa itens pendentes da outbox por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 32 | #562 | `20261023_110002_notification_outbox_retry_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa itens de retry da outbox por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 33 | #562 | `20261023_110003_notification_outbox_expired_lease_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa leases expirados da outbox por igreja e claim. | Conferir validade e remover índice concorrentemente por compensação. |
| 34 | #562 | `20261023_110004_messages_pending_agent_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa intenções de saída da IA por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 35 | #562 | `20261023_110005_work_queue_pending_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa itens acionáveis da fila por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 36 | #568 | `20261023_120000_auth_session_revocation.sql`: registra o `jti` das sessões próprias (sem guardar o JWT) para logout no servidor e revogação, com RLS forçada. Precisa estar aplicada antes do backend novo. | Reverter backend e frontend ao SHA anterior antes; remover as quatro políticas e a tabela `auth_sessions` só por compensação aprovada, o que descarta registros de sessão e revogação. |
| 37 | #543 | `20261025_100000_team_pessoa.sql`: aplica unicidade de Pessoa por igreja e cria auditoria técnica. Exige reconciliação manual prévia de duplicidades `(igreja_id, pessoa_id)`. | Reverter callers e preservar auditoria; remover índice e tabela somente por compensação aprovada. |
| 38 | #541 | `20261027_100000_reset_settles_erasure_requests.sql`: faz reset manual de pessoa cumprir pedidos privados pendentes. | Parar consumidores, preservar pedidos/recibos e restaurar wrapper anterior; não reabrir pedidos cumpridos. |
| 39 | #546 | `20261028_100000_private_memory_overview.sql`: expõe contagens administrativas sem conteúdo ou ação automática. | Remover a função por compensação; não há dados apagados e RLS/grants existentes permanecem. |
| 40 | #546 | `20261028_100001_private_erasure_requests_overview_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa inventário de pedidos por igreja, estado e idade. | Conferir validade e remover índice concorrentemente por compensação. |
| 41 | #546 | `20261028_100002_private_resume_delivered_overview_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa retomadas privadas entregues por igreja. | Conferir validade e remover índice concorrentemente por compensação. |
| 42 | #561 | `20261029_100000_reset_settles_church_erasure_requests.sql`: faz reset privado da igreja cumprir os pedidos cobertos pelo recibo. | Parar consumidores, preservar pedidos/recibos e restaurar wrapper #541; não reabrir pedidos cumpridos. |

As invocações abaixo usam a ordem lexical entre as migrations concorrentes. Cada
uma deve ser aplicada somente quando alcançar sua posição na ordem global
mostrada por `migrate.py status`, depois dos prechecks descritos no próprio
arquivo:

```bash
python3 backend/scripts/migrate.py apply 20260808_011500_messages_outbound_provider_id_uidx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_100001_ai_usage_tenant_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110001_notification_outbox_pending_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110002_notification_outbox_retry_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110003_notification_outbox_expired_lease_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110004_messages_pending_agent_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110005_work_queue_pending_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261028_100001_private_erasure_requests_overview_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261028_100002_private_resume_delivered_overview_idx.sql --yes --no-transaction
```

## Consultas de conferência das migrations 1 e 2 (somente leitura)

Rodar no banco correto, com autorização nominal, dentro de `BEGIN READ ONLY; ...
ROLLBACK;`, e **antes** de aplicar `20260711_023515` e `20260711_152127`. O
resultado mostra nomes e identificadores: ver só na sessão do operador e do dono;
não copiar para chat, issue, log de CI nem documento. Nenhuma consulta mostra o
telefone completo (a segunda mostra só o final de 4 dígitos).

Para poder reverter, o operador guarda **fora do repositório** apenas
`id`, `igreja_id` e o tipo atual (`atual`) de cada linha listada, em local
autorizado, antes de aplicar. Se aparecer linha inesperada, parar e voltar ao dono.

```sql
-- Migration 1: pessoas com vínculo ativo na mesma igreja que passariam a "membro"
SELECT p.id, p.igreja_id, p.nome, p.tipo AS atual, 'membro' AS proposto
FROM public.pessoas p
WHERE (p.tipo IS NULL OR p.tipo::text IN ('contato','visitante'))
  AND EXISTS (SELECT 1 FROM public.celula_membro cm
              WHERE cm.pessoa_id = p.id AND cm.igreja_id = p.igreja_id AND cm.ativo IS TRUE)
ORDER BY p.igreja_id, p.nome, p.id;

-- Migration 2: registro cujo telefone canônico coincide com o número conectado
-- da mesma igreja, sem vínculo ativo, hoje "membro" (passaria a "contato")
WITH p AS (
  SELECT id, igreja_id, nome, tipo,
         CASE WHEN length(d) > 11 AND left(d, 2) = '55' THEN substr(d, 3) ELSE d END AS d
  FROM (SELECT id, igreja_id, nome, tipo,
               regexp_replace(coalesce(telefone, ''), '\D', '', 'g') AS d
        FROM public.pessoas) s),
pn AS (
  SELECT *, CASE WHEN length(d) = 10 THEN substr(d, 1, 2) || '9' || substr(d, 3) ELSE d END AS k
  FROM p),
w AS (
  SELECT igreja_id,
         CASE WHEN length(d) > 11 AND left(d, 2) = '55' THEN substr(d, 3) ELSE d END AS d
  FROM (SELECT igreja_id, regexp_replace(coalesce(numero, ''), '\D', '', 'g') AS d
        FROM public.whatsapp_connections WHERE numero IS NOT NULL) s),
wn AS (
  SELECT igreja_id,
         CASE WHEN length(d) = 10 THEN substr(d, 1, 2) || '9' || substr(d, 3) ELSE d END AS k
  FROM w)
SELECT p.id, p.igreja_id, p.nome, right(p.k, 4) AS fone_final_4,
       p.tipo AS atual, 'contato' AS proposto
FROM pn p
WHERE p.tipo = 'membro' AND p.k <> ''
  AND NOT EXISTS (SELECT 1 FROM public.celula_membro cm
                  WHERE cm.pessoa_id = p.id AND cm.igreja_id = p.igreja_id AND cm.ativo IS TRUE)
  AND EXISTS (SELECT 1 FROM wn w WHERE w.igreja_id = p.igreja_id AND w.k = p.k)
ORDER BY p.igreja_id, p.nome, p.id;
```

Estas consultas não são executadas por `release_preflight.py` nem pelo CI. Os
dois `SELECT`s passaram por sintaxe e resultado em `BEGIN READ ONLY; ...
ROLLBACK;` em PostgreSQL 17 descartável com duas igrejas e dados sintéticos. A
consulta 1 retornou somente pessoas com vínculo ativo e tipo `contato`,
`visitante` ou `NULL`. A consulta 2 retornou membros sem vínculo ativo nas
formas `+55` com e sem 9º dígito e local com 9º dígito, incluindo vínculo
inativo; não retornou vínculo ativo, pessoa de outra igreja com o mesmo
telefone nem DDD distinto com o mesmo sufixo. A consulta 2 reproduz o predicado
e os passos de canonicalização da função `pg_temp.pastorai_canon_phone` da
migration `20260711_152127`, comparando o telefone canônico completo. A saída
da consulta 2 não projeta o telefone completo e mostra somente seus quatro
dígitos finais. Nenhum banco real foi consultado.

## Ensaio de restauração sintética

O ensaio não lê nem toca backups reais nem arquivos `.env`. Recusa `DOCKER_HOST`
explícito e contexto Docker cujo endpoint não seja um socket Unix local. Usa
apenas a imagem PostgreSQL 17 já presente na máquina, container com rede
desabilitada e diretório de dados em `tmpfs`. Cria um dump custom do schema
`public` com UUIDs e linhas fictícias, restaura em outro banco do mesmo
container descartável e exige as contagens `synthetic_private_records=2` e
`synthetic_team_events=1`.

```bash
bash backend/scripts/release_restore_synthetic.sh
```

Saída esperada: `RESTORE_SINTETICO=OK tabelas=2 contagens=2:1`. A ausência da
imagem local interrompe o ensaio; não baixar imagem automaticamente na janela
de produção. O script remove o container e os arquivos temporários ao terminar.

## O que não fazer

- Não conectar a PROD, VPS, banco remoto, deploy ou serviço externo durante a
  preparação deste runbook.
- Não abrir `ALLOW_REAL_SENDS`, `ASAAS_BILLING_ENABLED`, `BREVO_SEND_MODE`,
  `BROADCAST_ASYNC_ENABLED`, `AgentConfig.ativo` ou qualquer gate Jev.
- Não aplicar migrations fora da lista e da ordem aprovada por `migrate.py`.
- Não automatizar reconciliação, apagar duplicidades, ignorar RLS ou mascarar
  achado com migration manual.
- Não copiar PII, dados pastorais, dumps reais, URLs, credenciais, chaves ou
  conteúdo de `.env` para relatório, chat, log, teste ou commit.
- Não usar backup real no ensaio local nem restaurar backup sobre banco de
  produção.

## Ensaio sintético de contenção e retomada pré-DDL

Validação local em 24/10, base `830decc1`: 54 testes unitários e os sete
cenários Docker aprovados. O inventário independente confirmou que nenhum
container ou rede preexistente foi removido e que não restaram recursos do
ensaio. Revisão independente Claude Opus sem bloqueios de segurança para
execução descartável. Também passaram 129 testes existentes dos workers
no SHA `830decc1`, com dependências simuladas; não são testes de entrypoint
legado. O campo `production_ready` do recibo permanece `false`.

Redis foi um servidor real com dados fictícios; os workers e o provedor eram
simulados. O campo textual `topology` do recibo usa “falsos” para Redis/provedor;
a descrição precisa do alcance é esta. Não interpretar esse texto como mock
do processo Redis ou como prova de domínio do backend.

**Estado: preparação local.** Não é controlador de PROD, não toca release real,
gates reais, workers da aplicação nem workflows.

`deploy/rehearse_legacy_containment.py` cria os próprios recursos descartáveis
(prefixo aleatório e label `pastorai.synthetic.owner` com o UUID da execução):
uma rede `--internal` sem portas publicadas, Redis, um provedor falso com
barreira e quatro processos **simulados** (`deploy/synthetic_legacy_worker.py`):
`backend`, `queue-worker`, `cron-worker` e `broadcast-worker`. Todos são
containers avulsos, sem labels de Compose, como o `broadcast-worker` observado
em PROD. Entrypoint explícito (`python3` ou `redis-server`; o ENTRYPOINT da
imagem nunca roda), usuário `65534:65534`, raiz somente leitura, sem
capabilities, sem montagem do host, `.env`, credencial ou socket do Docker.
Aceita só IDs de imagem locais (`sha256:...`, sem pull) e o caminho do
relatório; não aceita nome, ID, DSN ou host de alvo existente.

Antes de qualquer efeito, o controlador exige contexto Docker local (socket
Unix, sem `DOCKER_HOST`/`DOCKER_CONTEXT`). Sobe o Redis e espera `PING`; depois
o provedor e os quatro processos; espera os marcadores de partida, gravados só
depois do bind; e por fim confirma o HTTP real de `backend` e provedor com uma
probe interna. Valida o conjunto exato de seis containers próprios: posse,
identidade no ledger, imagem, entrypoint, usuário, rede, ausência de portas e
montagens, e configuração de gate sintética. Os valores de gate são fictícios e
ilustrativos (envio aberto, Brevo `live`, broadcast assíncrono desligado), não
um espelho de PROD: lá não há variável ASAAS real e o default não foi
verificado. Eles permanecem inalterados durante todo o ensaio. Imagem ausente
localmente é recusada como `image-not-local-immutable` antes de qualquer
efeito; comando Docker que excede 120 s vira a recusa fixa `docker-timeout`,
sem comando nem saída, e interrompe a contenção ou a retomada.

A contenção envia só SIGTERM, um serviço por vez (`backend`, `cron-worker`,
`broadcast-worker`, `queue-worker`), com prazo e sem SIGKILL. A retomada
pré-DDL é explícita (token), religa os mesmos containers com a API primeiro e
depois os consumidores, validando o conjunto antes de cada partida; uma falha
de partida registra recusa, sem nova tentativa nem retomada automática.

Cenários, cada um com recursos novos:

| Cenário | Esperado |
|---|---|
| `in-flight-completes-after-sigterm` | Com a barreira fechada, um envio real fica em curso e duas pendências entram pela probe antes de qualquer SIGTERM. A barreira abre entre o sinal e a espera: o envio termina (`done`, efeito 1), saída 0. Com `backend` parado, a probe interna é recusada. A pendência que vence na pausa vai para `expired` com os bytes intactos; a outra é enviada uma vez após a retomada. Um broadcast pendente e um agendamento de cron futuro, semeados antes do SIGTERM, mantêm os mesmos bytes no Redis antes e depois da contenção e da retomada, sem efeito, com os gates inalterados. |
| `in-flight-response-lost` | O efeito ocorre e a resposta não chega: o worker desiste no timeout, leva o item a `ambiguous` sem retry e sai com 0. Após a retomada, o efeito continua 1. Broadcast pendente e cron futuro: mesma verificação de bytes do cenário anterior. |
| `post-ddl-mark` | Depois de marcar o ponto de DDL (sem SQL), a retomada do código antigo é recusada. |
| `graceful-timeout` | Processo que ignora SIGTERM, prazo de 3 s: recusa, o processo continua vivo, DDL e retomada recusados. |
| `identity-swapped` | Container trocado: recusa antes de qualquer sinal. |
| `fifth-writer` | Quinto writer na rede: recusa antes de qualquer sinal. |
| `interrupted` | Interrupção depois do primeiro sinal: a sequência para, sem retomada nem DDL. |

Prazos dos cenários físicos: resposta do provedor 15 s, prazo gracioso 30 s,
expiração 50 s.

Como executar (somente em máquina local descartável, pelo runner do revisor):

```bash
python3 deploy/rehearse_legacy_containment.py \
  --worker-image sha256:<ID local de imagem com python3> \
  --redis-image sha256:<ID local de imagem com redis-server >= 6.2> \
  --report /tmp/legacy-containment-report.json
python3 -m pytest deploy/tests/test_legacy_containment.py
```

A limpeza percorre só o ledger de IDs que esta execução criou (containers,
probes, substituto, intruso e rede) e remove cada um apenas se ainda tiver o
label de posse; nunca procura recursos por label. Tenta todos os IDs mesmo se
uma remoção falhar. Ausência só é concluída por uma listagem read-only de IDs;
Docker indisponível ou `inspect` com falha viram erro e sobra no relatório,
nunca "inexistente". Cenário com limpeza incompleta não é PASS, e o erro de
limpeza não substitui o motivo original da falha. O `docker rm -f` da limpeza
remove recurso descartável próprio e não faz parte da contenção. Nunca
reinicia daemon ou host.

**Limites.** Não é controlador de PROD nem prova de prontidão para PROD. O
relatório prova a topologia e o controlador sintéticos. Os workers são
simulados: não prova o tratamento de SIGTERM dos workers reais de `07a3f4d`,
retries da Evolution, reinício do Docker, compatibilidade pós-DDL nem a
semântica de fila dos workers legados. A marca de DDL é só estado do
controlador; nenhum SQL é executado.

## Ciclo de vida do queue-worker real do legado

A fatia seguinte à #573 usa `deploy/rehearse_legacy_queue.py` para executar
`python -m app.workers.queue_worker` do SHA fixo
`07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02`, com dependências do respectivo
`requirements.lock`. O código do aplicativo não é alterado. O evento fictício
é ignorado pelo parser real antes de banco, agente ou provedor, mas percorre
enfileiramento, claim e ACK reais.

Preparação exclusivamente local e sintética:

1. Executar `python3.13 deploy/rehearse_legacy_queue.py materialize --repo .
   --out /tmp/legacy-queue-source-NOVO`. O destino precisa não existir.
   A seleção lê apenas fontes Python permitidas de `backend/app` e o lock;
   não usa checkout/archive completo nem arquivos de ambiente.
2. Preparar uma imagem Python 3.13 com essa árvore em `/opt/legacy` e instalar
   o lock com `pip install --require-hashes -r /opt/legacy/requirements.lock`.
   Não copiar o workspace inteiro. A imagem não pode conter credenciais,
   configurações externas, volumes declarados ou arquivos extras nessa árvore.
3. Executar `python3.13 deploy/rehearse_legacy_queue.py run --repo .
   --legacy-image sha256:ID_LOCAL --redis-image sha256:ID_LOCAL
   --report /tmp/legacy-queue-report.json`, substituindo os IDs por imagens
   locais imutáveis. O programa recusa daemon remoto e não baixa imagens.

O preflight compara fontes com os blobs Git e nomes/versões instalados com o
lock. O ensaio cria Redis e rede interna próprios, sem portas ou montagens do
host, e exige heartbeat, lease e registro. Depois de SIGTERM exige saída zero,
heartbeat parado e remoção do registro/lease; enfileira enquanto parado,
confere preservação, reinicia o mesmo container e exige consumo/ACK e segunda
parada limpa. A limpeza usa os IDs criados pela execução; sobras impedem PASS.

Um PASS cobre esse ciclo de vida, não uma mensagem pastoral em processamento,
transação PostgreSQL, transporte Evolution, demais workers, restart do host,
compatibilidade pós-DDL ou produção. `production_ready=false` permanece.
A etapa posterior é provar uma ingestão ativa com barreira transacional em
PostgreSQL sintético antes de ampliar a conclusão operacional.

Validação local em 24/10/2026: 88 testes aprovados, zero skip; ensaio físico
com sete verificações aprovado, sem divergência de fonte/runtime, limpeza
com zero erros e nenhum container/rede remanescente. Imagem sintética legada
`34083a4f8d5a`, Redis `ff02b58f971e`; 148 fontes/lock conferidos contra o Git.
A prova independente anterior também passou. Não equivale aos quatro checks
de integração do futuro SHA publicado nem a uma verificação de produção.

## Ingestão ativa durante SIGTERM — validada localmente

A etapa seguinte à #574 usa `deploy/rehearse_legacy_queue_active.py` com o processo real do legado
`07a3f4d`, Redis e PostgreSQL descartáveis. A base sintética usa as 78
migrations selecionadas pelo aplicador atual, preservando RLS e triggers.
São duas igrejas fictícias; não há conexão com banco ou número real.

A barreira é o advisory lock já usado pela ingestão para o identificador da
mensagem, antes de escrever Pessoa/Conversation/Message. Isso prova a parada
enquanto a transação aguarda o fence; não prova parada com escritas ainda
não confirmadas. O ensaio precisa observar o worker bloqueado na transação e com o
envelope em processamento antes do SIGTERM. Enquanto a barreira estiver
fechada, o processo deve permanecer vivo e a mensagem ainda não pode estar
confirmada. Após liberar o lock, exige commit único, ACK, deregistro e saída
zero. Reenvios com e sem o marcador Redis devem preservar as contagens.

O tenant vem da instância oficial registrada, inclusive diante de um
`igreja_id` forjado no payload. Uma prova separada usa a promoção real para
`authenticated`, verifica leitura isolada e recusa de escrita na outra
igreja. O trigger legado confirma `pessoas.consentimento`; não se exige
registro em `consent_records` para este caminho.

Esta etapa ainda não comprova turno completo do agente, envio por provedor,
recuperação após DDL ou produção. Pilotos vazios e gates fechados mantêm a
execução dentro do escopo sintético.

Reprodução local, com as imagens imutáveis já preparadas e Docker local:

```bash
python3.13 deploy/rehearse_legacy_queue_active.py run --repo . --report /tmp/legacy-active-report.json
```

As opções `--legacy-image`, `--redis-image` e `--postgres-image` aceitam apenas
IDs locais `sha256:...`; sem downloads ou alvos existentes. O preflight confere
fonte/runtime legados. O banco recebe somente o aplicador atual e os 78 SQLs
selecionados; registros de bootstrap são preservados e conferidos.

Validação final em 25/10/2026: 130 testes aprovados, zero skip (42 novos e
88 de regressão); 20 verificações físicas aprovadas. A barreira, contando
desde antes do enqueue, durou 6,462 s; saída 0 em 0,636 s após liberação.
ACK estável, TTL sem renovação (comparado pelo instante de expiração),
contagens/não lidas preservadas, escrita na própria igreja permitida e
escrita na outra negada especificamente por RLS. Limpeza sem erros, zero
containers e redes remanescentes. Provas independentes também aprovadas.
Revisão Claude incorporada e versão final verificada pelo Codex.

Não se reproduzem papéis de login/timeouts de produção; não se atesta a
integridade de wheels, sitecustomize ou pth instalados. Os testes/ensaio novos
são evidências locais e não foram adicionados aos workflows existentes.
Os quatro checks obrigatórios do futuro SHA publicado são uma prova separada.

## Tick ativo do cron-worker durante SIGTERM — validado localmente

A etapa seguinte à #575 usa `deploy/rehearse_legacy_cron_active.py`, reaproveitando
a guarda de Docker local, a conferência de fonte/runtime de `07a3f4d`, o ledger
de posse e a mesma base sintética de 78 migrations (aplicador atual, sem
`create_all` nem wrappers pausados, bootstrap oficial preservado). O PID 1 é
`python -m app.workers.cron_worker` original, sem patch nem mock, com gates
fechados, piloto vazio, provedores em loopback morto e `CRON_TICK_SECONDS=10`.

A barreira usa a primeira etapa real do tick: a purga cross-tenant de
`calendar_oauth_flows`. O seed cria, numa igreja fictícia própria, um fluxo
expirado e um válido; antes do worker subir, uma conexão separada mantém
`FOR UPDATE` só no expirado. O ensaio exige, por IP dos containers em
`pg_stat_activity`/`pg_locks`, um único backend do worker executando o
`DELETE` e esperando `transactionid` no xid do holder. Envia SIGTERM e, durante
uma janela observada, exige processo vivo, heartbeat `running`, mesmo bloqueio
e banco inalterado (fluxos e digest de todas as tabelas de `public`). Só então
libera e exige: remoção única do expirado, válido idêntico, linha real
`sla=0, crons=0, plan_changes=0, oauth_flows_purged=1`, pedido de shutdown
registrado antes do fim do tick, saída 0 antes do intervalo do próximo tick,
heartbeat `stopped`, Redis só com o heartbeat e nenhuma outra tabela alterada.
Qualquer aviso/erro/traceback no log do worker é recusa. O orçamento de 20 s fica
abaixo dos 30 s de progresso do legado. Ele é medido depois do último check do
conjunto de containers e da reconfirmação do heartbeat `running`, imediatamente
antes de liberar; a decisão usa o tempo sem arredondar (só o relatório arredonda).

Limites: o `stop()` legado só faz `_running=False`; SLA, crons e billing do tick
em curso continuam depois do sinal, então não há contenção antes da saída. O
seed e o bootstrap não deixam trabalho para essas fases (pré-condição
conferida), logo SIGTERM com trabalho real nelas não é provado. O psycopg2
síncrono tende a adiar o handler até o `DELETE` voltar; isso só é observado. Não
prova supervisor/política de reinício, papéis de login ou timeouts de produção,
pós-DDL, outros serviços nem produção (`production_ready=false`).

Reprodução local, com as mesmas imagens imutáveis do ensaio anterior:

```bash
python3.13 deploy/rehearse_legacy_cron_active.py run --repo . --report /tmp/legacy-cron-report.json
```

Primeira rodada em 25/10/2026 (Codex): 172 testes aprovados (42 novos e 130 de
regressão) e ensaio físico aprovado com 13 verificações; bloqueio observado em
5,918 s desde o start do worker, saída 0 em 0,626 s após a liberação, limpeza
sem sobras. A revisão independente não apontou bloqueios nem regressões e pediu
a guarda temporal acima, já aplicada, com testes de recusa sem liberação.
Revalidação final após esse ajuste (Codex, 25/10/2026): 176 testes aprovados,
zero skip (46 novos e 130 de regressão); ensaio físico aprovado com 13
verificações, bloqueio em 6,445 s, saída 0 em 0,652 s após a liberação, limpeza
sem sobras. São evidências locais; os testes/ensaio novos não foram adicionados
aos workflows, e os quatro checks do SHA publicado são prova separada.

## Ciclo de vida ocioso do broadcast-worker real — integrado pela #577 (`92821e35`)

A etapa seguinte à #576 usa `deploy/rehearse_legacy_broadcast.py`, reaproveitando
de `rehearse_legacy_queue.py` a conferência de fonte/runtime de `07a3f4d` (148
fontes + lock), a guarda de Docker local, o ledger e a limpeza por posse. Só há
Redis descartável numa rede `--internal` própria, sem portas, montagens ou
download de imagem; não existe Postgres e `DATABASE_URL`/Evolution apontam para
loopback morto. O PID 1 é `python -m app.workers.broadcast_worker` original,
sem patch nem mock. O container usa `--init=false` explícito e o ensaio exige
`HostConfig.Init` igual a `false`; ausente/`null` (default do daemon, que pode
ter `init: true` e injetar `docker-init` mesmo com `Path=python`) ou `true` é
recusa. Gates: `ALLOW_REAL_SENDS=false`, `BROADCAST_ASYNC_ENABLED=false`,
Brevo `off`, Asaas `false`, piloto vazio e `BROADCAST_WORKER_TICK_SECONDS=10`.

Com esses gates o legado decide `enabled=False` no boot e fica **ocioso**; o
ensaio não abre gate e não afirma estado ativo. Exige: heartbeat `idle` e sua
renovação pelo loop (instante de expiração posterior), Redis só com esse
heartbeat, log com `enabled=False` e o aviso OCIOSO exato como único WARNING
aceito, sem tick, envio, dispatch pausado ou transporte. SIGTERM real: saída 0
antes do próximo tick, heartbeat `stopped`, log igual e TTL não renovado
durante a observação posterior. `docker start` do mesmo container precisa ser
uma nova execução (`StartedAt` novo, segundo boot no log) com `idle`
substituindo `stopped`; o segundo SIGTERM repete a saída 0 e `stopped`.

Ausência de rede não é capturada; é inferida de três fatos: destinos de banco
e Evolution inacessíveis (loopback morto, rede interna sem Postgres), gates
`false` e o caminho ocioso do código legado (`tick()` nunca chamado, sessão
nunca resolvida, `EvolutionClient` sem cliente HTTP até o primeiro uso e
`close()` sem efeito quando nada foi aberto).

Limites: não prova broadcast ativo, trabalho ou transporte Evolution em curso,
pendências no banco, que fechar gate pause fila, supervisor/restart do host,
backend, pós-DDL, RLS nem produção (`production_ready=false`).

Reprodução local, com as mesmas imagens imutáveis legada/Redis dos ensaios anteriores:

```bash
python3.13 deploy/rehearse_legacy_broadcast.py run --repo . --report /tmp/legacy-broadcast-report.json
```

Validação final em 25/10/2026 (Codex): 216 testes aprovados, zero skip (40
novos e 176 de regressão); ensaio físico aprovado com 10 verificações e
`HostConfig.Init=false` conferido; saída 0 em 0,503 s/0,549 s após cada
SIGTERM, heartbeat renovado em 9,947 s/9,948 s, limpeza sem erros nem sobras.
A revisão independente exigiu o PID 1 sem `init` do daemon; a correção foi
confirmada pelo Codex. São evidências locais; os testes/ensaio novos não foram
adicionados aos workflows, e os quatro checks do SHA publicado são prova separada.

## Backend ASGI com HTTP em curso durante SIGTERM — integrado pela #578 (`64d7509d`)

A fatia seguinte (#578; base `6b0b302b`, sem depender da #577, depois atualizada
com a `main` que já contém a #577 em `92821e35`) usa
`deploy/rehearse_legacy_backend.py`. Reaproveita a guarda de Docker local, a
fonte/runtime exatos de `07a3f4d`, o ledger e o Redis próprio. O PID 1 é o console
script real `uvicorn app.main:app --host 0.0.0.0 --port 8000` (CMD do
Dockerfile legado), com `--init=false` conferido, sem patch, mock, rota ou
instrumentação da aplicação. O preflight confere o script contra o RECORD da
distribuição `uvicorn==0.49.0`, o protocolo httptools e as premissas de shutdown
do Uvicorn instalado. Diferenças em relação ao Dockerfile: workdir `/opt/legacy`,
usuário 65534, rootfs read-only, sem `migrations/` e sem healthcheck do Compose.

Configuração: gates fechados, piloto vazio, `EVOLUTION_WEBHOOK_SECRET` fictício
fixo enviado só por header `X-Webhook-Token` (nunca query) e banco em loopback
morto. O único aviso de startup aceito é `Database warmup unavailable`, e
`/health` 200 prova só liveness: não é readiness nem prontidão de produção.
Allowlist exata de avisos: esse warmup (um por boot) e um `Rejected webhook`
da prova negativa (token errado, corpo completo, 401 real e fila vazia). O
relatório leva só marcadores próprios e contagens; o segredo fictício não pode
aparecer nos logs.

Barreira: um probe separado da mesma imagem envia o `POST /whatsapp/webhook`
com `Content-Length` do corpo inteiro e só metade do JSON. O handler legado lê o
corpo antes de autenticar. O probe só publica o READY depois que `TIOCOUTQ` do
socket chega a 0 (bytes confirmados por ACK do servidor, sem `recv`, prazo de
5 s; falha ou timeout encerram o probe e recusam). O controlador exige `outq`
inteiro igual a 0. Antes do SIGTERM, o `/proc` do backend (`docker exec` só
leitura) precisa mostrar a conexão do IP/porta do probe ESTABLISHED,
pertencente ao PID 1, com Recv-Q/Send-Q zero, e a fila precisa estar vazia.
ACK no cliente, Recv-Q 0 no servidor e a conexão retida durante a drenagem
sustentam um ciclo HTTP aberto, não a linha exata do handler
(`request.stream()`). Depois do sinal: backend vivo, log
`Waiting for connections to close`, listener fechado, conexão nova recusada,
mesma conexão retida e lifespan ainda aberto, numa janela observada. Só então
o restante do corpo segue na mesma conexão e se exige: 202
`{"status":"queued"}`, conexão encerrada pelo servidor (sem reuso), um envelope
no `WebhookQueue` real, ordem exata em stderr (resposta antes do lifespan
fechar os pools) e saída 0 sem SIGKILL. A duração da telemetria precisa cobrir o
intervalo sinal→liberação, mas isso é só consistência: inclui o processamento
após a liberação e a latência do kill, então não prova ordem. Os bytes da
fila se mantêm após a parada e após reiniciar o mesmo container sem consumidor;
o segundo SIGTERM também sai com 0.

Orçamentos independentes: barreira 20 s; log de drenagem 10 s após o sinal;
retenção abaixo de 20 s, medida depois do último check; saída em menos de 30 s
após a liberação.

Riscos e limites: a saída 0 depende de PID 1 direto, porque o Uvicorn re-levanta
o SIGTERM após o shutdown e só o PID 1 o ignora; sob init, seria 143. Sem
`--timeout-graceful-shutdown`, um cliente que nunca completa o corpo segura o
shutdown indefinidamente até o prazo do supervisor (SIGKILL). Não prova a
posição interna do handler nem o início do ASGI antes do sinal (inferido), consumo
pelo worker, turno do agente, banco/RLS, retries da Evolution,
supervisor/restart policy, topologia viva (proxy, init, timeouts), pós-DDL nem
produção (`production_ready=false`).

Reprodução local, com as mesmas imagens imutáveis dos ensaios anteriores:

```bash
python3.13 deploy/rehearse_legacy_backend.py run --repo . --report /tmp/legacy-backend-report.json
```

Validação final em 25/10/2026: 279 testes aprovados, zero skip (103 novos e
176 de regressão); ensaio físico (Codex) aprovado com 12 verificações, retenção
de 6,600 s após o sinal, saída 1,202 s após a liberação, segunda parada em
1,168 s, limpeza sem sobras. Premissas do Uvicorn 0.49.0 conferidas na imagem;
revisão independente incorporada. Um request gera um envelope; idempotência de
reenvio não é provada aqui. É prova sobre o HTTP real já existente, não
capacidade nova do agente. Os testes/ensaio não entram nos workflows, e os
quatro checks do SHA publicado são prova separada.

## Transição inicial integrada legado→atual — ensaio local sintético

**Histórico (27/10).** Este ensaio usa 46 migrations, catálogo de 124 e etapa de
reconciliação. Não reflete o candidato atual (51/129, sem reconciliação), e o
adaptador real continua pendente (ver "Plano e prévia atual").

**Estado: código integrado (#579–#581, `84fb7f11`/`74919ee0`/`87ba1e42`); procedimento
ainda sintético.** Não é procedimento executável em PROD, não toca
VPS, Supabase, workflow nem gates reais; `production_ready=false`.

`deploy/backend-release.sh` recusa a instalação atual (sem árvore de release,
checker anterior nem label de revisão). A primeira virada fica a cargo de
`deploy/initial_transition.py` (com `initial_transition_ops.py`,
`initial_transition_files.py` e `initial_transition_candidate.py`), que deixa
um layout `releases/<SHA>` + `current`. O ensaio
`deploy/rehearse_initial_transition.py` (cenários em
`rehearse_initial_transition_scenarios.py`, provedor falso em
`synthetic_evolution.py`) cria, por fixture e com UUID próprio, uma instalação
sintética com a mesma FORMA observada (três serviços por Compose gerado e
prefixado + `broadcast-worker` avulso, todos `restart: always`), não o mesmo
arquivo nem a topologia exata de PROD.

Controlador, em ordem: endpoint local e posse de redes/supports/DSN antes de
qualquer SQL; identidade e fonte exata (148 blobs de `07a3f4d`; 385 do
candidato) e runtime do lock; contenção por papel com `restart=no` persistido e
conferido por inspect ANTES do SIGTERM (sem SIGKILL); efeitos esperados do
drain conferidos item a item e só então snapshot estável (linhas de `public` +
chaves persistentes do Redis db0); reconciliação real por
`reconcile_team_pessoa.py` (prévia/confirmação; não é rollback e não é
desfeita por retomada); backfills de julho com 0 candidatos e
`release_preflight.py`; reconferência fresca (ledger baseline, pendências
exatas, snapshot, ausência de vestígio de DDL, escopo) imediatamente antes do
`ddl-marker` irrevogável; 46 migrations por `migrate.py`, um job próprio por
aplicação; checker do candidato + catálogo comparado a uma reconstrução
independente das 124; candidato em projeto Compose SEPARADO, `/ready` real
`ready` com os três workers e `/health` pela rede de borda; promoção na ordem
layout → readiness nova → `restart=always` → link `current`. Toda invocação
revalida tudo, qualquer que seja a fase registrada; jobs adotados só se idênticos
ao pretendido; probes de leitura sempre novos; falha pós-DDL antes da promoção
contém o candidato (`no` + SIGTERM + saída observada) e exige decisão humana
`retry-candidate`; o legado nunca é religado depois do marcador.
`CONCURRENTLY` inválido, ou índice válido sem linha no ledger, é recusa
persistente: o retry só é aceito com decisão humana e sem nenhum índice da
tentativa anterior (nunca `IF NOT EXISTS` como prova).

Retomada do legado (`resume-legacy`), só antes do marcador e com token ligado ao
journal: em toda invocação, inclusive replay após crash, reconfere endpoint,
posse, identidade/gates, ledger baseline e ausência de vestígio de DDL antes de
cada partida; snapshot de domínio e filas críticas só são exigidos antes do
primeiro consumidor voltar. A intenção de retomar é exclusiva e durável: depois
dela `run` recusa (`legacy-resume-in-progress`) e só a retomada pode continuar.

Filas críticas (nomes e tipos conferidos no código de `07a3f4d` e do candidato):
`pastorai:webhooks` (lista), `pastorai:webhooks:processing:<worker>` (ausente
após o drain), `pastorai:webhooks:dead` (lista) e
`pastorai:webhooks:retry-scheduled` (zset, conferido com score). Quando
esperadas, precisam existir SEM TTL (ou estar ausentes se esperadas vazias) e
são comparadas item a item (SHA-1 por item; score no zset). As expectativas são
reexecutadas no reconcile, imediatamente antes do `ddl-marker` (mesma invocação)
e antes do primeiro start da retomada. O snapshot de estabilidade cobre só chaves
persistentes do db0: chaves com TTL (heartbeats, `pastorai:processed:*`,
`pastorai:webhooks:retry-state:*`, que tem TTL legítimo) ficam fora da igualdade
e só são contadas; não se afirma igualdade de todo o Redis.

Gates: o ensaio principal usa valores sintéticos no FORMATO observado
(`ALLOW_REAL_SENDS=true`, `BREVO_SEND_MODE=live`, broadcast `false`, ASAAS
ausente), com piloto vazio, segredos fictícios e todos os endpoints em
containers próprios numa rede `--internal`; o controlador nunca altera gates e
o candidato precisa carregar os mesmos valores. Isso não satisfaz as guardas do
`backend-release.sh`, que exigem os quatro gates fechados (teste de contrato
`deploy/tests/test_initial_transition_layout.py`). A fixture `broadcast` liga
`ALLOW_REAL_SENDS`/`BROADCAST_ASYNC_ENABLED` só nela (`config_mirror=false`).

Achado de Docker registrado: `docker kill --signal SIGTERM` marca o container
como parado manualmente; `restart: always` não o reinicia na hora, mas o
reiniciaria no boot do daemon. A política `no` persistida é o que cobre esse
caso; o reinício real do daemon não foi exercitado. O controle negativo usa uma
saída não manual (SIGTERM de dentro do container).

**Adoção persistente pelo `backend-release.sh` (local, sintética, 25/10).**
`write_layout` grava `deploy/release-topology.json` (versão 1: projeto
permanente ≠ legado, rede externa existente por nome+ID, nomes dos quatro
serviços, IDs dos quatro legados contidos; nada privado), o helper
`release_topology.py` e `docker-compose.override.yml` com pin do ID verificado
da imagem candidata. O script lê o contrato só do ativo, sob lock e antes da
configuração privada; recusa marcador sem contrato válido e
contrato/marcador/override vindos no candidato (o workflow também recusa esses
caminhos no commit e exige `BACKEND_RELEASE_SAFETY_VERSION=3`). Toda chamada
Compose usa `-p` e base→topologia→checker→pin; o overlay redefine só
`networks.default` (externa), nomes, `depends_on: !reset {}` (sem isso
`compose start` recusa `missing dependency redis`) e põe Redis/Evolution em
profile inativo. Guardas: propriedade (membros do projeto só com nome
contratado, nenhum estranho, legados parados `no` fora do projeto) antes de
recriar; prontidão (sem alias dos quatro serviços em contêiner alheio rodando
na rede, um Redis saudável e uma Evolution rodando) antes de cada start;
contenção para só IDs próprios, independe de dependências, e deixa estranhos
intocados (recuperação humana com configuração, contrato e override do
candidato preservados). O predecessor volta pelo ID de imagem verificado, nunca
por rebuild; com o image store containerd, mover a tag de build apaga o ID antigo,
por isso o script mantém a tag local `<repo>-release:<SHA>` do predecessor e da
candidata construída. Essas tags se acumulam (sem poda automática; limpeza é
tarefa do operador) e um novo release do mesmo SHA move a tag de retenção para a
nova build. A imagem da transição inicial precisa continuar referenciada no host
até o primeiro release posterior (o pin do layout aponta para o seu ID); garantir
isso é trabalho do adaptador real, ainda inexistente. Instalação sem contrato nem
marcador mantém o caminho anterior.

Provas: doubles (`test_backend_release.py`, suíte inteira também no modo
adotado), helper puro, `docker compose config` real do `docker-compose.yml` sem
`.env` e ensaio físico `deploy/rehearse_release_topology.py` (rodada 4: 54
verificações, 71,6 s; o detector de imagens dessa rodada não cobria as builds
B/D feitas pelo Compose. Rodada 5, após integrar `9047c591`: 54 verificações,
76,7 s, sem contêineres, redes, volumes nem imagens restantes, procuradas pelo
prefixo e pelo label de revisão dos seis commits sintéticos; hashes das fontes no
relatório `/tmp/igreja12-release-topology-rehearsal-r5.json`): layout real → release que
falha em `/ready` volta ao layout pelo ID → release saudável → falha volta ao
predecessor construído → recusas físicas por alias concorrente e membro
estranho; legados e dependências com estado idêntico. Transformações no
compose do ensaio: porta publicada (a 8000 do host é de outro processo, nunca
tocado) e tag de build prefixada. Aplicação e checker sintéticos; Evolution falsa, sem
callback real Evolution→backend (não provado); modo digest só
por doubles/Compose config. Pendentes: atualizar `BACKEND_DEPLOY_SAFE_BASE_SHA`
após o merge (não executado), adaptador e janela de PROD, backup, autorização
nominal, decisão sobre gates abertos, escolha das contas da duplicidade,
webhooks recusados durante a janela e legado com `RestartCount>0`.

Limites: daemon/host não reiniciados; retry real da Evolution e mensagens
recusadas na janela não verificados; imagem candidata derivada local NÃO
oficial (camadas de `8fbc14c5`; app/lock/migrations/runner do HEAD; README de
migrations ausente não afeta o manifesto SQL) e legada sintética (`/opt/legacy`,
uid 65534); papéis/pooler/timeouts do Supabase não reproduzidos; turno do
agente não exercitado (piloto vazio); escritores só observados no escopo próprio
(membros das redes, IPs, `pg_stat_activity`, `CLIENT LIST`); chaves Redis com
TTL (heartbeats, marcadores de dedup) fora da igualdade, com filas críticas
exigidas sem TTL; `compose up` manual no projeto legado recriaria com `always`.

**Matriz de evidências (local, sintética, 25/10).** Fonte candidata
`6b0b302bd1c1f84dfef7516babee2b7767d3219c` (não o HEAD futuro da branch); imagem
derivada local `sha256:d9fea6b7…c45`; legada sintética `sha256:34083a4f…562`.
Na rodada 3 (antes da correção da retomada), a suíte completa (`main`,
`pre-ddl`, `post-ddl`, `broadcast` + catálogo de referência das 124) foi
aprovada em 684,1 s, com 28/15/22/12 verificações, catálogo idêntico e
limpeza total.
Relatório: `/tmp/igreja12-initial-transition-round3-full.json`. Rodada 4:
somente a retomada mudou (evidência de execução efetiva em vez de intenção;
crash antes do update, depois do update e depois do start real); `pre-ddl`
reensaiado sozinho e aprovado com 17 verificações e limpeza total
(`/tmp/igreja12-initial-transition-round4-preddl.json`; status `partial-pass`
por ser execução parcial, que nunca vale como suíte completa). Testes: 53
unitários/contrato dos módulos novos; regressão ampla de `deploy/tests` com 385
aprovados, 19 pulados e 1 teste PG17 não executado (exige
`BACKEND_RELEASE_TEST_DATABASE_URL`, só no CI). Conferência independente do
Codex: 229 testes (53 novos/contrato + 176 de regressão), zero skip. CI do SHA
publicado: não verificado até rodar. Os demais cenários não foram repetidos após a rodada 4 porque não
passam pelo código alterado, salvo a recusa pós-DDL, que ocorre antes dele.

**Recuperação da reconciliação (revisão da PR #579).** Antes do apply, na
mesma invocação que reconfere o snapshot de settle (banco e Redis), o journal
grava uma linha de base só com digests e contagens. Após queda depois do commit,
`run` e `resume-legacy` adotam o mesmo job, sem reaplicar (a retomada nunca cria
nem inicia o apply), e só aceitam o delta exato: `pessoa_id` nulo na conta
corrigida e exatamente uma linha de auditoria da operação idêntica à do serviço
(ator, alvo, campos NULL, `detalhe` completo); nada mais em `public`, auditoria
alheia (inclusive sem `operation_id`) ou Redis persistente. O snapshot gravado é
o da leitura verificada. Rodada 6, cenários selecionados (`partial-pass`, não
suíte completa): `pre-ddl` 21 verificações (crash após commit real; alteração de
auditoria sem `operation_id` e de campo da auditoria da operação recusadas em
PostgreSQL sintético) e `main` 28; limpeza total
(`/tmp/igreja12-initial-transition-round6-reconcile.json`). A suíte completa
continua sendo a da rodada 3. Testes em Python 3.13: 71 + 8 subtestes dos
módulos novos e 4/4 provas independentes (conferência do Codex: 247 + 8 subtestes);
regressão ampla de `deploy/tests` com 401 aprovados, 19 pulados, 1 desmarcado
(PG17 de CI) e 5 falhas ambientais em `test_maintenance_schema*.py` por
`psycopg2` ausente no venv 3.13 (passam no venv 3.12 com o driver). CI do novo
SHA: pendente. Limites: digests e contagens não distinguem uma escrita alheia
que reproduza exatamente o delta autorizado nem cobrem esquemas fora de `public`.
Controle negativo: o predicado agora é relativo ao contador e `StartedAt`
observados; a causa da falha intermitente da rodada 5 (possível reinício antes
do sinal) é hipótese não confirmada.

**Retomada de legado com `RestartCount>0` (local, sintético).** Semântica medida
no Docker 29.9.2: reinício automático incrementa o contador, `update`/`stop` o
mantêm e `docker start` manual o zera. A contenção continua comparando o k
observado. Na retomada, um papel só conta como retomado se estiver rodando com
`StartedAt` novo, política original e contador 0 (nunca o conjunto {0, k}); o
estado é relido antes do `done`, e um reinício nesse intervalo recusa
(`legacy-restarted-during-resume`) sem gravar `done`. Antes de cada novo start e
antes da fase final, os papéis já retomados são revalidados
(`legacy-resumed-state-changed`). O replay terminal só retorna depois de
endpoint, posse, identidade/gates/política, mesma execução e ausência de DDL;
dados, filas e escopo não são comparados, porque os consumidores legítimos os
alteram. Ensaio `pre-ddl` (`partial-pass`, cenário selecionado; Docker 29.9.2):
queue-worker com k = 1 antes do observe, k mantido na contenção, 0 no mesmo ID ao
retomar, `done` com 0. Duas quedas do controlador depois do start real e antes do
`done`: backend (k = 0) e queue-worker (k = 1, contador em execução 0); o replay
adotou a mesma execução (mesmo ID e `StartedAt`, um único `done`) e o backlog m2
foi consumido uma vez. Replay terminal aceito após o backlog consumido e recusado
após um reinício real; 28 verificações, limpeza total
(`/tmp/igreja12-legacy-resume-preddl-r2.json`). A recusa terminal é diagnóstica:
não desfaz uma retomada concluída, e uma manutenção legítima posterior (por
exemplo, reinício) também a faz recusar. Limites: um `docker start` manual
alheio entre a intenção e o start do controlador é indistinguível; reboot do
daemon não provado; durante uma corrida, no máximo um papel a mais pode
iniciar; uma recusa no meio não desfaz os papéis já retomados; o sucesso é
pontual, não supervisão contínua.

## Envio ativo do broadcast-worker real durante SIGTERM — validado localmente

`deploy/rehearse_legacy_broadcast_active.py` reaproveita a montagem de
`rehearse_legacy_queue_active.py`: fonte e runtime de `07a3f4d` conferidos,
Postgres/Redis efêmeros, rede `--internal` sem portas nem montagens, as 78
migrations pelo `cmd_apply` atual e limpeza por posse. O PID 1 é o
`python -m app.workers.broadcast_worker` original, sem patch nem mock e com
`HostConfig.Init=false`. `ALLOW_REAL_SENDS` e `BROADCAST_ASYNC_ENABLED` ficam
`true` **só nesse container sintético**. A Evolution aponta para uma falsa na
mesma rede, com chave pública fictícia. Lease (120 s), intervalo de envio, tentativas
e timeout HTTP (15 s) continuam nos defaults legados. A falsa é um container da imagem legada só com
stdlib + `redis`. Registra cada requisição antes de responder, recusa
rota/chave/corpo inesperados e retém a primeira até a liberação.

Seed fictício: duas igrejas com conexão `online`, três pessoas elegíveis
(números `009…`, DDD inexistente). A audiência vem de
`resolve_recipient_snapshot` numa sessão `mark_tenant_scoped` e o envio
imediato de `materialize_immediate_broadcast`, sem router. Resultado: três
entregas `pendente`, duas na igreja A e uma na B.

O ensaio exige, nesta ordem:

1. Antes do sinal: a falsa retém a 1ª requisição. A entrega retida é
   identificada pelo número recebido e está `em_envio`, com `tentativas=1`,
   lease de 120 s vivo e `claim_por` do PID 1; as outras duas seguem idênticas
   ao seed.
2. `docker kill --signal SIGTERM`: log legado `transport already in progress`,
   processo vivo, uma única requisição, ledger e restante do banco inalterados.
3. Liberação antes de 8 s após observar a retenção (abaixo do timeout HTTP e do
   TTL do heartbeat). O total do comando SIGTERM até a saída confirmada é
   medido a partir de antes do `docker kill` e recusado se chegar a 10 s, o
   grace padrão do Docker. É um limite superior do trecho observado, não prova
   de `docker stop` automático, supervisor ou SLA. Saída 0 e resultado gravado
   pelo próprio worker, com lease e claim limpos: `aceito`, ou
   `desconhecido`/`http_500` com `--held-status 500`. As demais entregas ficam byte-idênticas ao seed, o
   heartbeat vai a `stopped` e nada muda por intervalo de envio + tick.
4. `docker start` do mesmo container (`StartedAt` novo): exatamente +2
   requisições, para os números pendentes, sem repetir a retida. Ocorrências
   finalizadas, broadcasts `enviado`, reaper 0, um tick ocioso sem requisição e
   SIGTERM ocioso com saída 0, também com total abaixo de 10 s.

Em todas as fases (seed, retenção, parada, drenagem e final), antes de
comparar por igreja ou telefone, o ledger precisa ter exatamente 2 broadcasts,
2 execuções e 3 entregas, com chaves únicas e os mesmos IDs do seed. Linha
extra ou substituída é recusa. O relatório registra só essas contagens e
unicidades por fase, sem dados das linhas.

Limites: o `stop()` legado não espera o HTTP (`RLock` reentrante na mesma
thread) e há janela entre a checagem de parada e o POST. O ensaio prova que
não há **segundo** envio após o sinal, não que nenhuma requisição comece depois
dele. Não prova `docker stop` com grace vencido/SIGKILL durante o HTTP, envio
agendado, 429/retry, vários workers, supervisor, queda de PG/Redis,
router/autorização, papéis/timeouts de produção, pós-DDL nem produção
(`production_ready=false`). A ausência de tráfego externo é inferida (rede
interna, falsa como única receptora e contagens), não capturada. Nas rodadas
locais a 1ª entrega veio sempre da igreja A. O caso da retida na igreja de
entrega única (ocorrência finalizada no 1º ciclo) foi coberto só por teste
unitário.

Reprodução local, com as mesmas imagens imutáveis legada/Redis/Postgres:

```bash
python3.13 deploy/rehearse_legacy_broadcast_active.py run --repo . --report /tmp/legacy-broadcast-active-200.json
python3.13 deploy/rehearse_legacy_broadcast_active.py run --repo . --held-status 500 --report /tmp/legacy-broadcast-active-500.json
```

Validação local em 26/10/2026 (Claude; revisão Claude e Codex aprovada), depois de
corrigir a cardinalidade e medir o total: 329 testes aprovados, zero falhas e
zero skip (113 novos e 216 de regressão). Rodadas físicas finais aprovadas,
uma 200 e uma 500, com 19 verificações cada. Comando SIGTERM → saída
confirmada em 4,153 s/4,057 s, ocioso em 0,478 s/0,423 s. Ledger 2/2/3 com
chaves e IDs do seed em todas as fases. Limpeza sem erros nem sobras. São evidências locais: os testes e o ensaio novos não
entram nos workflows, e os quatro checks do SHA publicado são prova separada.

Compatibilidade encontrada na integração com a `main` (26/10/2026): as
migrations `20261030_100000`/`110000`/`120000` (#583–#585) elevaram o total
ativo para 127 (129 após as #588/#590; a seleção de 78 não muda), e `select_baseline` (`deploy/rehearse_legacy_queue_active.py`,
usado por este ensaio e pelos de fila, cron e transição inicial) recusava com
`baseline-count`, porque exigia 124 no total. Agora a guarda fixa só as 78
migrations antes do corte `20261015`; as posteriores não são selecionadas nem
lidas pelo `select_baseline` e não entram no bundle (o `migration_files()` real
ainda abre cada arquivo para ler o marcador de pausa). Conferido sem Docker no head integrado: 127 ativas, 78 selecionadas,
com nomes, SQL, runner e digest do bundle idênticos aos de `cf291a15`. As
rodadas físicas acima são anteriores e não foram repetidas.
