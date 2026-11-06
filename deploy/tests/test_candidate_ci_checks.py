"""Candidate CI uses an actual tiny Git checkout and read-only fake GitHub."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess

import pytest

SPEC=importlib.util.spec_from_file_location('candidate_gate',Path(__file__).resolve().parents[1]/'check_integrated_candidate.py')
GATE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(GATE)
REPO='synthetic/repository'
NAMES=('backend-tests','frontend-ci','e2e-critical','rls-integration')


@pytest.fixture
def checkout(tmp_path):
    root=tmp_path/'synthetic';root.mkdir()
    def git(*args):
        return subprocess.check_output(['/usr/bin/git','-C',str(root),'-c','user.name=Synthetic',
            '-c','user.email=synthetic@example.test','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false',*args],
            env=dict(PATH='/usr/bin:/bin',LC_ALL='C',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1'),
            stderr=subprocess.DEVNULL,text=True).strip()
    git('init','--quiet');(root/'app.txt').write_text('synthetic\n');git('add','app.txt');git('commit','--quiet','-m','synthetic fixture')
    return root,git('rev-parse','HEAD')


def fetcher(sha):
    runs=[dict(id=i,name=name,head_sha=sha,status='completed',conclusion='success',app=dict(id=15368),
        html_url=f'https://github.com/{REPO}/actions/runs/{100+i}/job/{i}',
        url=f'https://api.github.com/repos/{REPO}/check-runs/{i}') for i,name in enumerate(NAMES,1)]
    return dict(total_count=len(runs),check_runs=runs)


def feature():
    assert callable(getattr(GATE,'check_candidate',None)),'exact local candidate CI gate is missing'
    return GATE.check_candidate


def test_four_checks_on_exact_clean_candidate_are_diagnostic_only(checkout):
    root,sha=checkout;calls=[]
    def fetch(path):calls.append(path);return fetcher(sha)
    report=feature()(REPO,sha,fetch,checkout=root)
    assert len(calls)==1 and set(report['checks'])==set(NAMES)
    assert report['ci_checks_verified'] is True and report['production_ready'] is report['authoritative_fence_proven'] is False
    assert report['sha']==sha and report['local_tree_clean'] is True


@pytest.mark.parametrize('dirty',['tracked','untracked','staged'])
def test_base_green_never_approves_uncommitted_candidate_or_fetches_network(checkout,dirty):
    root,sha=checkout
    if dirty=='untracked':(root/'new.py').write_text('synthetic')
    else:
        (root/'app.txt').write_text('changed')
        if dirty=='staged':subprocess.run(['/usr/bin/git','-C',str(root),'add','app.txt'],check=True)
    with pytest.raises(ValueError,match='uncommitted'):
        feature()(REPO,sha,lambda _p:pytest.fail('network before local candidate'),checkout=root)


def test_other_revision_refuses_before_network(checkout):
    root,_=checkout
    with pytest.raises(ValueError,match='revision'):
        feature()(REPO,'b'*40,lambda _p:pytest.fail('wrong revision fetched'),checkout=root)


def test_checkout_change_during_authenticated_get_refuses_old_green(checkout):
    root,sha=checkout
    def fetch(_path):
        (root/'app.txt').write_text('changed during read')
        return fetcher(sha)
    with pytest.raises(ValueError,match='uncommitted'):feature()(REPO,sha,fetch,checkout=root)


@pytest.mark.parametrize('flag',['--assume-unchanged','--skip-worktree'])
def test_index_flags_cannot_hide_changed_candidate_bytes(checkout,flag):
    root,sha=checkout
    subprocess.run(['/usr/bin/git','-C',str(root),'update-index',flag,'app.txt'],check=True)
    (root/'app.txt').write_text('hidden local edit')
    with pytest.raises(ValueError,match='index'):
        feature()(REPO,sha,lambda _p:pytest.fail('network with hidden changes'),checkout=root)


@pytest.mark.parametrize('fault',['missing','sha','app','pending','failure','skipped','neutral','latest-failure',
    'duplicate-id','bool-id','cross-repo-url','partial-page','wrong-type'])
def test_remote_names_alone_cannot_satisfy_candidate_checks(checkout,fault):
    root,sha=checkout;body=fetcher(sha);row=body['check_runs'][0]
    if fault=='missing':body['check_runs'].pop();body['total_count']-=1
    elif fault=='sha':row['head_sha']='b'*40
    elif fault=='app':row['app']['id']=42
    elif fault=='pending':row['status']='in_progress';row['conclusion']=None
    elif fault in ('failure','skipped','neutral'):row['conclusion']=fault
    elif fault=='latest-failure':body['check_runs'].append(deepcopy(row)|dict(id=99,conclusion='failure',url=f'https://api.github.com/repos/{REPO}/check-runs/99'));body['total_count']+=1
    elif fault=='duplicate-id':body['check_runs'][1]['id']=row['id']
    elif fault=='bool-id':row['id']=True
    elif fault=='cross-repo-url':row['url']='https://api.github.com/repos/other/repo/check-runs/1'
    elif fault=='partial-page':body['total_count']=101
    else:body=[]
    with pytest.raises(ValueError):feature()(REPO,sha,lambda _p:body,checkout=root)


def test_duplicate_trusted_check_context_is_ambiguous_even_with_successful_high_id(checkout):
    root,sha=checkout;body=fetcher(sha);new=deepcopy(body['check_runs'][0]);new.update(id=99,url=f'https://api.github.com/repos/{REPO}/check-runs/99');body['check_runs'][0]['conclusion']='failure';body['check_runs'].append(new);body['total_count']+=1
    with pytest.raises(ValueError,match='ambiguous'):feature()(REPO,sha,lambda _p:body,checkout=root)
