-- ============================================================================
-- PastorAI 1.0 — Migration 0013: autoria das mensagens humanas (Parte A do chat)
--
-- "Quem respondeu": quando um humano assume a conversa, a mensagem enviada passa
-- a registrar QUEM enviou. O nome exibido é a "assinatura" do usuário
-- (app_users.chat_nome), com fallback para o nome da conta.
--
--   app_users.chat_nome  nome de exibição no chat (assinatura). NULL = usa o nome.
--   messages.autor_nome  nome exibido na mensagem (snapshot no momento do envio).
--   messages.enviado_por app_user que enviou (auditoria). NULL p/ IA e contato.
--
-- Aditiva e idempotente.
-- ============================================================================

begin;

alter table app_users
  add column if not exists chat_nome text;
comment on column app_users.chat_nome is
  'Nome de exibição do usuário no chat do WhatsApp (assinatura). NULL = usa o nome da conta.';

alter table messages
  add column if not exists autor_nome  text,
  add column if not exists enviado_por uuid references app_users(id) on delete set null;
comment on column messages.autor_nome is
  'Nome exibido de quem enviou (humano: assinatura/nome). Snapshot no envio. NULL p/ IA, contato e mensagens antigas.';
comment on column messages.enviado_por is
  'app_user que enviou a mensagem (humano). NULL para IA e mensagens do contato.';

commit;
