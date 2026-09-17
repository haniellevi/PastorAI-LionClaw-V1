# Inventário individual de basenames não deriváveis

Cada linha abaixo falha a forma exata `AAAAMMDD_HHMMSS_slug.sql`: o prefixo
sequencial de quatro dígitos não fornece uma chave candidata de 14 dígitos.
Esses itens permanecem `CATALOG_ENTRY_WITHOUT_PROD_KEY`; isso não prova que não
foram aplicados.

| Basename | Motivo |
| --- | --- |
| `0001_extensions_and_enums.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0002_schema_tables.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0003_rls_policies.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0004_triggers.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0005_seed.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0006_harden_function_search_path.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0007_remove_demo_data.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0008_add_operador_role.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0009_unify_system_managers.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0010_platform_admins.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0011_app_users_celula_pendente.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0012_planos.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0013_platform_audit_log.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0014_platform_orchestrator.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0015_message_media.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0016_message_author.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |
| `0017_app_user_status_revogado.sql` | `LEGACY_SEQUENTIAL_4_DIGIT_PREFIX` |

Há exatamente `17` linhas individuais. Elas pertencem ao catálogo top-level de
`77`, não são associadas por posição PROD e não recebem chave inventada por
nome, data aproximada, ordem ou cardinalidade.

## Delimitação de `private_runtime`

Existe um único SQL recursivo adicional sob
`backend/migrations/private_runtime/`. Ele é excluído deste inventário e do
catálogo de histórico porque a seleção e o derivador atuais consideram somente
arquivos diretos de `backend/migrations`. Inclusão futura requer contrato
próprio e alteraria o universo fechado `77/75`; este candidato não a autoriza.

## Próximo gate único

O próximo gate é parecer `APTO` conjunto de OpenCode e QWEN 3.8 FLASH sobre os
mesmos bytes. Nenhuma mudança de catálogo ou ledger é autorizada.
