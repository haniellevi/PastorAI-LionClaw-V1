-- ============================================================================
-- fingerprint_ro.sql - impressão digital SÓ LEITURA do schema public (DEV = PROD).
--
-- Uma linha por objeto: secao, objeto, md5 de tudo o que define o objeto
-- (tipo, dono, RLS/FORCE, colunas, defaults, restrições, índices, policies com
-- roles e expressões, gatilhos, funções com corpo e config, tipos, sequências,
-- ACL normalizada e md5 do comentário). No fim, um *TOTAL* por seção e o
-- total de public. Rodar nos dois bancos e comparar com diff: cada linha
-- diferente é um objeto diferente.
--
-- ACL: aclexplode(coalesce(acl, acldefault(...))) em ordem; NULL e o default
-- explícito dão o mesmo resultado. Colunas: posição entre as não removidas
-- (o dump renumera attnum). "plataforma" (event triggers, extensões,
-- publicações) é do Supabase e fica fora do total de public.
--
-- Lê só o catálogo, mais nomes/origens de public.schema_migrations (seção
-- ledger, só a contagem e o md5). Nunca lê linha de tabela da aplicação nem imprime texto de comentário.
--
--   psql service=... -X --csv -f fingerprint_ro.sql > fingerprint.csv
-- ============================================================================
\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL statement_timeout = '120s';

