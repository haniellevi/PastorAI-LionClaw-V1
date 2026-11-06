"""Fixed, single-process Uvicorn bootstrap; no exec, reload or worker spawning.

Mount this module and native_candidate_ca.py read-only beside a public profile.
The expected profile SHA must be supplied by trusted composition independently.
This entrypoint alone grants no operational/A8 admission. Runtime dependencies
Uvicorn and app code come from the separately pinned candidate image.
Trusted composition must verify /app bytes/mounts independently; this module
does not turn an arbitrary application directory into trusted code.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

APP_DIRECTORY = '/app'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--expect-profile-sha256',required=True)
    parser.add_argument('--admission-timeout',type=float,default=30)
    args=parser.parse_args(argv)
    # -I intentionally excludes the script directory. Load the single sibling
    # implementation explicitly; its bytes/mounts must be independently pinned.
    module_path=Path(__file__).resolve().with_name('first_transition_native_candidate_ca.py')
    spec=importlib.util.spec_from_file_location('igreja12_candidate_ca_runtime',module_path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module;spec.loader.exec_module(module)
    fd=None
    try:
        module.need(not any(name=='app' or name.startswith('app.') for name in sys.modules)
                    and not any(name.startswith('UVICORN_') or name in ('WEB_CONCURRENCY','GUNICORN_CMD_ARGS')
                                for name in os.environ),'native-candidate-bootstrap-process')
        path=Path(args.profile)
        module.need(path.is_absolute() and '..' not in path.parts,'native-candidate-bootstrap-profile')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
        import stat
        info=os.fstat(fd)
        module.need(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and 0<info.st_size<=16384
                    and not info.st_mode&0o022,'native-candidate-bootstrap-profile')
        raw=os.pread(fd,16385,0)
        module.need(len(raw)==info.st_size and module._pin(os.fstat(fd))==module._pin(info),
                    'native-candidate-bootstrap-profile')
        profile=module.CandidateCAProfile.from_dict(json.loads(raw))
        with module.NativeCandidateCA(profile,args.expect_profile_sha256) as custody:
            admission_path=Path(__file__).resolve().with_name('first_transition_native_candidate_admission.py')
            admission_spec=importlib.util.spec_from_file_location('igreja12_candidate_admission_runtime',admission_path)
            admission=importlib.util.module_from_spec(admission_spec)
            sys.modules[admission_spec.name]=admission;admission_spec.loader.exec_module(admission)
            admission.serve_admission(custody,timeout=args.admission_timeout)
            sys.path.insert(0,APP_DIRECTORY)  # explicit fixed image path under python -I
            import uvicorn
            uvicorn.run('app.main:app',host='0.0.0.0',port=8000,workers=1,reload=False)
        return 0
    except Exception:
        raise SystemExit('native-candidate-bootstrap-refused') from None
    finally:
        if fd is not None:os.close(fd)


if __name__=='__main__':raise SystemExit(main())
