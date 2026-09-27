import hashlib
import json
import datetime
from pathlib import Path
from sqlalchemy import create_engine
from tests.conftest_rls import assert_disposable_database
from tests import test_church_cell_public_data_s2b_pg17 as proof

url = 'postgresql+psycopg2://postgres:postgres@127.0.0.1:55477/s2b_exact_sql_test'
assert_disposable_database(url)
proof._SCHEMA = 'public'
source = proof._MIGRATION.read_text(encoding='utf-8')
if proof._migration_for_schema() != source:
    raise RuntimeError('A prova deve executar SQL original sem substituição')
engine = create_engine(url, future=True)
try:
    baseline = proof._prepare_pre_s2b_baseline(engine)
    proof.test_s2b_migration_is_idempotent_backfills_and_preserves_rls_acl((engine, baseline))
    baseline = proof._prepare_pre_s2b_baseline(engine)
    proof.test_s2b_anchor_fks_trigger_and_two_sim_are_tenant_scoped((engine, baseline))
    for wrong_command in (False, True):
        baseline = proof._prepare_pre_s2b_baseline(engine)
        proof.test_s2b_migration_requires_existing_igrejas_self_update_policy(
            (engine, baseline), wrong_command
        )
    result = {
        'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'base': '7a00383576878f90c1eb35bfd8648a09c4152529',
        'migration': proof._MIGRATION.name,
        'migration_sha256': hashlib.sha256(proof._MIGRATION.read_bytes()).hexdigest(),
        'test_sha256': hashlib.sha256(Path(proof.__file__).read_bytes()).hexdigest(),
        'namespace': 'public',
        'sql_original_unchanged': True,
        'postgres': '17.6-trixie',
        'database': 's2b_exact_sql_test descartável sintético',
        'proofs_passed': 4,
        'limits': 'Baseline sintética; sem DEV/PROD ou providers. Não comprova schema/ledger real nem deploy.'
    }
    Path('/tmp/igreja12-s2b-exact-sql-evidence.json').write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(result, ensure_ascii=False))
finally:
    engine.dispose()
