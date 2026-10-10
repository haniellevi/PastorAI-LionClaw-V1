#!/usr/bin/env python3
"""Actual Docker process swap and queue retention, on owned disposable stacks.

No ports or connection strings are accepted for a database. Independent schema
expectation is reconstructed in a different PostgreSQL cluster, then verified
against the target. Neither cluster can reach external services.
"""
import argparse
import base64
import json
import os
import secrets
import tempfile
import uuid
from pathlib import Path

from dev_coordination import DevCoordinator, package_id
from dev_pipeline import Executor, PipelineRefused, schema_id


def main():
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--backend-image',required=True)
    parser.add_argument('--frontend-image',required=True)
    parser.add_argument('--sha',required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--schema-output',type=Path)
    args=parser.parse_args()
    prefix='pastorai-synthetic-rehearsal-'+uuid.uuid4().hex[:8]
    stacks=[]
    with tempfile.TemporaryDirectory(prefix='pastorai-synthetic-rehearsal-') as directory:
        root=Path(directory)
        runtime=root/'synthetic-runtime.conf'
        runtime.write_text('\n'.join([
            'DATABASE_URL=postgresql://postgres:synthetic-only@postgres:5432/rls_disposable',
            'SUPABASE_URL=http://127.0.0.1:54321',
            'EVOLUTION_WEBHOOK_SECRET=synthetic-offline-only',
            'SESSION_JWT_SECRET='+secrets.token_hex(32),
            'SECRETS_ENCRYPTION_KEY='+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            'BROADCAST_ASYNC_ENABLED=false',
        ])+'\n')
        runtime.chmod(0o600)
        candidate=dict(sha=args.sha,frontend_sha=args.sha,backend_digest=args.backend_image,
            frontend_digest=args.frontend_image, frontend_origin='https://synthetic-dev.example.test',
            api_origin='https://synthetic-api.example.test',schema='b'*64,seed='synthetic-v1',
            sequence=1,environment='dev-sintetico')
        def create(name):
            config=dict(project=name,profile='rehearsal',approved_project='disposable',
                runtime_env_file=str(runtime),state_dir=str(root/name),backend_repository='',
                frontend_repository='',api_port=18073,frontend_port=13073)
            executor=Executor(config,candidate)
            # Rehearsal only. Docker daemon/context guard precedes first effect.
            context=json.loads(executor.runner(['docker','context','inspect']))[0]
            if context['Endpoints']['docker']['Host']!='unix:///var/run/docker.sock' or os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
                raise PipelineRefused('local disposable Docker required')
            stacks.append(executor)
            executor.call('up','-d','--wait','postgres','redis')
            executor.database('bootstrap')
            return executor
        try:
            reference=create(prefix+'-reference')
            reference.database('migrate')
            expected=json.loads(reference.database('capture'))
            if args.schema_output:
                args.schema_output.write_text(json.dumps(expected,sort_keys=True)+'\n')
            candidate['schema']=schema_id(expected)
            target=create(prefix+'-target')
            coordinator=DevCoordinator(target.state)
            target.env['REHEARSAL_FRESH_DATABASE']='true'
            coordinator.transition(candidate,operation='deploy',execute=lambda _p: target.promote(expected))
            target.env.pop('REHEARSAL_FRESH_DATABASE',None)
            token=coordinator.reserve(owner='synthetic-owner')
            coordinator.finish(token=token,owner='synthetic-owner')
            # Stop actual API and consumers without touching their gate config
            # or deleting the persistent Redis volume. Queue data survives.
            target.contain()
            target.call('exec','-T','redis','redis-cli','RPUSH','pastorai:webhooks','synthetic-pending-item')
            target.call('exec','-T','redis','redis-cli','RPUSH','pastorai:webhooks:processing','synthetic-in-flight-item')
            assert target.call('exec','-T','redis','redis-cli','LLEN','pastorai:webhooks').strip()=='1'
            # Failure after the physical swap must leave no false acceptance.
            good_health=target.health
            target.health=lambda **_k: (_ for _ in ()).throw(PipelineRefused('synthetic post-swap failure'))
            newer=candidate|{'sequence':2}
            target.package=newer
            try:
                coordinator.transition(newer,operation='deploy',execute=lambda _p: target.promote(expected))
            except PipelineRefused:
                pass
            else:
                raise AssertionError('failed smoke accepted')
            state=json.loads((target.state/'state.json').read_text())
            assert state['recovery_required'] and state['package']==candidate
            assert token in state['receipts']
            for service in ('backend','queue-worker','cron-worker','broadcast-worker'):
                assert not target.call('ps','--status','running','-q',service).strip()
            assert target.call('exec','-T','redis','redis-cli','LPOP','pastorai:webhooks').strip()=='synthetic-pending-item'
            assert target.call('exec','-T','redis','redis-cli','LPOP','pastorai:webhooks:processing').strip()=='synthetic-in-flight-item'
            target.package=candidate
            target.health=good_health
            coordinator.record_recovery(candidate,verify=lambda _p: target.recover(expected))
            pending=coordinator.reserve(owner='synthetic-owner')
            reset_package=candidate|{'seed':'synthetic-v2'}
            target.package=reset_package
            target.env['REHEARSAL_FRESH_DATABASE']='true'
            coordinator.transition(reset_package,operation='reset',execute=lambda _p: target.reset(expected,package_id(reset_package)))
            state=json.loads((target.state/'state.json').read_text())
            assert state['invalidated'][pending]=='reset' and token in state['receipts']
            assert not state['recovery_required'] and state['package']==reset_package
            args.report.write_text(json.dumps(dict(status='pass',sha=args.sha,
                backend_image=args.backend_image,frontend_image=args.frontend_image,
                schema=candidate['schema'],checks=['independent-migrations','process-readiness',
                'frontend-http-headers','persistent-pending-queue','failed-swap-containment',
                'additive-code-recovery','synthetic-reset','reset-reservation-invalidated',
                'completed-acceptance-preserved']),sort_keys=True,indent=2)+'\n')
        finally:
            for executor in reversed(stacks):
                # Named stack is created here with synthetic resource labels.
                executor.call('down','--volumes','--remove-orphans')


if __name__=='__main__':
    main()
