# test-local.sh rejeita alvo desconhecido (F0, T04)

Data: 09/10/2026. Base: `origin/main` `d36ab813`. Tarefa T04 do
[plano de refatoração](../ops/refatoracao-modular-plano.md).

## Problema

`./test-local.sh <alvo>` com alvo inexistente (por exemplo `bakend`) terminava
com exit 0 sem executar nenhum teste: um erro de digitação parecia sucesso.

## Mudança

- `test-local.sh` valida o alvo logo após lê-lo e, se não for `todos`, `backend`
  ou `frontend`, imprime a mensagem em stderr e sai com código 2, antes de
  executar qualquer ferramenta.
- `backend/tests/test_test_local_script.py` exercita o script com um Python
  falso: alvo inválido falha sem invocar a ferramenta; `backend` continua aceito.
- Sem CLI nova. Encaminhamento de argumentos e seleção rápida ficam para depois.

## Evidência

- Reprodução com o script de `origin/main`: alvo `bakend` → exit 0, sem saída.
- Com a correção: exit 2 e `Alvo desconhecido: 'bakend'. Use: todos, backend ou frontend.`
- `pytest tests/test_test_local_script.py`: 2 passed (venv do checkout principal).
- Não executado localmente: suíte completa, `ruff` (não instalado no venv usado),
  CI. Os quatro checks de produto dependem do PR.

## Reversão

Revert do commit; sem dados nem migrations.
