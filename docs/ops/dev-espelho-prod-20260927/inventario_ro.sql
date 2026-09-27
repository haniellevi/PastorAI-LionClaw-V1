-- ============================================================================
-- inventario_ro.sql - inventário SÓ LEITURA para o espelho DEV = PROD (27/09/2026).
--
-- Serve para DEV e PROD. Uma transação READ ONLY com ROLLBACK no fim; lê só o
-- catálogo. Com -v contar_linhas=1 (só no DEV) conta linhas das tabelas de
-- public, de storage.objects por bucket e de auth.users: números, nunca conteúdo.
-- Não imprime host, URL, senha, linha de tabela nem texto de comentário.
--
--   PGSERVICEFILE=~/.config/pastorai/pg_service.conf \
--     psql service=pastorai_dev -X -v contar_linhas=1 -f inventario_ro.sql
-- ============================================================================
\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '120s';
SET LOCAL lock_timeout = '5s';
-- Caminho fixo: nomes de função/tipo saem sempre com schema (a trava depende disso).
SET LOCAL search_path = pg_catalog, pg_temp;

\echo == 1. IDENTIDADE ==
SELECT current_setting('server_version') AS pg, current_user, session_user,
       r.rolsuper, r.rolbypassrls, r.rolcreaterole, current_database() AS db
  FROM pg_roles AS r WHERE r.rolname = current_user;
SELECT b.rolname AS postgres_e_membro_de
  FROM pg_auth_members AS m JOIN pg_roles AS b ON b.oid = m.roleid
 WHERE m.member = to_regrole('postgres') ORDER BY 1;

\echo == 2. ROLES DO SUPABASE E DO APP ==
SELECT r.rolname, r.rolsuper, r.rolbypassrls, r.rolcanlogin, r.rolinherit
  FROM pg_roles AS r
 WHERE r.rolname IN ('postgres', 'anon', 'authenticated', 'service_role', 'authenticator',
                     'supabase_admin', 'supabase_auth_admin', 'supabase_storage_admin',
                     'dashboard_user', 'pgbouncer', 'agent_runtime')
 ORDER BY 1;

\echo == 3. SCHEMAS (fora do sistema) ==
SELECT n.nspname AS schema, pg_get_userbyid(n.nspowner) AS dono, n.nspacl::text AS acl
  FROM pg_namespace AS n
 WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
 ORDER BY 1;

\echo == 4. DEFAULT PRIVILEGES ==
SELECT pg_get_userbyid(d.defaclrole) AS role, coalesce(n.nspname, '<global>') AS schema,
       d.defaclobjtype AS tipo, d.defaclacl::text AS acl
  FROM pg_default_acl AS d LEFT JOIN pg_namespace AS n ON n.oid = d.defaclnamespace
 ORDER BY 2, 1, 3;

\echo == 5. EVENT TRIGGERS ==
SELECT e.evtname, e.evtevent, e.evtenabled, e.evtfoid::regprocedure AS funcao,
       pg_get_userbyid(e.evtowner) AS dono, e.evttags::text AS tags, md5(pg_get_functiondef(e.evtfoid)) AS funcao_md5
  FROM pg_event_trigger AS e ORDER BY 1;

\echo == 6. EXTENSÕES ==
SELECT x.extname, x.extversion, n.nspname AS schema
  FROM pg_extension AS x JOIN pg_namespace AS n ON n.oid = x.extnamespace ORDER BY 1;

\echo == 7. OBJETOS EM public POR TIPO, DONO E EXTENSÃO ==
SELECT o.tipo, o.dono, o.de_extensao, count(*) AS quantidade
  FROM (
    SELECT 'relacao:' || c.relkind::text AS tipo, pg_get_userbyid(c.relowner) AS dono,
           EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_class'::regclass
                     AND d.objid = c.oid AND d.deptype = 'e') AS de_extensao
      FROM pg_class AS c WHERE c.relnamespace = 'public'::regnamespace
    UNION ALL
    SELECT 'funcao:' || p.prokind::text, pg_get_userbyid(p.proowner),
           EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_proc'::regclass
                     AND d.objid = p.oid AND d.deptype = 'e')
      FROM pg_proc AS p WHERE p.pronamespace = 'public'::regnamespace
    UNION ALL
    SELECT 'tipo:' || t.typtype::text, pg_get_userbyid(t.typowner),
           EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_type'::regclass
                     AND d.objid = t.oid AND d.deptype = 'e')
      FROM pg_type AS t
     WHERE t.typnamespace = 'public'::regnamespace AND t.typtype IN ('e', 'd', 'r', 'm')
  ) AS o
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

\echo == 8. TABELAS DE public: dono, RLS, FORCE, policies, triggers ==
SELECT c.relname AS tabela, pg_get_userbyid(c.relowner) AS dono,
       c.relrowsecurity AS rls, c.relforcerowsecurity AS force_rls,
       (SELECT count(*) FROM pg_policy AS p WHERE p.polrelid = c.oid) AS policies,
       (SELECT count(*) FROM pg_trigger AS t WHERE t.tgrelid = c.oid AND NOT t.tgisinternal) AS triggers
  FROM pg_class AS c
 WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
 ORDER BY 1;

\echo == 9. FUNÇÕES DE public ==
SELECT p.oid::regprocedure AS funcao, pg_get_userbyid(p.proowner) AS dono, p.prosecdef AS secdef,
       p.proconfig::text AS config, md5(pg_get_functiondef(p.oid)) AS def_md5
  FROM pg_proc AS p
 WHERE p.pronamespace = 'public'::regnamespace AND p.prokind IN ('f', 'p')
 ORDER BY 1::text COLLATE "C";

