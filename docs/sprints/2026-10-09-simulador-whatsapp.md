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
  modo e a chave real nunca vai para o simulador.
- Destino validado por sentido com `ipaddress` e lista exata de nomes
  (`is_simulated_destination`): backend → Evolution falsa aceita IP de loopback,
  `localhost` e `simulador-whatsapp`; simulador → webhook aceita IP de loopback,
  `localhost` e `backend`. Recusa `127.example.invalid`, `0x7f000001`,
  `2130706433`, `167772161`, IPv4 não loopback, credenciais embutidas, porta
  inválida e o nome do outro sentido.
- Estado do fake: excluir a instância a deixa fora até recriar (antes a ausência
  voltava a significar `open`); `sendMedia` e a entrada simulada respeitam a
  desconexão. Foto de perfil e mídia base64 ficam fora do contrato do fake.
- Gates próprios: o modo simulado exige `BREVO_SEND_MODE=off` e
  `ASAAS_BILLING_ENABLED=false`; o compose dev fixa os dois fechados.
- Compose dev: serviço `simulador-whatsapp` e transporte simulado por padrão
  (`DEV_WHATSAPP_TRANSPORTE=real` volta à Evolution local).

## Decisões
- O simulador não liga `ALLOW_REAL_SENDS`: LLM, agenda, Asaas e Brevo seguem
  bloqueados. Sem LLM valem as respostas fixas (termo LGPD, consultas públicas).
- Outros envios que checam o gate global antes do cliente (SLA, lembretes,
  mídia do inbox) continuam suprimidos no modo simulado. O dispatcher da
  `notification_outbox` revalida o gate global antes do transporte e pode
  cancelar pendências com `gate_fechado`; esta fatia NÃO faz lembretes/avisos
  chegarem ao simulador. Isso exige uma fatia própria sob isolamento, sem abrir
  o gate geral como atalho.
- O gate global `ALLOW_REAL_SENDS` não é endurecido pelo validador: o `dev.sh`
  ainda prevê o gate aberto com o simulador (só avisa). Decisão pendente.
- Telefones sintéticos com DDD 00, aceitos pelo scanner de privacidade sem
  registro de revisão.

## Verificação
- `tests/test_whatsapp_simulado.py` (65 após as correções da F2a): configuração,
  destinos adversariais nos dois sentidos, gates Brevo/Asaas, estado do fake,
  contrato `EvolutionClient` ↔ simulador, webhook pela autenticação real.
- `tests/test_whatsapp_simulado_turno_pg.py` (4, `rls_integration`): "oi" →
  termo LGPD no simulador e em `messages`; SAIR grava opt-out e o bot não
  responde mais; igreja fora do piloto e agente inativo não respondem. Alcance:
  handler e persistência, com fila em memória, dedupe Redis substituído, schema
  ORM sem policies e leitura direta da tabela. NÃO prova Redis, RLS, ação
  privilegiada nem API/painel do inbox (isso é a F2b).
- Relato do autor, não repetido na revisão: suíte backend local com 6.366 testes
  verdes. No CI do PR original, a execução aprovou os 4 testes PG novos dentro
  de 866 executados, sem skips.
- Não exercitado: a stack completa `./dev.sh up` com painel e Supabase local.

## Pendente / próximo passo
- Observado, sem mudança de comportamento: "SAIR" grava o opt-out sem mensagem
  de confirmação, embora `nodes.optout_node` tenha um texto de confirmação.
- F2b: prova integrada com Redis real, policies reais e uma ação vertical.
- Fatia 2 (DEV online): copiar `devtools/` para a imagem DEV ou rodar o
  simulador como serviço próprio.
