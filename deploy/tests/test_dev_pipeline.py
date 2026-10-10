"""Controller boundary tests. Physical Docker rehearsal is a separate command."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dev_pipeline as pipeline
from test_dev_coordination import package


def configuration(tmp_path):
    return dict(project='pastorai-synthetic-test', profile='rehearsal', approved_project='disposable',
        runtime_env_file=str(tmp_path/'synthetic-config'), state_dir=str(tmp_path/'state'),
        backend_repository='', frontend_repository='', api_port=18000, frontend_port=13000)


@pytest.mark.parametrize('mutation', [
    {'profile':'production'}, {'project':'pastorai-production'}, {'approved_project':'production'},
    {'api_port':True}, {'frontend_port':18000}, {'runtime_env_file':'relative'},
    {'profile':'online', 'approved_project':'pffafnchtxbimpwyaczq'},
    {'profile':'online', 'approved_project':'cxmjojnocigekgcxhubi', 'backend_repository':'latest'},
])
def test_invalid_configuration_never_calls_docker(tmp_path, mutation):
    calls = []
    with pytest.raises(pipeline.PipelineRefused):
        pipeline.Executor(configuration(tmp_path)|mutation, package(), runner=lambda *a, **k: calls.append(a))
    assert not calls


def test_frontend_wrong_build_origin_is_refused_before_container_change(tmp_path):
    expected = {'catalog':{}, 'migrations':['synthetic.sql']}
    candidate = package()|{'schema':pipeline.schema_id(expected)}
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ['docker','context','inspect']:
            return json.dumps([{'Endpoints':{'docker':{'Host':'unix:///var/run/docker.sock'}}}])
        return json.dumps([{'Config':{'Labels':{'org.opencontainers.image.revision':candidate['sha'],
            'pastorai.api-origin':'https://api.igreja12.com.br', 'pastorai.frontend-origin':candidate['frontend_origin']}}}])
    executor = pipeline.Executor(configuration(tmp_path), candidate, runner=runner)
    with pytest.raises(pipeline.PipelineRefused, match='frontend build target'):
        executor.preflight(expected)
    assert not any('compose' in args for args in calls)


def test_failure_after_start_contains_api_and_consumers_and_keeps_previous_schema(tmp_path, monkeypatch):
    expected = {'catalog':{}, 'migrations':['synthetic.sql']}
    calls=[]
    executor=pipeline.Executor(configuration(tmp_path), package()|{'schema':pipeline.schema_id(expected)},
                               runner=lambda argv, **k: calls.append(argv) or '')
    previous={'catalog':{'old':True},'migrations':['old.sql']}
    (executor.state/'current-schema.json').write_text(json.dumps(previous))
    monkeypatch.setattr(executor,'preflight',lambda _e: None)
    monkeypatch.setattr(executor,'health',lambda **_k: (_ for _ in ()).throw(pipeline.PipelineRefused('smoke failed')))
    with pytest.raises(pipeline.PipelineRefused, match='smoke failed'):
        executor.promote(expected)
    stops=[args for args in calls if 'stop' in args]
    assert len(stops)==2 and all('backend' in args and all(c in args for c in pipeline.CONSUMERS) for args in stops)
    assert not any('down' in args or 'redis' in args for args in stops)
    assert json.loads((executor.state/'current-schema.json').read_text())==previous


_spec=importlib.util.spec_from_file_location('integrated_candidate',Path(__file__).parents[1]/'check_integrated_candidate.py')
gate=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


@pytest.mark.parametrize('bad', ['old-main','failed','running','fork','missing','newer-attempt'])
def test_only_exact_integrated_revision_with_latest_four_checks_can_publish(bad):
    sha='a'*40
    def fetch(path):
        if '/git/ref/' in path:
            return {'object':{'sha':'b'*40 if bad=='old-main' else sha}}
        runs=[dict(head_sha=sha,head_branch='main',head_repository={'full_name':'owner/repo'},
                   run_number=1,run_attempt=1,status='completed',conclusion='success')]
        if bad=='failed': runs[0]['conclusion']='failure'
        if bad=='running': runs[0]['status']='in_progress'
        if bad=='fork': runs[0]['head_repository']['full_name']='other/repo'
        if bad=='missing': runs=[]
        if bad=='newer-attempt': runs.append(runs[0]|{'run_attempt':2,'status':'in_progress','conclusion':None})
        return {'workflow_runs':runs}
    with pytest.raises(ValueError): gate.check('owner/repo',sha,fetch)


def test_integrated_gate_accepts_successful_latest_workflows():
    sha='a'*40
    def fetch(path):
        if '/git/ref/' in path: return {'object':{'sha':sha}}
        return {'workflow_runs':[dict(head_sha=sha,head_branch='main',head_repository={'full_name':'owner/repo'},
            run_number=1,run_attempt=1,status='completed',conclusion='success')]}
    assert gate.check('owner/repo',sha,fetch)==sha


def test_parent_environment_cannot_turn_deploy_into_reset(tmp_path,monkeypatch):
    for key in ('DEV_RESET_APPROVED_PROJECT','DEV_RESET_EMPTY_SCHEMA','REHEARSAL_FRESH_DATABASE'):
        monkeypatch.setenv(key,'true')
    executor=pipeline.Executor(configuration(tmp_path),package())
    assert not any(key in executor.env for key in ('DEV_RESET_APPROVED_PROJECT','DEV_RESET_EMPTY_SCHEMA','REHEARSAL_FRESH_DATABASE'))


def test_incompatible_live_schema_never_restarts_old_code(tmp_path,monkeypatch):
    expected={'catalog':{},'migrations':['synthetic.sql']}
    calls=[]
    def runner(argv,**_k):
        calls.append(argv)
        if 'verify' in argv:
            raise pipeline.PipelineRefused('schema incompatible')
        return ''
    executor=pipeline.Executor(configuration(tmp_path),package()|{'schema':pipeline.schema_id(expected)},runner=runner)
    (executor.state/'current-schema.json').write_text(json.dumps(expected))
    (executor.receipts/(pipeline.schema_id(expected)+'.json')).write_text(json.dumps(expected))
    monkeypatch.setattr(executor,'preflight',lambda _e: None)
    with pytest.raises(pipeline.PipelineRefused,match='schema incompatible'):
        executor.recover(expected)
    assert not any('up' in argv for argv in calls)


def test_reset_needs_exact_confirmation_before_any_docker_call(tmp_path):
    calls=[]
    executor=pipeline.Executor(configuration(tmp_path),package(),runner=lambda argv,**_k: calls.append(argv))
    with pytest.raises(pipeline.PipelineRefused,match='reset package confirmation'):
        executor.reset({'catalog':{},'migrations':['synthetic.sql']},'wrong-confirmation')
    assert not calls


@pytest.mark.parametrize('base,expected',[('main','ok'),('codex/temporary','pendente'),(None,'pendente')])
def test_temporary_base_merge_cannot_be_reported_as_main_integration(base,expected):
    path=Path(__file__).parents[2]/'docs/ops/acompanhamento/atualizar.py'
    spec=importlib.util.spec_from_file_location('progress_model',path)
    model=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    assert model.indicador_main({'ok':True,'dados':{'estado':'MERGED','base':base}})['status']==expected
