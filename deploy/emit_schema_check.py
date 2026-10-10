#!/usr/bin/env python3
"""Emit a standalone read-only schema verifier for the legacy release image.

The bundle must be reconstructed from nominal previous/candidate migrations,
reviewed by hash and bound to both revisions. No database connection here.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from schema_compatibility import verify_additive_compatibility


def validate_bundle(bundle, previous_sha, candidate_sha, previous_names, candidate_names):
    if (type(bundle) is not dict or set(bundle)!={'previous_sha','candidate_sha','previous','candidate'}
        or any(not re.fullmatch('[0-9a-f]{40}',sha) for sha in (previous_sha,candidate_sha))
        or previous_sha==candidate_sha or bundle['previous_sha']!=previous_sha or bundle['candidate_sha']!=candidate_sha):
        raise ValueError('schema bundle revision mismatch')
    for kind,names in (('previous',previous_names),('candidate',candidate_names)):
        if type(bundle[kind]) is not dict or set(bundle[kind])!={'catalog','migrations'} or sorted(bundle[kind]['migrations'])!=sorted(names):
            raise ValueError('schema bundle manifest mismatch')
    verify_additive_compatibility(previous=bundle['previous']['catalog'],candidate=bundle['candidate']['catalog'],
        live=bundle['candidate']['catalog'],previous_migrations=previous_names,
        candidate_migrations=candidate_names,applied_migrations=candidate_names)
    return bundle


def verify_bundle(connection,bundle):
    from schema_compatibility import capture_catalog
    # Caller starts a read-only transaction on the existing guarded connection.
    applied=list(connection.exec_driver_sql('SELECT name FROM public.schema_migrations').scalars())
    verify_additive_compatibility(previous=bundle['previous']['catalog'],candidate=bundle['candidate']['catalog'],
        live=capture_catalog(connection),previous_migrations=bundle['previous']['migrations'],
        candidate_migrations=bundle['candidate']['migrations'],applied_migrations=applied)


def main():
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--previous-sha',required=True)
    parser.add_argument('--candidate-sha',required=True)
    parser.add_argument('--previous-migrations',required=True)
    parser.add_argument('--candidate-migrations',required=True)
    parser.add_argument('--legacy-checker',type=Path)
    args=parser.parse_args()
    if not args.bundle.is_absolute() or args.bundle.suffix!='.json' or args.bundle.is_symlink() or not re.fullmatch('[0-9a-f]{64}',args.sha256):
        raise ValueError('reviewed absolute schema bundle required')
    raw=args.bundle.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.sha256:
        raise ValueError('reviewed schema bundle hash mismatch')
    bundle=validate_bundle(json.loads(raw),args.previous_sha,args.candidate_sha,
        json.loads(args.previous_migrations),json.loads(args.candidate_migrations))
    # Source and JSON are Python literals, not interpolated executable input.
    source=(Path(__file__).with_name('schema_compatibility.py')).read_text()
    script=(f'exec(compile({source!r},"schema_compatibility","exec"))\n'
        'import json,os,sys,re\nfrom sqlalchemy import create_engine\nfrom sqlalchemy.engine import make_url\n'
        f'bundle=json.loads({json.dumps(bundle,sort_keys=True)!r})\n'
        f'if os.environ.get("PASTORAI_RELEASE_SHA")!={args.previous_sha!r}: raise SystemExit("active image revision unverifiable")\n'
        'url=make_url(os.environ["DATABASE_URL"])\n'
        'project="pffafnchtxbimpwyaczq"\n'
        'direct=url.host=="db."+project+".supabase.co" and url.username=="postgres"\n'
        'pooler=bool(re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\\.pooler\\.supabase\\.com",url.host or "")) and url.username=="postgres."+project\n'
        'if not (url.drivername in {"postgresql","postgresql+psycopg2"} and url.database=="postgres" and url.port in {5432,6543} and (direct or pooler) and dict(url.query)=={"sslmode":"verify-full","sslrootcert":"system"}): raise SystemExit("nominal production database identity or TLS unverifiable")\n'
        'engine=create_engine(url)\n'
        'with engine.connect() as connection:\n'
        '    connection.exec_driver_sql("SET TRANSACTION READ ONLY")\n'
        '    verify_additive_compatibility(previous=bundle["previous"]["catalog"],candidate=bundle["candidate"]["catalog"],\n'
        '        live=capture_catalog(connection),previous_migrations=bundle["previous"]["migrations"],\n'
        '        candidate_migrations=bundle["candidate"]["migrations"],\n'
        '        applied_migrations=list(connection.exec_driver_sql("SELECT name FROM public.schema_migrations").scalars()))\n'
        'engine.dispose()\n')
    if args.legacy_checker:
        # Keep the previous version's required-column contract after proving
        # the complete additive envelope. Ledger is the exact candidate set.
        script+=f'exec(compile({args.legacy_checker.read_text()!r},"legacy_checker","exec"),{{"__name__":"__main__"}})\n'
    print('try:\n'+'\n'.join('    '+line for line in script.splitlines())+'\nexcept Exception:\n    raise SystemExit("schema compatibility refused") from None\n')


if __name__=='__main__':
    try:
        main()
    except Exception:
        raise SystemExit('reviewed schema verifier refused')
