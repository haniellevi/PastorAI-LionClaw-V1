# Revisão independente, V2a Agenda, candidato 03

## Identidade do candidato

- Base: `3e8306e9dfd5e3dec3097f3e8a701829b4d7aa36`.
- Patch SHA256: `2397128ed04e53732a6d034a8c1836435e444965b7437b0eeb7f07b3fbd4c0bb`.
- Manifesto: `V2A-CANDIDATE-03.json`.
- Conferência: 8 de 8 blobs correspondem ao manifesto. O único delta em relação ao C02 está em `backend/tests/test_whatsapp_agenda_pg.py`, SHA256 `b44374246f3539b16e6804481f8d3589f1bfb074e0d609372866bdd766def0bb`.

## Rechecagem do delta Clerk

O delta corrige a causa da falha anterior sem reduzir os guards de produto:

- A fixture passa a alinhar `agent_identity.get_settings` à configuração sintética já usada pelo resolvedor de privilégio, preservando versão de termo e segredo efetivo iguais na emissão, confirmação e leitura da prova.
- A prova é criada pelo serviço real `confirm_identity_challenge`, com challenge emitido no inbound anterior, escopo de tenant e sessão Clerk sintética válidos. Não há inserção manual de prova que contorne integridade.
- Antes da segunda rota, o teste abre uma sessão de execução com RLS e exige `PrivilegeContext` sensível com `proof_id`. Assim, o teste distingue falha de prova ou fingerprint de uma falha na projeção de rascunho.
- A expectativa final permanece restrita a `Rascunho: Culto` e confirma que o título livre não aparece no outbound.

Nenhum P1 ou P2 novo foi encontrado no delta. As conclusões de fonte do C02 permanecem válidas para os sete arquivos inalterados.

## Evidência conferida

- `/tmp/v2a-pg-final.xml`: 117 testes, 0 falhas, 0 erros e 0 skips, em 79,534 s.
- `/tmp/v2a-offline-verified.xml`: 5.881 testes, 0 falhas, 0 erros e 0 skips, em 36,14 s.
- Li os dois XML diretamente: há 117 e 5.881 elementos `testcase`, respectivamente, sem elementos `failure`, `error` ou `skipped`.

## Parecer técnico final

APTO técnico limitado para o candidato C03 e seu patch exato. A evidência cobre a projeção, gates, RLS, retry, prova Clerk e regressões offline no hash congelado. Este parecer não substitui a revisão Sarah nem autoriza merge, deploy, flags, provedor ou produção.

## Limites

- Não executei PostgreSQL, provedor, rede ou operação externa.
- A configuração efetiva de modelo e esforço não é exposta nesta sessão.
- Duas execuções offline anteriores ficaram bloqueadas no sandbox por AnyIO/TestClient. A evidência final acima vem da execução `env -i` com fakes; o nó isolado sob a avaliação exata passou em cerca de um segundo, conforme recibo do coordenador.

## Próximo gate

O próximo gate humano permanece a decisão nominal sobre a PR após as revisões independentes exigidas, incluindo Sarah.
