# Jev: configuração pelo Console da Plataforma

Base: `4bc5ef1` (merge da PR #418). Branch: `claude/friendly-cerf-4h8b87`.
Ambiente: nuvem, dados sintéticos. Nenhum acesso a DEV, PROD, VPS ou TypeSafe.

## O que foi feito

- **Tabela `platform_jev_settings`** (migration `20260926_120446`):
  - tem linha única e não tem `igreja_id`;
  - tem RLS com policy restritiva e privilégios revogados de `anon` e
    `authenticated`, como `platform_orchestrator`;
  - o CHECK recusa igreja listada sem data de DPA, modelo fora do padrão
    `jev-*` e timeout fora de (0, 10].
- **`PUT /admin/jev/config`**:
  - grava a chave cifrada com `services/crypto.py`, o modelo, o timeout, a data
    do DPA e as igrejas;
  - audita cada gravação como `jev_configurar`, sem a chave;
  - `GET /admin/jev` passa a dizer de onde vem a chave (console ou ambiente) e
    quando ela mudou.
- **`effective_settings`** em `semantic_triage.py`: o valor salvo pelo console
  vale sobre o ambiente, e campo nulo cai no ambiente. Se a chave salva não
  decifrar, ela conta como não configurada. Não há queda silenciosa para a
  chave do ambiente.
- **Formulário no `JevModal`**:
  - a chave é só para gravar, em campo de senha;
  - as igrejas vêm da lista do console e ficam travadas até informar o DPA.

## Decisões

- `ALLOW_REAL_SENDS` e a URL da API ficam só no ambiente. A URL, editável pelo
  console, poderia desviar a chave para outro servidor.
- A lista de igrejas é um `uuid[]` sem FK. Uma igreja excluída aparece como
  "não encontrada" e sai da lista no próximo salvamento.
- Trocar a `SECRETS_ENCRYPTION_KEY` do servidor torna a chave salva ilegível,
  e ela precisa ser digitada de novo, como as chaves OpenAI.

## Pendente

- Aplicar a migration no PROD antes do deploy do código, com backup e revisão
  da Sarah; o passo a passo da Fase 1 foi atualizado.
- Chave da TypeSafe e DPA reais; J1 continua fechado.

## Verificação

- `./test-local.sh` terminou com exit 0.
  - Backend: 5.034 testes, 5.010 aprovados e 24 pulados (seleção sem RLS).
  - Frontend: 870 testes aprovados, mais typecheck.
  - `npm run lint` e `npm run build` passaram.
- 19 casos novos em `test_platform_jev.py`:
  - acesso restrito ao master;
  - chave cifrada que nunca volta;
  - console valendo sobre o ambiente e campo vazio caindo nele;
  - chave ilegível;
  - remover e manter a chave;
  - dez recusas de valor, entre elas igreja sem DPA, modelo, timeout e chave;
  - ausência de cifra no servidor;
  - teste de conexão usando a chave do console.
- 3 casos `rls_integration` em `test_platform_jev_settings_migration.py`:
  - a migration aplicada duas vezes;
  - a tabela fechada para `anon` e `authenticated`;
  - a linha única e as travas de DPA, modelo e timeout.

  Passaram em PostgreSQL 16 local; no CI rodam em PostgreSQL 17.
- 3 casos novos em `admin-api.test.ts` e 5 em `JevModal.test.ts`.
