# Jev: erro do console, custo em US$ e avaliação offline J0

Base: `92eed57` (merge da PR #417). Branch: `claude/friendly-cerf-4h8b87`.
Ambiente: nuvem, dados sintéticos. Nenhum acesso a DEV, PROD, VPS ou TypeSafe.

## O que foi feito

- **Erro "Não foi possível carregar o status do Jev".** É um 404: o frontend da
  Vercel sai do `main` sozinho e o backend de produção é anterior à PR #413
  (último release registrado na VPS: `c525d6a`, PR #303, lido em 15/09). O
  console agora diz "backend em produção desatualizado; faça o deploy" no
  status e no teste de conexão (`frontend/src/lib/admin-api.ts`). A correção
  de fato é o deploy (B13). O passo a passo da Fase 1 foi reordenado: backup,
  migrations pendentes por SQL (o ledger `public.schema_migrations` estava
  ausente em 28/08), deploy com `ALLOW_REAL_SENDS=false` e só depois a lista
  piloto.
- **Custo de IA em US$.** `ai_usage_logs.custo` é estimado em dólar e aparecia
  como R$ no console (B14). Novo `frontend/src/lib/ai-cost.ts`.
- **J0, avaliação offline.** `backend/scripts/jev_eval.py` e o corpus
  `backend/scripts/data/jev_corpus_v1.jsonl` (207 frases sintéticas, 60
  armadilhas). Sem chave, mede só as regras. Com `--jev`, mede o Jev com as
  mesmas perguntas do módulo sombra, em instruções PT e EN, com um cliente
  HTTP único, teto de custo e relatório só com ids.
- Comentários e documentos do "gate D3" atualizados (removido na Fase 0, commit
  `adb6b6e`). Variáveis do Jev vazias em `deploy/.env.example`. Banner de
  sucesso do teste do Jev com estilo neutro.

## Baseline das regras (sem Jev)

| Sinal | Resultado no corpus |
|---|---|
| Crise | 0 de 42 detectadas: não existe regra (B6) |
| Opt-out | 10 de 42 pedidos (24%); 2 falsos opt-outs, "sair da lista de espera" e "cancelar o envio das mensagens" (B15) |
| Aceite do termo | 8 de 14 respostas negativas gravariam consentimento, como "sim, mas não autorizo" e "aceito não"; 6 de 18 aceites válidos recusados, como "claro" e "pode ser" (B4) |
| CSIM | as 12 armadilhas silenciariam o contato, como "trabalho numa empresa… célula"; 7 de 12 casos reais pegos (B5) |
| Relatório | 7 de 8 mensagens de líder que não são relatório virariam "Relatório recebido!"; 2 de 12 relatórios com números por extenso perdidos (B15) |

O corpus foi escrito para expor erros: as porcentagens descrevem o corpus, não
o tráfego real.

## Decisões

- **Custo não é a alavanca.** O Jev custa cerca de US$ 0,00003 por mensagem e
  acrescenta cerca de 1 s por chamada; o custo de IA acumulado da plataforma é
  US$ 0,03. O valor está em acertar as decisões acima.
- **O J0 não usa `ALLOW_REAL_SENDS`.** O `--jev` só envia o corpus
  versionado, revisado no git como sintético, e recusa qualquer outro arquivo,
  porque a redação de egresso não detecta nome, endereço ou relato. O veredito
  fica INCONCLUSIVO se alguma frase ficar sem resposta (achados P1 e P2 da
  revisão do Codex).
- **Política por sinal.** Crise e opt-out somam à regra (regra OU Jev);
  aceite, CSIM e relatório só passam com regra E Jev de acordo, e o Jev nunca
  concede consentimento sozinho.

## Pendente

- Deploy do backend pelo proprietário, pelo passo a passo da Fase 1.
- Chave da TypeSafe para rodar `--jev` (lista de espera ou Vercel AI Gateway,
  que vira mais um processador) e frases escritas pelo pastor no corpus antes
  da decisão de GO.
- J1 (sombra) só com J0 = GO, DPA com a TypeSafe e termo LGPD que cite IA e
  processador estrangeiro.
- Correções de regex B4, B5 e B15 e detecção de crise B6, na Fase 2, usando
  este corpus como critério.

## Verificação

- `./test-local.sh` com exit 0, com Python 3.13.12 e Node 24.19.0 passados por
  `PASTORAI_PYTHON` e `PASTORAI_NODE_BIN`. Backend: 5.014 testes, 4.990
  aprovados e 24 pulados (seleção sem RLS). Frontend: 862 testes aprovados em
  98 arquivos, mais typecheck.
- Também passaram `npm run lint` e `npm run build`.
- 18 casos novos em `backend/tests/test_jev_eval.py`, com a API simulada por
  `httpx.MockTransport`: corpus válido e sintético, baseline sem rede, `--jev`
  sem chave ou com outro corpus, métricas exatas, teto de custo, falha total e
  parcial da API e braço EN. Mais 5 casos em `admin-api.test.ts` e 3 em
  `ai-cost.test.ts`.
- Com o venv dentro de `backend/.venv-runtime`, o teste de privacidade
  `test_source_contact_privacy` varre os pacotes instalados e falha: ele exclui
  `.venv`, mas não `.venv-runtime`. Rodado com o venv fora do repositório.
- Nenhuma chamada real ao Jev: sem chave neste ambiente.
