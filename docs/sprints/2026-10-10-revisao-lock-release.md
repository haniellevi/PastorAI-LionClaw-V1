# Lock comum aos modos de release

O review P1 do #473 identificou que o modo legado podia executar enquanto o
modo por digest mantinha seu lock. Ambos usam os mesmos containers e link ativo,
portanto a concorrência poderia ativar ou recuperar o release incorreto.

A aquisição do lock foi movida ao caminho comum, antes de consultar o release
ativo. O descritor permanece aberto durante ativação, recuperação e limpeza.
Uma segunda execução recusa antes de Docker ou cópia de configuração. A janela
operacional deve usar este executor revisado em todas as invocações.

Validação local com Python 3.13, diretórios temporários e provedores simulados:
cinco casos passaram, incluindo dois subcasos de concorrência. As verificações
usam o lock real do sistema nos dois modos, durante ativação e recuperação,
e confirmam sua liberação após saída. JUnit: sete resultados, sem falhas,
erros ou skips. A suíte de release, parser Compose e runbook também passou
antes da adição dos dois casos de recuperação, que passaram na rodada focada.

CI do novo SHA será obrigatório antes de resolver o review e integrar. Nenhum
release, acesso ao banco ou operação de infraestrutura foi executado.
