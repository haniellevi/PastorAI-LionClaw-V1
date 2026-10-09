# Acompanhamento do plano

Painel local que mostra o andamento de [`docs/ops/refatoracao-modular-plano.md`](../refatoracao-modular-plano.md): o que foi feito, o trabalho atual, bloqueios e tarefas futuras, com evidências. É uma visualização do plano e de seus registros. Não cria prazos, estimativas nem outro plano.

## Usar

```bash
./acompanhar.sh            # lê o GitHub (somente leitura) e regenera o painel
./acompanhar.sh offline    # regenera sem consultar o GitHub
./acompanhar.sh verificar  # só valida tarefas.json
./acompanhar.sh servir     # regenera e serve em http://127.0.0.1:8791/painel.html
```

O painel também abre direto do arquivo `docs/ops/acompanhamento/painel.html`, sem servidor. Só é preciso Python 3 e, para a leitura do GitHub, o `gh` autenticado. Nenhum token chega ao navegador: o `gh` roda no terminal e grava o resultado em `github.json`.

## Dentro do Claude Code (mod)

O painel também existe como **mod do Claude Code** (`docs/ops/acompanhamento/mod/`): um painel ao lado da conversa, com o pipeline, as barras de progresso, as tarefas, os bloqueios e o que o Claude está fazendo agora. Ele só lê `docs/ops/acompanhamento/dados.js` e se atualiza a cada poucos segundos, então acompanha o que `./acompanhar.sh` grava enquanto o Claude trabalha.

```bash
./acompanhar.sh mod        # abre o Claude Code com o mod carregado (claude --plugin-dir ...)
```

No Claude Code, digite:

- `/plano`: abre o painel. Teclas: `1` Pipeline, `2` Tarefas, `3` Bloqueios; na lista, Tab até uma tarefa e Enter abre os detalhes (`b` volta); Esc fecha.
- `/plano-faixa`: liga ou desliga uma linha de progresso fixa acima do prompt (a escolha fica salva).

Requisitos e cuidados:

- Claude Code v2.1.287 ou mais novo no terminal (v2.1.286 no app Desktop, aba Code).
- **O mod não carrega se `disableAllHooks` estiver ligado** nas suas configurações (por exemplo, em `.claude/settings.local.json`). Isso desliga todos os mods e hooks de configuração; o mod não altera essa chave.
- Um mod roda com as suas permissões. Este só lê `dados.js` (`$.fs.read`/`$.fs.exists`), guarda a escolha da faixa em `$.store`, observa as chamadas de ferramenta sem alterá-las e não escreve arquivos, não usa rede nem processos. Confira com `claude plugin validate docs/ops/acompanhamento/mod`.
- Para usar sem o script, em outra sessão: `claude --plugin-dir /caminho/para/docs/ops/acompanhamento/mod`.
- Testes do mod: `claude plugin test` dentro de `docs/ops/acompanhamento/mod`. Não rodam no CI do produto.
- O desenho do pane foi validado por teste nos dois apps (terminal e Desktop). Para ver o aspecto real, abra o painel numa sessão; a vista não foi conferida a olho aqui.

## Arquivos

| Arquivo | Papel | Edição |
|---|---|---|
| `tarefas.json` | Tarefas, dependências, estado, indicadores, evidências, próxima ação e histórico | Manual, versionado |
| `github.json` | Última leitura do GitHub (PRs, checks, `main`, monitor) | Gerado por `atualizar.py` |
| `dados.js` | Junção dos dois acima, carregada pelo painel | Gerado |
| `painel.html`, `painel.css`, `painel.js` | Visualização no navegador | Código |
| `mod/` | Visualização dentro do Claude Code (`/plano`) | Código |
| `atualizar.py` | Valida, consulta o GitHub e gera `dados.js` | Código |

## Procedimento ao trabalhar numa tarefa

1. **Iniciar:** em `tarefas.json`, mude o `estado` para `em_andamento` e escreva a `proxima_acao`.
2. **Concluir uma etapa** (PR aberto, teste rodado, CI verde): registre o fato em `evidencias` (data, tipo, descrição, link ou SHA) e ajuste os `indicadores`.
3. **Bloquear:** `estado: "bloqueada"` e o motivo em `bloqueio`. Se só está esperando uma ação externa, use `aguardando` e mantenha o estado.
4. Rode `./acompanhar.sh`. O comando valida o registro, atualiza a leitura do GitHub e regenera o painel.
5. Commite `tarefas.json`, `github.json` e `dados.js` junto com a mudança.

## Regras

- **Estados:** `futura`, `pronta`, `em_andamento`, `em_validacao`, `bloqueada`, `concluida`. `pronta` exige todas as dependências concluídas.
- **Indicadores** (separados): implementação, validação local, CI, integração na `main`, publicação em DEV e publicação em PROD. Status possíveis: `nao_iniciado`, `em_andamento`, `parcial`, `ok`, `pendente`, `falhou`, `nao_aplicavel`, `desconhecido`.
- **CI e integração na `main`** vêm do GitHub quando a tarefa tem `pr_referencia`. Um PR verde e aberto aparece como “Validado — aguardando integração”.
- **Publicação** só vale `ok` com uma evidência do mesmo tipo (`publicacao_dev` ou `publicacao_prod`). Merge ou CI verde não publicam nada.
- **`concluida`** exige evidência e integração na `main` comprovada (ou `nao_aplicavel`).
- **Dependências:** `depende_de` impede começar; `integra_apos` impede integrar.
- **Proporção:** o painel mostra tarefas concluídas ÷ tarefas cadastradas. É contagem de itens, não de esforço.
- Não registre percentual, prazo, teste executado ou tarefa concluída sem evidência.

## Quando o GitHub não responde

A última leitura de cada item fica em `github.json`, marcada como desatualizada, e o painel avisa no topo. Nada é apagado.

## Quando o plano mudar

Se a ordem, o escopo ou os critérios de uma fase mudarem, atualize o plano e `tarefas.json` na mesma PR. O validador (`./acompanhar.sh verificar`) recusa dependência inexistente, ciclo, tarefa bloqueada sem motivo e tarefa concluída sem evidência.
