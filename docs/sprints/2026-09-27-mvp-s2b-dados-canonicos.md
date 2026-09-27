# MVP S2b: dados públicos canônicos, 2026-09-27

**Branch:** `feat/church-cell-public-data` · **Base:** `e6aafc296014770ceabc24d5ea6bd9572f33ace4` · **Commits:** candidato na branch, head identificado pela PR · **Deploy:** não

## O que foi feito

- Plano S2b aprovado com os ajustes dos conselheiros: Igreja/Celula como fonte,
  bairro editável pelo líder, publicação pastor/admin, oferta antes do Jev e
  interface protegida por suporte da API. Implementação concluída; revisão independente no patch exato.
- Roteiro DEV entregue ao Raniel por nota Maestri e Conselheiro Claude, com
  diagnóstico antes de aplicação, URL privada e sequência dependente do estado.
- Ordem WhatsApp-first registrada no MVP-PLANO: S3 revisada, relatório de célula,
  agenda, consolidação, membro e trilha UX. Não reclassifica domínio como pronto.

## Decisões

- Endereço residencial e dados de liderança ficam fora da projeção pública.
  Sem backfill do bloco livre legado; copiar somente endereço/horários válidos
  do JSON estruturado para campos canônicos vazios, sem publicar células.
- Ofertas de secretaria usam o ledger de mensagens existente, confirmação de
  envio, prazo e consumo único; nenhuma transação nova atravessa HTTP.
- Migration aditiva com `lock_timeout` curto, referência 2s. DEV reconciliado
  condiciona somente sua aplicação/deploy PROD. Código, PR e CI seguem.

## Pendente / próximo passo

- Publicar PR e conferir CI no head; solicitar Sarah com o candidato exato.
- Merge exige ordem nominal com número e gates vivos. Avisar necessidade de
  deploy manual backend. Banco, implantação e envios mantêm gates próprios.
- S3 anterior preservada; seu plano será revisado para telefone com confirmação
  por ação comum, Clerk nas leituras sensíveis e nenhuma finança por telefone.

## Verificação

- Roteiro DEV: oito blocos Bash conferidos sintaticamente e seis DSNs
  sintéticos, inclusive Python otimizado. Revisão documental independente APTO
  no SHA256 `15dac264ecdfe45e7d1bf0714d754381e08de0c17329bd50b559c666e234856f`.
- Backend: 5.453 testes passaram; RLS PostgreSQL17: 352 passaram, sem skips.
  Frontend: 902 testes, typecheck/build e seis cenários E2E conferidos (5+1).
- SQL original final aplicado em `public` de banco descartável exclusivo, duas
  provas passaram. Migration SHA256 `6679087ae4b8b97eba7dca1a8b068c76fdc7a799b87cda95347e285c16d6ebe1`.
- Base, patch de código, hashes e limites: [evidência](../ops/s2b-church-cell-20260927/TEST-EVIDENCE.json).
- Zero acesso a DEV/PROD/VPS/provedores nesta missão; nenhum backup real lido.
