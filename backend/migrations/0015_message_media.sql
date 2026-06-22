-- ============================================================================
-- PastorAI 1.0 — Migration 0012: mídia nas mensagens (Etapa 2 do chat)
-- Imagens e arquivos no inbox (envio e recebimento via WhatsApp/Evolution).
--
-- O binário NÃO fica no Postgres (protege a cota do banco + LGPD): vai para o
-- Supabase Storage (bucket privado `whatsapp-media`). Aqui guardamos só o
-- ponteiro (`media_path`) e os metadados. A leitura no painel é por URL
-- assinada de curta duração gerada pelo backend (service-role key).
--
-- PRD (delta): estende `mensagem.tipo` de (texto|audio) para
-- (texto|imagem|arquivo|audio). Áudio já estava previsto no PRD (US-24).
--
-- Aditiva e idempotente. Linhas existentes ficam com tipo='texto'.
-- ============================================================================

begin;

-- messages.tipo (texto|imagem|arquivo|audio)
do $$ begin
  create type message_tipo as enum ('texto', 'imagem', 'arquivo', 'audio');
exception when duplicate_object then null; end $$;

alter table messages
  add column if not exists tipo          message_tipo not null default 'texto',
  add column if not exists media_path    text,
  add column if not exists media_mime    text,
  add column if not exists media_nome    text,
  add column if not exists media_tamanho int;

comment on column messages.tipo is
  'Tipo do conteúdo: texto|imagem|arquivo|audio. Mídia fica no Supabase Storage (bucket whatsapp-media); media_path aponta para o objeto.';
comment on column messages.media_path is
  'Caminho do objeto no bucket whatsapp-media: {igreja_id}/{conversation_id}/{uuid}.{ext}. NULL quando tipo=texto.';
comment on column messages.media_mime is
  'MIME type da mídia (ex.: image/jpeg, application/pdf). NULL quando tipo=texto.';
comment on column messages.media_nome is
  'Nome original do arquivo (documentos). NULL para imagens/áudio sem nome.';
comment on column messages.media_tamanho is
  'Tamanho da mídia em bytes. NULL quando tipo=texto.';

commit;
