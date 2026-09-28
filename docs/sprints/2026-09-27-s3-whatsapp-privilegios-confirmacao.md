# S3: privilégios e confirmação por ação, 2026-09-27

**Branch:** feat/whatsapp-privilege-actions · **Base:** 2e08d11 · **Deploy:** não.
Candidato source-only; manifesto e evidência em docs/ops/s3-whatsapp-20260927/.

## O que foi feito

- Plano aprovado com roteamento BYO sem Jev, proposta genérica e flag vazia.
- Catálogo servidor com duas ações mutantes, serviços humanos compartilhados;
  enum tipado e handles opacos não concedem identidade ou autorização.
- Confirmação no Perfil para consultas sensíveis, protegida contra API ausente.

## Decisões

- `marcar_presenca` confirma presença prevista em reunião usando CelulaPresenca;
  o contador legado permanece desabilitado e não representa comparecimento real.
- Proposta exige resumo efetivamente entregue, TTL de dez minutos e uso único.
  Efeito e comprovante durável compartilham commit; só depois há transporte.
- Leituras sensíveis exigem prova do painel; ações comuns usam telefone único,
  vínculo ativo e confirmação explícita. Finanças ficam excluídas.
- SQL próprio e testes PG17 descartáveis; migration da PR426 não foi alterada.

## Pendente / próximo passo

- Conferir CI do head exato; revisão Sarah permanece necessária.
- Parecer independente final APTO, 46/46 hashes; não substitui Sarah nem gate operacional.
- Sarah e ordem nominal de merge; rebase após merge426. Migration/deploy e
  ativação interna da flag dependem de coordenação e ordem próprias do Raniel.

## Verificação

Local: backend5660, RLS PG17 384 sem skip, frontend937, lint/build e E2E1.
Delta final LGPD: 25 PG focais verdes, incluindo dois novos aceites não estritos.
O SQL S3 byte-exato foi aplicado no public de banco descartável separado:
SHA256 d087013e0da83c7d80a1e3df05307861314eaaf2195bcd83149fe8927c2a50cc.
Manifesto fonte/testes/CI: 927a583ccbf1405343d15015dc11c42a999ec633cd01ac08996d77d2fb9906ae.
Duas ações, confirmações concorrentes, rollback, TTL, homônimos, mudança de termo,
revogação de alvo/papel, retry e supressão de respostas privadas foram exercitados.
Isso não comprova qualidade do LLM real, p95 real ou estado de ambiente compartilhado.

## Delta Sarah e robô

- SQL reaplicável, duas execuções byte-exatas preservando proposta existente;
  novo SHA186a99ab8d9c4cd8e0ce9583c542c9c45c60555da87e6d824224f3d2cf8a1795.
- Constante de release None impede ativação somente pela env, sem DB/HTTP S3.
- Somente nomes mencionados no inbound persistido entram nos candidatos D;
  roster não solicitado e texto solto do worker não ampliam a seleção.
- Perfil orienta repetir a consulta sensível, sem comando WhatsApp inexistente.
- Delta local:43backend/PG,22frontend,build e E2E1. Manifesto atualizado no diretório
  de evidências; os números e hashes acima registram a rodada anterior.

Rodada integral final do delta: backend5661 e RLS390 sem skips; manifesto
6834153ed0fb80b183eef2b6baef3d33bff86448fe4a7b3defdcd1a89e327db6.
Revisão independente do delta APTO; CI será reconferido no novo head.
