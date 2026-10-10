"""Legacy-release compatibility bridge on nominal SQL in owned PG17 only."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from tests.test_whatsapp_integrated_pg import migrated_factory,rls_database_url  # noqa: F401
from scripts.migrate import migration_files

pytestmark=pytest.mark.rls_integration
sys.path.insert(0,str(Path(__file__).parents[2]/'deploy'))
import emit_schema_check as bridge
from schema_compatibility import capture_catalog,SchemaCompatibilityError


def test_bridge_accepts_nominal_addition_and_rejects_wrong_revision_manifest_and_live_drift(migrated_factory):
    engine=migrated_factory.kw['bind']
    names=migration_files()
    with engine.connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        previous={'catalog':capture_catalog(connection),'migrations':names}
        connection.rollback()

        new_name='20261010_025800_synthetic_bridge.sql'
        with connection.begin():
            connection.exec_driver_sql('ALTER TABLE public.igrejas ADD COLUMN synthetic_bridge integer DEFAULT 0')
            connection.exec_driver_sql('UPDATE public.igrejas SET synthetic_bridge=1')
            connection.execute(text('INSERT INTO public.schema_migrations(name) VALUES (:name)'),{'name':new_name})
        candidate={'catalog':capture_catalog(connection),'migrations':names+[new_name]}
        connection.rollback()
        bundle=dict(previous_sha='a'*40,candidate_sha='b'*40,previous=previous,candidate=candidate)
        bridge.validate_bundle(bundle,'a'*40,'b'*40,names,names+[new_name])
        with pytest.raises(ValueError,match='revision mismatch'):
            bridge.validate_bundle(bundle,'c'*40,'b'*40,names,names+[new_name])
        with pytest.raises(ValueError,match='manifest mismatch'):
            bridge.validate_bundle(bundle,'a'*40,'b'*40,names,names)
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        bridge.verify_bundle(connection,bundle)
        connection.rollback()
        transaction=connection.begin()
        try:
            connection.exec_driver_sql('ALTER TABLE public.pessoas DISABLE ROW LEVEL SECURITY')
            with pytest.raises(SchemaCompatibilityError,match='catalogue drift'):
                bridge.verify_bundle(connection,bundle)
        finally:
            transaction.rollback()
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        bridge.verify_bundle(connection,bundle)
        connection.rollback()

def test_emitted_gate_rejects_unreviewed_hash_and_disposable_target_before_connecting(migrated_factory,tmp_path):
    engine=migrated_factory.kw['bind']
    names=migration_files()
    with engine.connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        reference={'catalog':capture_catalog(connection),'migrations':names}
    bundle=dict(previous_sha='a'*40,candidate_sha='b'*40,previous=reference,candidate=reference)
    path=tmp_path/'reviewed-schema.json'
    path.write_text(json.dumps(bundle,sort_keys=True))
    args=[sys.executable,str(Path(bridge.__file__).resolve()),'--bundle',str(path),
          '--sha256',hashlib.sha256(path.read_bytes()).hexdigest(),
          '--previous-sha','a'*40,'--candidate-sha','b'*40,
          '--previous-migrations',json.dumps(names),'--candidate-migrations',json.dumps(names)]
    emitted=subprocess.run(args,capture_output=True,text=True,check=True)
    compile(emitted.stdout,'generated_gate','exec')
    env=dict(os.environ,PASTORAI_RELEASE_SHA='a'*40,DATABASE_URL=engine.url.render_as_string(hide_password=False))
    result=subprocess.run([sys.executable,'-'],input=emitted.stdout,capture_output=True,text=True,env=env)
    assert result.returncode!=0 and 'nominal production database identity' in result.stderr
    args[args.index('--sha256')+1]='0'*64
    refused=subprocess.run(args,capture_output=True,text=True)
    assert refused.returncode!=0 and not refused.stdout
