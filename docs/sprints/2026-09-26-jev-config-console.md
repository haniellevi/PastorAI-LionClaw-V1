# Jev: configuração pelo Console da Plataforma

Base: `4bc5ef1` (merge da PR #418). Branch: `claude/friendly-cerf-4h8b87`.
Ambiente: nuvem, dados sintéticos. Nenhum acesso a DEV, PROD, VPS ou TypeSafe.

## O que foi feito

- **Tabela `platform_jev_settings`** (migration `20260926_120446`):
  - tem linha única e não tem `igreja_id`;
  - tem RLS com policy restritiva e privilégios revogados de `anon` e
    `authenticated`, como `platform_orchestrator`;
  - o CHECK recusa igreja listada sem data de DPA, modelo fora do padrão
    `jev-*` e timeout fora de (0, 10];
  - uma pós-condição no fim aborta a transação se a tabela não ficar como
    esperado, por exemplo uma tabela pré-existente com outro formato.
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
- **Deploy sem a migration:** se a tabela não existir, o `GET /admin/jev`
  mostra só o ambiente e salvar responde 409 pedindo a migration.
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
- O runtime (`log_shadow_triage`) continua lendo só o ambiente. A sessão com
  escopo de tenant roda como `authenticated`, que não lê a tabela. O J1
  resolve `effective_settings` numa sessão de plataforma e passa `settings=`.

## Revisão da Sarah (26/09)

- **Merge da PR: GO.** Aplicar a migration no PROD: NO-GO por enquanto.
- **Corrigido nesta PR:**
  - a pós-condição fail-closed na migration;
  - o runtime voltou ao ambiente, com a regra do J1 anotada no plano;
  - o 422 não ecoa mais a chave colada: saiu o `max_length` do Pydantic, e o
    limite de 512 é conferido no handler;
  - o teste prova que o dono da tabela ainda lê.
- **Sem mudança:** sem `FORCE ROW LEVEL SECURITY`, como `platform_orchestrator`.
  O dono é o papel de serviço, que ignora a RLS de qualquer forma.

## Pendente

- Próximo portão, com a Sarah: sessão de reconciliação só leitura (backup,
  inspeção por SQL e ledger), sem aplicar nada novo. Depois, a sessão de
  aplicação. A migration do Jev é decisão separada. O passo a passo da Fase 1
  foi atualizado.
- O roteiro do Maestri precisa incluir `20260822_225752` e, quando decidido,
  `20260926_120446`.
- Chave da TypeSafe e DPA reais; J1 continua fechado.

## Verificação

- `./test-local.sh` terminou com exit 0.
  - Backend, depois das correções da Sarah: 5.038 testes, 5.014 aprovados e
    24 pulados (seleção sem RLS).
  - Frontend: 870 testes aprovados, mais typecheck.
  - `npm run lint` e `npm run build` passaram.
- 22 casos novos em `test_platform_jev.py`:
  - acesso restrito ao master;
  - chave cifrada que nunca volta;
  - console valendo sobre o ambiente e campo vazio caindo nele;
  - chave ilegível;
  - remover e manter a chave;
  - onze recusas de valor, entre elas igreja sem DPA, modelo, timeout e chave,
    sem ecoar a chave;
  - ausência de cifra no servidor;
  - banco sem a tabela: status pelo ambiente e 409 ao salvar;
  - teste de conexão usando a chave do console.
- 4 casos `rls_integration` em `test_platform_jev_settings_migration.py`:
  - a migration aplicada duas vezes;
  - a tabela fechada para `anon` e `authenticated`, e o dono ainda lê;
  - a linha única e as travas de DPA, modelo e timeout;
  - uma tabela pré-existente com outro formato aborta a migration.

  Passaram em PostgreSQL 16 local; no CI rodam em PostgreSQL 17.
- 3 casos novos em `admin-api.test.ts` e 5 em `JevModal.test.ts`.
