-- ============================================================================
-- guardar_logins_dev.sql - opção (a) do proprietário: antes de recriar public,
-- guarda DENTRO do DEV só o vínculo de login (Clerk id, nome, e-mail, status,
-- papéis e se é admin de plataforma) num schema temporário fora de public.
-- A semente (passo 7) devolve esses logins à igreja fictícia e apaga o schema.
--
-- Nada sai do banco nem é impresso além das contagens. As colunas usam só tipos
-- do pg_catalog (enum vira text), para nada fora de public depender de public:
-- assim a trava "dependentes" da recriação continua passando.
--
--   psql service=pastorai_dev -X -q -v estado=291:<md5> -v ledger=33 -f guardar_logins_dev.sql
-- ============================================================================
\set ON_ERROR_STOP on
\if :{?estado}
\else
  \echo 'faltou -v estado=<objetos>:<md5> (inventario_ro.sql §10)'
  \quit
\endif
\if :{?ledger}
\else
  \echo 'faltou -v ledger=<linhas do ledger antigo>'
  \quit
\endif
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = pg_catalog, pg_temp;
SELECT set_config('pastorai.estado_esperado', :'estado', true),
       set_config('pastorai.ledger_esperado', :'ledger', true);

DO $trava$
DECLARE n bigint; m text;
BEGIN
  IF current_user <> 'postgres' THEN RAISE EXCEPTION 'conexão inesperada: %', current_user; END IF;
  IF to_regclass('public.schema_migrations') IS NULL
     OR EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = 'public.schema_migrations'::regclass
                  AND attname = 'origem' AND attnum > 0 AND NOT attisdropped) THEN
    RAISE EXCEPTION 'ledger no formato do PROD ou ausente: este não é o DEV inspecionado';
  END IF;
  SELECT count(*) INTO n FROM public.schema_migrations;
  IF n::text <> current_setting('pastorai.ledger_esperado') THEN
    RAISE EXCEPTION 'ledger com % linhas: o DEV mudou', n;
  END IF;
  SELECT count(*), md5(string_agg(x, ',' ORDER BY x COLLATE "C")) INTO n, m
    FROM (SELECT 'r:' || c.relkind::text || ':' || c.relname FROM pg_class AS c
           WHERE c.relnamespace = 'public'::regnamespace
          UNION ALL
          SELECT 'f:' || p.oid::regprocedure::text FROM pg_proc AS p
           WHERE p.pronamespace = 'public'::regnamespace
          UNION ALL
          SELECT 't:' || t.typtype::text || ':' || t.typname FROM pg_type AS t
           WHERE t.typnamespace = 'public'::regnamespace AND t.typtype IN ('e', 'd', 'r', 'm')) AS s(x);
  IF n || ':' || m <> current_setting('pastorai.estado_esperado') THEN
    RAISE EXCEPTION 'o schema public do DEV mudou desde a inspeção (% objetos, %)', n, m;
  END IF;
  IF to_regnamespace('pastorai_semente_tmp') IS NOT NULL THEN
    RAISE EXCEPTION 'pastorai_semente_tmp já existe: os logins já foram guardados';
  END IF;
END
$trava$;

CREATE SCHEMA pastorai_semente_tmp;
COMMENT ON SCHEMA pastorai_semente_tmp IS
  'Temporário (espelho DEV = PROD, 27/09/2026): logins de teste guardados antes de recriar public. A semente do passo 7 os devolve e apaga este schema.';
CREATE TABLE pastorai_semente_tmp.logins AS
SELECT u.id AS app_user_id, u.clerk_user_id, u.nome, u.email, u.status::text AS status, u.chat_nome,
       coalesce((SELECT array_agg(r.papel::text ORDER BY r.papel::text)
                   FROM public.user_roles AS r WHERE r.user_id = u.id), '{}'::text[]) AS papeis,
       EXISTS (SELECT 1 FROM public.platform_admins AS pa WHERE pa.app_user_id = u.id) AS admin_plataforma
  FROM public.app_users AS u;

DO $confere$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_depend AS d
              JOIN pg_type AS t ON d.refclassid = 'pg_type'::regclass AND t.oid = d.refobjid
             WHERE d.classid = 'pg_class'::regclass
               AND d.objid = 'pastorai_semente_tmp.logins'::regclass
               AND t.typnamespace = 'public'::regnamespace) THEN
    RAISE EXCEPTION 'a cópia dos logins depende de um tipo de public: a recriação recusaria';
  END IF;
  IF (SELECT count(*) FROM pastorai_semente_tmp.logins) <> (SELECT count(*) FROM public.app_users) THEN
    RAISE EXCEPTION 'contagem de logins guardados diferente de app_users';
  END IF;
END
$confere$;

SELECT count(*) AS logins_guardados, count(*) FILTER (WHERE admin_plataforma) AS admins_plataforma,
       count(*) FILTER (WHERE clerk_user_id IS NOT NULL) AS com_clerk
  FROM pastorai_semente_tmp.logins;
COMMIT;
