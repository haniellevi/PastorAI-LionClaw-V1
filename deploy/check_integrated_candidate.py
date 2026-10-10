#!/usr/bin/env python3
"""Check latest successful workflow runs of the exact current main revision.

No gh subprocess, PR artifacts or fork checkout. The workflow consumes only
this allowlisted integrated revision before gaining registry/SSH permissions.
"""
import json
import os
import re
import sys
from urllib.request import Request, urlopen

WORKFLOWS = ('backend-tests.yml', 'frontend-ci.yml', 'e2e-critical.yml', 'rls-integration.yml', 'synthetic-release.yml')


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
    def fetch(path):
        request = Request('https://api.github.com'+path, headers={
            'Authorization': 'Bearer '+os.environ['GH_TOKEN'],
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        with urlopen(request, timeout=15) as result:
            return json.load(result)
    print(check(os.environ['GITHUB_REPOSITORY'], sys.argv[1], fetch))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('integrated candidate refused', file=sys.stderr)
        sys.exit(1)
