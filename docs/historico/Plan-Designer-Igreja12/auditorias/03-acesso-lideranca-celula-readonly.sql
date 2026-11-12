-- Fatia 03, auditoria SOMENTE LEITURA.
-- Não contém UPDATE, INSERT, DELETE, DDL ou chamada de função mutante.
-- Execute somente após escolher conscientemente o ambiente e registrar o gate.

-- 1. Resumo executivo de divergências de liderança e acesso.
WITH usable_access AS (
  SELECT au.igreja_id, au.pessoa_id, count(*) AS total
  FROM app_users au
  WHERE au.pessoa_id IS NOT NULL
    AND au.clerk_user_id IS NOT NULL
    AND (au.status IS NULL OR au.status = 'ativo')
  GROUP BY au.igreja_id, au.pessoa_id
), active_leadership AS (
  SELECT c.igreja_id, c.lider_id, count(*) AS total
  FROM celulas c
  WHERE c.ativo IS TRUE
    AND c.lider_id IS NOT NULL
  GROUP BY c.igreja_id, c.lider_id
), derived_role AS (
  SELECT ur.igreja_id, au.pessoa_id, count(*) AS total
  FROM user_roles ur
  JOIN app_users au ON au.id = ur.user_id AND au.igreja_id = ur.igreja_id
  WHERE ur.papel = 'lider_celula'
    AND au.pessoa_id IS NOT NULL
  GROUP BY ur.igreja_id, au.pessoa_id
)
SELECT 'celula_ativa_sem_lider' AS achado, count(*) AS total
FROM celulas c
WHERE c.ativo IS TRUE AND c.lider_id IS NULL
UNION ALL
SELECT 'lider_sem_exatamente_um_acesso_utilizavel', count(*)
FROM active_leadership al
LEFT JOIN usable_access ua
  ON ua.igreja_id = al.igreja_id AND ua.pessoa_id = al.lider_id
WHERE coalesce(ua.total, 0) <> 1
UNION ALL
SELECT 'pessoa_liderando_mais_de_uma_celula_ativa', count(*)
FROM active_leadership al
WHERE al.total > 1
UNION ALL
SELECT 'lider_ativo_sem_papel_derivado', count(*)
FROM active_leadership al
LEFT JOIN derived_role dr
  ON dr.igreja_id = al.igreja_id AND dr.pessoa_id = al.lider_id
WHERE coalesce(dr.total, 0) = 0
UNION ALL
SELECT 'papel_derivado_sem_lideranca_ativa', count(*)
FROM derived_role dr
LEFT JOIN active_leadership al
  ON al.igreja_id = dr.igreja_id AND al.lider_id = dr.pessoa_id
WHERE al.lider_id IS NULL
ORDER BY achado;

-- 2. Células ativas cujo líder não possui exatamente um acesso utilizável.
WITH usable_access AS (
  SELECT au.igreja_id, au.pessoa_id, count(*) AS total
  FROM app_users au
  WHERE au.pessoa_id IS NOT NULL
    AND au.clerk_user_id IS NOT NULL
    AND (au.status IS NULL OR au.status = 'ativo')
  GROUP BY au.igreja_id, au.pessoa_id
)
SELECT c.igreja_id, c.id AS celula_id, c.nome AS celula_nome, c.lider_id,
       coalesce(ua.total, 0) AS acessos_utilizaveis
FROM celulas c
LEFT JOIN usable_access ua
  ON ua.igreja_id = c.igreja_id AND ua.pessoa_id = c.lider_id
WHERE c.ativo IS TRUE
  AND c.lider_id IS NOT NULL
  AND coalesce(ua.total, 0) <> 1
ORDER BY c.igreja_id, c.nome, c.id;

-- 3. AppUsers duplicados para a mesma Pessoa, independentemente de status.
SELECT au.igreja_id, au.pessoa_id, count(*) AS app_users,
       array_agg(au.id ORDER BY au.id) AS app_user_ids
FROM app_users au
WHERE au.pessoa_id IS NOT NULL
GROUP BY au.igreja_id, au.pessoa_id
HAVING count(*) > 1
ORDER BY au.igreja_id, au.pessoa_id;

-- 4. Convites legados que ainda carregam célula pendente.
SELECT au.igreja_id, au.id AS app_user_id, au.status, au.celula_pendente_id
FROM app_users au
WHERE au.celula_pendente_id IS NOT NULL
ORDER BY au.igreja_id, au.created_at, au.id;

-- 5. Acessos utilizáveis sem qualquer papel efetivo.
SELECT au.igreja_id, au.id AS app_user_id, au.pessoa_id
FROM app_users au
LEFT JOIN user_roles ur
  ON ur.igreja_id = au.igreja_id AND ur.user_id = au.id
WHERE au.clerk_user_id IS NOT NULL
  AND (au.status IS NULL OR au.status = 'ativo')
GROUP BY au.igreja_id, au.id, au.pessoa_id
HAVING count(ur.user_id) = 0
ORDER BY au.igreja_id, au.id;

-- 6. Espelho Pessoa.celula_id diferente do vínculo canônico ativo.
WITH active_membership AS (
  SELECT cm.igreja_id, cm.pessoa_id,
         count(*) AS total,
         (array_agg(cm.celula_id ORDER BY cm.celula_id))[1] AS celula_id
  FROM celula_membro cm
  WHERE cm.ativo IS TRUE
  GROUP BY cm.igreja_id, cm.pessoa_id
)
SELECT p.igreja_id, p.id AS pessoa_id, p.celula_id AS espelho_celula_id,
       am.celula_id AS vinculo_ativo_celula_id, coalesce(am.total, 0) AS vinculos_ativos
FROM pessoas p
LEFT JOIN active_membership am
  ON am.igreja_id = p.igreja_id AND am.pessoa_id = p.id
WHERE p.celula_id IS DISTINCT FROM am.celula_id
   OR coalesce(am.total, 0) > 1
ORDER BY p.igreja_id, p.id;

-- 7. Dono da igreja que não é admin utilizável.
SELECT i.id AS igreja_id, i.dono_id
FROM igrejas i
LEFT JOIN app_users au
  ON au.id = i.dono_id AND au.igreja_id = i.id
LEFT JOIN user_roles ur
  ON ur.user_id = au.id AND ur.igreja_id = i.id AND ur.papel = 'admin'
WHERE i.dono_id IS NOT NULL
  AND (
    au.id IS NULL
    OR au.clerk_user_id IS NULL
    OR NOT (au.status IS NULL OR au.status = 'ativo')
    OR ur.user_id IS NULL
  )
ORDER BY i.id;

-- 8. E-mails repetidos no cadastro de acesso. Não expõe o e-mail em claro.
SELECT encode(digest(lower(trim(au.email)), 'sha256'), 'hex') AS email_hash,
       count(*) AS acessos,
       count(DISTINCT au.igreja_id) AS igrejas
FROM app_users au
GROUP BY lower(trim(au.email))
HAVING count(*) > 1
ORDER BY acessos DESC, email_hash;
