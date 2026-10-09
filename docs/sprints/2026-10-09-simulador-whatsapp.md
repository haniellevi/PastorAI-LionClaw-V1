# Simulador de WhatsApp (Fatia 1) — 2026-10-09

**Branch:** `feat/simulador-whatsapp`  ·  **Commits:** neste PR  ·  **Deploy:** não

## O que foi feito
- `backend/devtools/simulador_whatsapp.py`: Evolution falsa com só os endpoints
  que o `EvolutionClient` usa, mensagens em memória, falhas programáveis de
  `sendText` e uma página de chat. A mensagem do "contato" vira um webhook
  `messages.upsert` entregue ao backend com o segredo real.
- `WHATSAPP_TRANSPORTE=simulado` + `EVOLUTION_SIMULADOR_URL` (`app/config.py`):
  no modo simulado o `EvolutionClient` fala só com o simulador, mesmo com
  `ALLOW_REAL_SENDS=false` (`app/services/evolution.py`). Produção recusa o
  modo; a URL precisa ser loopback ou serviço interno; a chave real nunca vai
  para o simulador.
- Compose dev: serviço `simulador-whatsapp` e transporte simulado por padrão
  (`DEV_WHATSAPP_TRANSPORTE=real` volta à Evolution local).

## Decisões
- O simulador não liga `ALLOW_REAL_SENDS`: LLM, agenda, Asaas e Brevo seguem
  bloqueados. Sem LLM valem as respostas fixas (termo LGPD, consultas públicas).
- Outros envios que checam o gate global antes do cliente (SLA, lembretes,
  mídia do inbox) continuam suprimidos no modo simulado; ficam para quando o
  DEV online precisar deles.
- Telefones sintéticos com DDD 00, aceitos pelo scanner de privacidade sem
  registro de revisão.

## Verificação
- `tests/test_whatsapp_simulado.py` (22): configuração, isolamento do gate,
  contrato `EvolutionClient` ↔ simulador, webhook pela autenticação real.
- `tests/test_whatsapp_simulado_turno_pg.py` (4, `rls_integration`): "oi" →
  termo LGPD no simulador e no inbox; SAIR grava opt-out e o bot não responde
  mais; igreja fora do piloto e agente inativo não respondem. Rodado em
  PostgreSQL 17.11 descartável, sem rede.
- Suíte backend local (`./test-local.sh backend`): 6.366 testes verdes.
- Não exercitado: a stack completa `./dev.sh up` com painel e Supabase local.

## Pendente / próximo passo
- Observado, sem mudança de comportamento: "SAIR" grava o opt-out sem mensagem
  de confirmação, embora `nodes.optout_node` tenha um texto de confirmação.
- Fatia 2 (DEV online): copiar `devtools/` para a imagem DEV ou rodar o
  simulador como serviço próprio.
