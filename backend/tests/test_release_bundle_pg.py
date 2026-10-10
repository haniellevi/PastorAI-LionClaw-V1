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
from sqlalchemy.exc import IntegrityError


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


@pytest.mark.parametrize('action', ['NO ACTION', 'RESTRICT', 'CASCADE', 'SET NULL', 'SET DEFAULT'])
def test_new_child_foreign_key_refuses_legacy_parent_delete_recovery(migrated_factory, action):
    engine=migrated_factory.kw['bind']
    names=migration_files()
    with engine.connect() as connection:
        with connection.begin():
            connection.exec_driver_sql('CREATE TABLE public.synthetic_legacy_parent(id integer PRIMARY KEY)')
            connection.exec_driver_sql('INSERT INTO public.synthetic_legacy_parent VALUES (1)')
        previous={'catalog':capture_catalog(connection),'migrations':names}
        connection.rollback()
        with connection.begin():
            connection.exec_driver_sql('CREATE TABLE public.synthetic_new_child('
                'id integer PRIMARY KEY, parent_id integer REFERENCES public.synthetic_legacy_parent(id) '
                f'ON DELETE {action})')
            connection.exec_driver_sql('INSERT INTO public.synthetic_new_child VALUES (1,1)')
        candidate={'catalog':capture_catalog(connection),'migrations':names}
        connection.rollback()
        bundle=dict(previous_sha='a'*40,candidate_sha='b'*40,previous=previous,candidate=candidate)
        # The real catalogue includes the referenced table and both actions.
        reference=candidate['catalog']['foreign_keys']['synthetic_new_child.synthetic_new_child_parent_id_fkey']
        assert reference[:2]==['public','synthetic_legacy_parent']
        assert reference[3]=={'NO ACTION':'a','RESTRICT':'r','CASCADE':'c','SET NULL':'n','SET DEFAULT':'d'}[action]
        with pytest.raises(SchemaCompatibilityError,match='previous schema contract changed'):
            bridge.validate_bundle(bundle,'a'*40,'b'*40,names,names)
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        with pytest.raises(SchemaCompatibilityError,match='previous schema contract changed'):
            bridge.verify_bundle(connection,bundle)
        connection.rollback()
        # Exercise the legacy operation: it is blocked or alters new data.
        with connection.begin():
            if action in ('NO ACTION','RESTRICT'):
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        connection.exec_driver_sql('DELETE FROM public.synthetic_legacy_parent WHERE id=1')
                assert connection.exec_driver_sql('SELECT parent_id FROM public.synthetic_new_child').scalar_one()==1
            else:
                connection.exec_driver_sql('DELETE FROM public.synthetic_legacy_parent WHERE id=1')
                rows=connection.exec_driver_sql('SELECT parent_id FROM public.synthetic_new_child').all()
                assert rows==([] if action=='CASCADE' else [(None,)])


def test_foreign_key_between_new_tables_keeps_legacy_contract(migrated_factory):
    engine=migrated_factory.kw['bind']
    names=migration_files()
    with engine.connect() as connection:
        previous={'catalog':capture_catalog(connection),'migrations':names}
        connection.rollback()
        with connection.begin():
            connection.exec_driver_sql('CREATE TABLE public.synthetic_new_parent(id integer PRIMARY KEY)')
            connection.exec_driver_sql('CREATE TABLE public.synthetic_new_child('
                'id integer PRIMARY KEY, parent_id integer REFERENCES public.synthetic_new_parent(id) ON DELETE CASCADE)')
        candidate={'catalog':capture_catalog(connection),'migrations':names}
        connection.rollback()
        bundle=dict(previous_sha='a'*40,candidate_sha='b'*40,previous=previous,candidate=candidate)
        bridge.validate_bundle(bundle,'a'*40,'b'*40,names,names)
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        bridge.verify_bundle(connection,bundle)
        connection.rollback()
        # Older bundles cannot silently omit the new referential envelope.
        del previous['catalog']['foreign_keys']
        with pytest.raises(SchemaCompatibilityError,match='incomplete catalogue contract'):
            bridge.validate_bundle(bundle,'a'*40,'b'*40,names,names)
