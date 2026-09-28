SELECT md5(concat_ws('|',
  (SELECT concat_ws(';', pg_get_userbyid(relowner), relrowsecurity::text, relforcerowsecurity::text, relacl::text) FROM pg_class WHERE oid = to_regclass('public.agent_configs')),
  (SELECT string_agg(concat_ws('=', attname, coalesce(attacl::text, '')), ';' ORDER BY attname) FROM pg_attribute WHERE attrelid = to_regclass('public.agent_configs') AND attnum > 0 AND NOT attisdropped AND attname <> 'informacoes_publicas'),
  (SELECT string_agg(concat_ws(':', polname, polcmd::text, polpermissive::text, polroles::text, pg_get_expr(polqual, polrelid), pg_get_expr(polwithcheck, polrelid)), ';' ORDER BY polname) FROM pg_policy WHERE polrelid = to_regclass('public.agent_configs')),
  (SELECT string_agg(concat_ws(':', conname, pg_get_constraintdef(oid)), ';' ORDER BY conname) FROM pg_constraint WHERE conrelid = to_regclass('public.agent_configs') AND conname <> 'agent_configs_informacoes_publicas_objeto'),
  (SELECT string_agg(concat_ws(':', tgname, tgenabled::text, pg_get_triggerdef(oid)), ';' ORDER BY tgname) FROM pg_trigger WHERE tgrelid = to_regclass('public.agent_configs') AND NOT tgisinternal)
)) AS fingerprint_md5
