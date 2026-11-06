#!/usr/bin/env python3
"""Current-main publishing gate and read-only exact-candidate CI diagnostic.

No gh subprocess, PR artifacts or fork checkout. The workflow consumes only
this allowlisted integrated revision before gaining registry/SSH permissions.
The optional candidate diagnostic cannot authorize publication or deployment.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import Request, urlopen

WORKFLOWS = ('backend-tests.yml', 'frontend-ci.yml', 'e2e-critical.yml', 'rls-integration.yml', 'synthetic-release.yml')
REQUIRED_CHECKS = ('backend-tests', 'frontend-ci', 'e2e-critical', 'rls-integration')


def _candidate_checkout(checkout, sha):
    """Git metadata only; no checkout/reset/fetch and no credential helper."""
    root = Path(checkout).resolve()
    env = dict(PATH='/usr/bin:/bin', LC_ALL='C', GIT_OPTIONAL_LOCKS='0',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    def git(*args, optional=False):
        result = subprocess.run(['/usr/bin/git', '-C', str(root), '-c', 'core.fsmonitor=false',
                                 '-c', 'core.trustctime=true', '-c', 'core.checkstat=default',
                                 '-c', 'core.ignorestat=false', *args],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=5, env=env, check=False)
        if result.returncode != 0 and not (optional and result.returncode == 1):
            raise ValueError('candidate checkout unavailable')
        return result.stdout.strip()
    if Path(git('rev-parse', '--show-toplevel')).resolve() != root or git('rev-parse', 'HEAD') != sha:
        raise ValueError('candidate checkout revision mismatch')
    entries = git('ls-files', '-v', '-z').split('\0')
    if any(row and not row.startswith('H ') for row in entries):
        raise ValueError('candidate checkout index hides tracked state')
    if git('config', '--get-regexp', r'^filter\..*\.(clean|smudge|process)$', optional=True):
        raise ValueError('candidate checkout uses unsupported content filters')
    if git('status', '--porcelain=v1', '--untracked-files=all', '--ignore-submodules=none'):
        raise ValueError('candidate checkout has uncommitted changes')


def check_candidate(repository, sha, fetch, *, checkout):
    """Read-only diagnostic for the exact clean candidate, never deploy authority.

    fetch is a trusted authenticated GET transport, not caller-supplied evidence.
    The existing current-main/five-workflow publishing gate below is unchanged.
    CI checks attest their committed tree; they never approve dirty local edits,
    source containment, a migration, application readiness or production.
    """
    if (type(sha) is not str or not re.fullmatch('[0-9a-f]{40}', sha)
            or type(repository) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)):
        raise ValueError('invalid repository revision')
    _candidate_checkout(checkout, sha)  # Refuse before any authenticated request.
    body = fetch(f'/repos/{repository}/commits/{sha}/check-runs?filter=latest&per_page=100')
    if (type(body) is not dict or type(body.get('check_runs')) is not list
            or type(body.get('total_count')) is not int
            or not 0 <= body['total_count'] == len(body['check_runs']) <= 100):
        raise ValueError('candidate checks incomplete')
    checks, ids = {}, set()
    for row in body['check_runs']:
        if type(row) is not dict or type(row.get('id')) is not int or row['id'] <= 0 or row['id'] in ids:
            raise ValueError('candidate check identity invalid')
        ids.add(row['id'])
        if row.get('name') not in REQUIRED_CHECKS:
            continue
        app = row.get('app')
        if type(app) is not dict or type(app.get('id')) is not int or app['id'] != 15368:
            continue
        if (row.get('head_sha') != sha
                or row.get('url') != f'https://api.github.com/repos/{repository}/check-runs/{row["id"]}'):
            raise ValueError('candidate check repository revision mismatch')
        # The API's latest selection is authoritative; numeric IDs are not a
        # substitute for recency/attempt metadata. Ambiguous contexts refuse.
        if row['name'] in checks:
            raise ValueError('candidate check context ambiguous')
        checks[row['name']] = dict(id=row['id'], status=row.get('status'), conclusion=row.get('conclusion'),
                                   app_id=15368, url=row['url'])
    if set(checks) != set(REQUIRED_CHECKS) or any(
            row['status'] != 'completed' or row['conclusion'] != 'success' for row in checks.values()):
        raise ValueError('mandatory candidate check missing or not successful')
    _candidate_checkout(checkout, sha)  # Refuse local changes during the GET too.
    return dict(schema='igreja12.candidate-ci-checks/1', repository=repository, sha=sha,
                checks=checks, local_tree_clean=True, ci_checks_verified=True,
                authoritative_fence_proven=False, production_ready=False)


def check(repository, sha, fetch):
    if not re.fullmatch('[0-9a-f]{40}', sha) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('invalid repository revision')
    if fetch(f'/repos/{repository}/git/ref/heads/main')['object']['sha'] != sha:
        raise ValueError('candidate is no longer current main')
    for workflow in WORKFLOWS:
        runs = fetch(f'/repos/{repository}/actions/workflows/{workflow}/runs?head_sha={sha}&event=push&per_page=100')['workflow_runs']
        eligible = [run for run in runs if run['head_sha'] == sha and run['head_branch'] == 'main' and run['head_repository']['full_name'] == repository]
        if not eligible:
            raise ValueError('mandatory integrated workflow missing')
        latest = max(eligible, key=lambda run: (run['run_number'], run['run_attempt']))
        if latest['status'] != 'completed' or latest['conclusion'] != 'success':
            raise ValueError('mandatory integrated workflow not successful')
    return sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sha')
    parser.add_argument('--candidate-checkout', type=Path)
    parser.add_argument('--repository')
    args = parser.parse_args()
    def fetch(path):
        request = Request('https://api.github.com'+path, headers={
            'Authorization': 'Bearer '+os.environ['GH_TOKEN'],
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        with urlopen(request, timeout=15) as result:
            return json.load(result)
    if args.candidate_checkout is not None:
        repository = args.repository or os.environ['GITHUB_REPOSITORY']
        print(json.dumps(check_candidate(repository, args.sha, fetch, checkout=args.candidate_checkout), sort_keys=True))
    else:
        if args.repository is not None:
            raise ValueError('repository override requires candidate diagnostic mode')
        print(check(os.environ['GITHUB_REPOSITORY'], args.sha, fetch))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('integrated candidate refused', file=sys.stderr)
        sys.exit(1)