\echo == 10. IMPRESSÃO DO ESTADO DE public (trava do passo de recriação) ==
-- Nomes de relações, funções e tipos (sem OID): muda se qualquer objeto entrar ou sair.
-- estado:inicio  (montar_recriacao.py usa este trecho igual, na trava)
SELECT count(*) AS objetos, md5(string_agg(x, ',' ORDER BY x COLLATE "C")) AS estado_public_md5
  FROM (
    SELECT 'r:' || c.relkind::text || ':' || c.relname FROM pg_class AS c
     WHERE c.relnamespace = 'public'::regnamespace
    UNION ALL
    SELECT 'f:' || p.oid::regprocedure::text FROM pg_proc AS p
     WHERE p.pronamespace = 'public'::regnamespace
    UNION ALL
    SELECT 't:' || t.typtype::text || ':' || t.typname FROM pg_type AS t
     WHERE t.typnamespace = 'public'::regnamespace AND t.typtype IN ('e', 'd', 'r', 'm')
  ) AS s(x)
-- estado:fim
;

\echo == 10b. OBJETOS DE FORA DE public QUE DEPENDEM DE public (o DROP ... CASCADE os levaria) ==
-- Catálogo desconhecido conta como "de fora" (lado seguro): ex. event trigger, publicação.
-- dependentes:inicio  (montar_recriacao.py usa este trecho igual, na trava)
WITH dep AS (
  SELECT d.classid, d.objid, d.objsubid, d.refclassid, d.refobjid, d.refobjsubid,
         CASE d.refclassid
           WHEN 'pg_class'::regclass THEN (SELECT c.relnamespace FROM pg_class AS c WHERE c.oid = d.refobjid)
           WHEN 'pg_proc'::regclass THEN (SELECT p.pronamespace FROM pg_proc AS p WHERE p.oid = d.refobjid)
           WHEN 'pg_type'::regclass THEN (SELECT t.typnamespace FROM pg_type AS t WHERE t.oid = d.refobjid)
         END AS ref_nsp,
         CASE d.classid
           WHEN 'pg_class'::regclass THEN (SELECT c.relnamespace FROM pg_class AS c WHERE c.oid = d.objid)
           WHEN 'pg_proc'::regclass THEN (SELECT p.pronamespace FROM pg_proc AS p WHERE p.oid = d.objid)
           WHEN 'pg_type'::regclass THEN (SELECT t.typnamespace FROM pg_type AS t WHERE t.oid = d.objid)
           WHEN 'pg_constraint'::regclass THEN (SELECT k.connamespace FROM pg_constraint AS k WHERE k.oid = d.objid)
           WHEN 'pg_attrdef'::regclass THEN (SELECT c.relnamespace FROM pg_attrdef AS a
                                               JOIN pg_class AS c ON c.oid = a.adrelid WHERE a.oid = d.objid)
           WHEN 'pg_policy'::regclass THEN (SELECT c.relnamespace FROM pg_policy AS p
                                              JOIN pg_class AS c ON c.oid = p.polrelid WHERE p.oid = d.objid)
           WHEN 'pg_trigger'::regclass THEN (SELECT c.relnamespace FROM pg_trigger AS t
                                               JOIN pg_class AS c ON c.oid = t.tgrelid WHERE t.oid = d.objid)
           WHEN 'pg_rewrite'::regclass THEN (SELECT c.relnamespace FROM pg_rewrite AS r
                                               JOIN pg_class AS c ON c.oid = r.ev_class WHERE r.oid = d.objid)
         END AS dep_nsp
    FROM pg_depend AS d
   WHERE d.deptype IN ('n', 'a')
)
SELECT pg_describe_object(classid, objid, objsubid) AS objeto_de_fora,
       pg_describe_object(refclassid, refobjid, refobjsubid) AS depende_de
  FROM dep
 WHERE ref_nsp = 'public'::regnamespace AND dep_nsp IS DISTINCT FROM 'public'::regnamespace
 ORDER BY 1, 2
-- dependentes:fim
;

\if :{?contar_linhas}
\echo == 11. LINHAS POR TABELA DE public (só números) ==
SELECT c.relname AS tabela,
       (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', c.relname),
                                            false, true, '')))[1]::text::bigint AS linhas
  FROM pg_class AS c
 WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
 ORDER BY 1;

-- CASE (e não AND) porque o SQL não garante ordem de avaliação: sem a tabela,
-- has_table_privilege daria erro.
SELECT CASE WHEN to_regclass('storage.objects') IS NULL OR to_regclass('storage.buckets') IS NULL
            THEN false
            ELSE has_table_privilege(to_regclass('storage.objects'), 'SELECT')
                 AND has_table_privilege(to_regclass('storage.buckets'), 'SELECT') END AS ok_storage,
       CASE WHEN to_regclass('auth.users') IS NULL THEN false
            ELSE has_table_privilege(to_regclass('auth.users'), 'SELECT') END AS ok_auth
\gset inv_
\echo == 12. STORAGE: objetos por bucket (só números) ==
\if :inv_ok_storage
SELECT b.id AS bucket, b.public AS publico,
       (SELECT count(*) FROM storage.objects AS o WHERE o.bucket_id = b.id) AS objetos
  FROM storage.buckets AS b ORDER BY 1;
\else
\echo storage.objects ausente ou sem permissão de leitura
\endif
\echo == 13. AUTH: usuários do Supabase Auth (só número; o app usa Clerk) ==
\if :inv_ok_auth
SELECT count(*) AS auth_users FROM auth.users;
\else
\echo auth.users ausente ou sem permissão de leitura
\endif
\endif

ROLLBACK;