WITH fp AS (
-- itens:inicio  (montar_recriacao.py usa este trecho igual, dentro da transação)
WITH
rel AS (
  SELECT c.oid, c.relname, c.relkind, c.relowner, c.relacl FROM pg_class AS c
   WHERE c.relnamespace = 'public'::regnamespace
     AND NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_class'::regclass
                       AND d.objid = c.oid AND d.deptype = 'e')
),
itens AS (
  -- tabelas, visões, sequências e tipos compostos (índices ficam em "indice")
  SELECT 'tabela' AS secao, c.relname::text AS objeto,
         md5(concat_ws('|', c.relkind, pg_get_userbyid(c.relowner), k.relrowsecurity, k.relforcerowsecurity,
                       k.relpersistence, k.relreplident, k.reloptions::text,
                       CASE WHEN c.relkind IN ('v', 'm') THEN md5(pg_get_viewdef(c.oid)) END,
                       acl.v, md5(coalesce(obj_description(c.oid, 'pg_class'), '')))) AS sig
    FROM rel AS c JOIN pg_class AS k ON k.oid = c.oid
    LEFT JOIN LATERAL (
      SELECT string_agg(x, ',' ORDER BY x COLLATE "C") AS v
        FROM (SELECT format('%s>%s:%s%s', CASE WHEN e.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(e.grantee) END,
                            pg_get_userbyid(e.grantor), e.privilege_type, CASE WHEN e.is_grantable THEN '*' END) AS x
                FROM aclexplode(nullif(coalesce(c.relacl, acldefault(CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END::"char",
                                                               c.relowner)), '{}'::aclitem[])) AS e) AS s) AS acl ON true
   WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f', 'c')
  UNION ALL
  SELECT 'coluna', c.relname || '.' || a.attname,
         md5(concat_ws('|', row_number() OVER (PARTITION BY c.oid ORDER BY a.attnum),
                       format_type(a.atttypid, a.atttypmod), a.attnotnull, pg_get_expr(ad.adbin, ad.adrelid),
                       a.attidentity, a.attgenerated,
                       CASE WHEN a.attcollation <> 0 THEN a.attcollation::regcollation::text END,
                       acl.v, md5(coalesce(col_description(c.oid, a.attnum), ''))))
    FROM rel AS c
    JOIN pg_attribute AS a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
    LEFT JOIN pg_attrdef AS ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
    LEFT JOIN LATERAL (
      SELECT string_agg(x, ',' ORDER BY x COLLATE "C") AS v
        FROM (SELECT format('%s>%s:%s%s', CASE WHEN e.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(e.grantee) END,
                            pg_get_userbyid(e.grantor), e.privilege_type, CASE WHEN e.is_grantable THEN '*' END) AS x
                FROM aclexplode(nullif(a.attacl, '{}'::aclitem[])) AS e) AS s) AS acl ON true
   WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'c')
  UNION ALL
  SELECT 'restricao', c.relname || '.' || con.conname,
         md5(concat_ws('|', con.contype, pg_get_constraintdef(con.oid), con.convalidated, con.condeferrable,
                       con.condeferred, con.connoinherit,
                       md5(coalesce(obj_description(con.oid, 'pg_constraint'), ''))))
    FROM rel AS c JOIN pg_constraint AS con ON con.conrelid = c.oid
  UNION ALL
  SELECT 'indice', ic.relname::text,
         md5(concat_ws('|', pg_get_indexdef(i.indexrelid), i.indisvalid, i.indisready,
                       md5(coalesce(obj_description(ic.oid, 'pg_class'), ''))))
    FROM rel AS c JOIN pg_index AS i ON i.indrelid = c.oid JOIN pg_class AS ic ON ic.oid = i.indexrelid
  UNION ALL
  SELECT 'policy', c.relname || '.' || p.polname,
         md5(concat_ws('|', p.polcmd, p.polpermissive,
                       (SELECT string_agg(x, ',' ORDER BY x COLLATE "C")
                          FROM (SELECT CASE WHEN r = 0 THEN 'public' ELSE pg_get_userbyid(r) END AS x
                                  FROM unnest(p.polroles) AS r) AS s),
                       pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid),
                       md5(coalesce(obj_description(p.oid, 'pg_policy'), ''))))
    FROM rel AS c JOIN pg_policy AS p ON p.polrelid = c.oid
  UNION ALL
  SELECT 'gatilho', c.relname || '.' || t.tgname,
         md5(concat_ws('|', pg_get_triggerdef(t.oid), t.tgenabled,
                       md5(coalesce(obj_description(t.oid, 'pg_trigger'), ''))))
    FROM rel AS c JOIN pg_trigger AS t ON t.tgrelid = c.oid AND NOT t.tgisinternal
  UNION ALL
  SELECT 'funcao', p.oid::regprocedure::text,
         md5(concat_ws('|', p.prokind, pg_get_userbyid(p.proowner), p.prosecdef, p.proleakproof, p.provolatile,
                       p.proparallel, p.proconfig::text,
                       CASE WHEN p.prokind IN ('f', 'p') THEN md5(pg_get_functiondef(p.oid)) ELSE 'agregado' END,
                       acl.v, md5(coalesce(obj_description(p.oid, 'pg_proc'), ''))))
    FROM pg_proc AS p
    LEFT JOIN LATERAL (
      SELECT string_agg(x, ',' ORDER BY x COLLATE "C") AS v
        FROM (SELECT format('%s>%s:%s%s', CASE WHEN e.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(e.grantee) END,
                            pg_get_userbyid(e.grantor), e.privilege_type, CASE WHEN e.is_grantable THEN '*' END) AS x
                FROM aclexplode(nullif(coalesce(p.proacl, acldefault('f', p.proowner)), '{}'::aclitem[])) AS e) AS s) AS acl ON true
   WHERE p.pronamespace = 'public'::regnamespace
     AND NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_proc'::regclass
                       AND d.objid = p.oid AND d.deptype = 'e')
  UNION ALL
  SELECT 'tipo', t.typname::text,
         md5(concat_ws('|', t.typtype, pg_get_userbyid(t.typowner),
                       (SELECT string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder) FROM pg_enum AS e
                         WHERE e.enumtypid = t.oid),
                       CASE WHEN t.typtype = 'd' THEN concat_ws(';', format_type(t.typbasetype, t.typtypmod),
                            t.typnotnull, t.typdefault,
                            (SELECT string_agg(pg_get_constraintdef(dc.oid), ';' ORDER BY dc.conname)
                               FROM pg_constraint AS dc WHERE dc.contypid = t.oid)) END,
                       acl.v, md5(coalesce(obj_description(t.oid, 'pg_type'), ''))))
    FROM pg_type AS t
    LEFT JOIN LATERAL (
      SELECT string_agg(x, ',' ORDER BY x COLLATE "C") AS v
        FROM (SELECT format('%s>%s:%s%s', CASE WHEN e.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(e.grantee) END,
                            pg_get_userbyid(e.grantor), e.privilege_type, CASE WHEN e.is_grantable THEN '*' END) AS x
                FROM aclexplode(nullif(coalesce(t.typacl, acldefault('T', t.typowner)), '{}'::aclitem[])) AS e) AS s) AS acl ON true
   WHERE t.typnamespace = 'public'::regnamespace AND t.typtype IN ('e', 'd', 'r', 'm')
     AND NOT EXISTS (SELECT 1 FROM pg_depend AS d WHERE d.classid = 'pg_type'::regclass
                       AND d.objid = t.oid AND d.deptype = 'e')
  UNION ALL
  SELECT 'sequencia', c.relname::text,
         md5(concat_ws('|', format_type(s.seqtypid, NULL), s.seqstart, s.seqincrement, s.seqmax, s.seqmin,
                       s.seqcache, s.seqcycle,
                       (SELECT d.refobjid::regclass::text || '.' || d.refobjsubid FROM pg_depend AS d
                         WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ('a', 'i')
                           AND d.refclassid = 'pg_class'::regclass LIMIT 1)))
    FROM rel AS c JOIN pg_sequence AS s ON s.seqrelid = c.oid
  UNION ALL
  SELECT 'schema', n.nspname::text,
         md5(concat_ws('|', pg_get_userbyid(n.nspowner), acl.v, md5(coalesce(obj_description(n.oid, 'pg_namespace'), ''))))
    FROM pg_namespace AS n
    LEFT JOIN LATERAL (
      SELECT string_agg(x, ',' ORDER BY x COLLATE "C") AS v
        FROM (SELECT format('%s>%s:%s%s', CASE WHEN e.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(e.grantee) END,
                            pg_get_userbyid(e.grantor), e.privilege_type, CASE WHEN e.is_grantable THEN '*' END) AS x
                FROM aclexplode(nullif(coalesce(n.nspacl, acldefault('n', n.nspowner)), '{}'::aclitem[])) AS e) AS s) AS acl ON true
   WHERE n.nspname = 'public'
  UNION ALL
  SELECT 'default_acl', pg_get_userbyid(d.defaclrole) || ':' || d.defaclobjtype::text,
         md5((SELECT string_agg(x, ',' ORDER BY x COLLATE "C")
                FROM (SELECT format('%s>%s:%s%s', CASE WHEN e.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(e.grantee) END,
                                    pg_get_userbyid(e.grantor), e.privilege_type, CASE WHEN e.is_grantable THEN '*' END) AS x
                        FROM aclexplode(nullif(d.defaclacl, '{}'::aclitem[])) AS e) AS s))
    FROM pg_default_acl AS d WHERE d.defaclnamespace = 'public'::regnamespace
  UNION ALL
  SELECT 'ledger', 'public.schema_migrations',
         md5(CASE WHEN to_regclass('public.schema_migrations') IS NULL THEN 'ausente'
                  ELSE (xpath('/row/v/text()', query_to_xml(
                          'SELECT count(*) || '':'' || coalesce(md5(string_agg(sm.name || '':'' || '
                          || 'coalesce(to_jsonb(sm) ->> ''origem'', ''<sem origem>''), '','' '
                          || 'ORDER BY sm.name COLLATE "C")), '''') AS v FROM public.schema_migrations AS sm',
                          false, true, '')))[1]::text END)
  UNION ALL
  SELECT 'plataforma', 'event_trigger:' || e.evtname,
         md5(concat_ws('|', e.evtevent, e.evtenabled, e.evttags::text, e.evtfoid::regprocedure::text,
                       pg_get_userbyid(e.evtowner), md5(pg_get_functiondef(e.evtfoid))))
    FROM pg_event_trigger AS e
  UNION ALL
  SELECT 'plataforma', 'extensao:' || x.extname, md5(concat_ws('|', x.extversion, x.extnamespace::regnamespace::text))
    FROM pg_extension AS x
  UNION ALL
  SELECT 'plataforma', 'publicacao:' || p.pubname || ':' || c.relname, md5(concat_ws('|', p.pubinsert, p.pubupdate, p.pubdelete))
    FROM pg_publication AS p JOIN pg_publication_rel AS pr ON pr.prpubid = p.oid JOIN rel AS c ON c.oid = pr.prrelid
)
SELECT secao, objeto, sig AS md5 FROM itens
-- itens:fim
),
totais AS (
  SELECT secao, '*TOTAL* (' || count(*) || ')' AS objeto,
         md5(string_agg(objeto || '=' || md5, ',' ORDER BY objeto COLLATE "C")) AS md5
    FROM fp GROUP BY secao
  UNION ALL
  SELECT '~public', '*TOTAL* (' || count(*) || ')',
         md5(string_agg(secao || ':' || objeto || '=' || md5, ',' ORDER BY secao COLLATE "C", objeto COLLATE "C"))
    FROM fp WHERE secao <> 'plataforma'
)
SELECT r.secao, r.objeto, r.md5
  FROM (SELECT secao, objeto, md5 FROM fp
        UNION ALL
        SELECT secao, objeto, md5 FROM totais) AS r
 ORDER BY r.secao COLLATE "C", r.objeto COLLATE "C";

ROLLBACK;
