from pathlib import Path, PurePosixPath
import os, stat, subprocess, sys, json, hashlib, tarfile, gzip, io, datetime, zlib

REPO=Path('/home/raniel-linux/.codex/worktrees/fase1-a3-transicao-20261029/PastorAi-1.0')
DEST=Path('/home/raniel-linux/igreja12-release-candidates/A4-20261030')
APP='afdfb78d71a53f2861632806e13cdda4662d7d63'
EXEC='37c7d68d60b6f86cfb1fe75d4c720530537845d6'
CTRL='6d46206c8b92e6a932a87cf4fde84a2f81b11b19'
MODULES=('first_transition_adapter.py','first_transition_local_backup.py',
 'first_transition_host_contract.py','first_transition_host_transport.py','first_transition_host_driver.py',
 'first_transition_database.py','first_transition_candidate.py','first_transition_orchestrator.py',
 'initial_transition_files.py','package_backend_release.py','initial_transition_ops.py','release_topology.py')
sys.dont_write_bytecode=True

def require(ok,code):
 if not ok:raise RuntimeError(code)
def git(*args):return subprocess.check_output(['git','-C',str(REPO),*args])
def sha(b):return hashlib.sha256(b).hexdigest()
def encoded(x):return (json.dumps(x,sort_keys=True,indent=2)+'\n').encode()
def new_file(p,data):
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
def new_dir(p):p.mkdir(mode=0o700)
def archive(path,contents):
 b=io.BytesIO()
 with tarfile.open(fileobj=b,mode='w',format=tarfile.PAX_FORMAT) as t:
  dirs={str(p) for n in contents for p in PurePosixPath(n).parents if str(p)!='.'}
  for n in sorted(dirs):
   i=tarfile.TarInfo(n+'/');i.type=tarfile.DIRTYPE;i.mode=0o755;t.addfile(i)
  for n,data in sorted(contents.items()):
   i=tarfile.TarInfo(n);i.mode=0o644;i.size=len(data);t.addfile(i,io.BytesIO(data))
 new_file(path,gzip.compress(b.getvalue(),mtime=0))
def verify_archive(path,expected):
 names=[]
 with tarfile.open(path,mode='r:gz') as t:
  for m in t:
   q=PurePosixPath(m.name)
   require(not q.is_absolute() and '..' not in q.parts and m.uid==m.gid==m.mtime==0,'archive-entry')
   require(not(m.issym() or m.islnk() or m.isdev()),'archive-type')
   if m.isdir():continue
   require(m.isfile() and m.name in expected and m.name not in names,'archive-scope')
   require(t.extractfile(m).read()==expected[m.name],'archive-content')
   names.append(m.name)
 require(set(names)==set(expected),'archive-missing')
 return len(names)

require(sys.version_info[:2]==(3,13),'python-version')
require(git('rev-parse','HEAD').decode().strip()==CTRL,'controller-checkout-pin')
require(not os.path.lexists(DEST),'destination-exists')
for p in reversed(DEST.parent.parents):
 m=os.lstat(p).st_mode;require(stat.S_ISDIR(m) and not stat.S_ISLNK(m),'parent-type')
if os.path.lexists(DEST.parent):
 m=os.lstat(DEST.parent).st_mode;require(stat.S_ISDIR(m) and not stat.S_ISLNK(m),'parent-type')
for pin in (APP,EXEC,CTRL):require(git('rev-parse',pin+'^{commit}').decode().strip()==pin,'git-pin')
controller={n:git('show',CTRL+':deploy/'+n) for n in MODULES}
preflight=git('show',APP+':backend/scripts/release_preflight.py')
executor=git('show',EXEC+':backend/scripts/migrate.py')
# All validation above precedes the exclusive artifact directory creation.
if not DEST.parent.exists():new_dir(DEST.parent)
new_dir(DEST)
new_dir(DEST/'controller')
for n,data in controller.items():new_file(DEST/'controller'/n,data)
print('Exported 12 exact controller blobs; application not executed.',flush=True)
sys.path.insert(0,str(DEST/'controller'))
import package_backend_release as pack
import first_transition_adapter as adapter
for module in (pack,adapter):require(Path(module.__file__).parent==DEST/'controller','tool-origin')
require(tuple(n for n,_ in adapter.adapter_sources())==MODULES,'source-scope')
require(dict(adapter.adapter_sources())=={n:sha(b) for n,b in controller.items()},'source-hashes')
plan=adapter.prepare(REPO,application_sha=APP,executor_sha=EXEC)
require(plan.executor==executor and plan.preflight==preflight,'plan-pinned-helpers')
require((len(plan.migrations),len(plan.baseline),len(plan.pending),sum(m.concurrent for m in plan.pending))==(129,78,51,8),'plan-shape')
app_files=pack.source_files(REPO,APP)
app_manifest=pack.release_manifest(APP,app_files)
app_path=DEST/f'backend-{APP}.tar.gz'
app_result=pack.build(REPO,APP,app_path)
verify_archive(app_path,{**app_files,'release-manifest.json':app_manifest})
require(app_result['sha256']==sha(app_path.read_bytes()),'package-hash')
new_file(DEST/'application-manifest.json',app_manifest)
new_file(DEST/'application-package.json',encoded(app_result))
print('Backend package verified byte-for-byte against allowlisted Git blobs.',flush=True)
ctrl_contents={'deploy/'+n:b for n,b in controller.items()}
ctrl_manifest=encoded({'commit':CTRL,'files':{n:sha(b) for n,b in sorted(ctrl_contents.items())}})
new_file(DEST/'controller-manifest.json',ctrl_manifest)
ctrl_path=DEST/f'controller-{CTRL}.tar.gz'
ctrl_contents['controller-manifest.json']=ctrl_manifest
archive(ctrl_path,ctrl_contents);verify_archive(ctrl_path,ctrl_contents)
new_dir(DEST/'executor');new_dir(DEST/'executor/backend');new_dir(DEST/'executor/backend/scripts')
new_file(DEST/'executor/backend/scripts/migrate.py',executor)
exec_manifest=encoded({'commit':EXEC,'files':{'backend/scripts/migrate.py':sha(executor)}})
new_file(DEST/'executor-manifest.json',exec_manifest)
exec_path=DEST/f'executor-{EXEC}.tar.gz'
exec_contents={'backend/scripts/migrate.py':executor,'executor-manifest.json':exec_manifest}
archive(exec_path,exec_contents);verify_archive(exec_path,exec_contents)
new_dir(DEST/'preflight');new_dir(DEST/'preflight/backend');new_dir(DEST/'preflight/backend/scripts')
new_file(DEST/'preflight/backend/scripts/release_preflight.py',preflight)
new_file(DEST/'preflight-manifest.json',encoded({'commit':APP,'files':{'backend/scripts/release_preflight.py':sha(preflight)}}))
report=plan.report()
report.update(controller_sha=CTRL,transactional=sum(not m.concurrent for m in plan.pending),
 executor_sha256=sha(executor),application_manifest_sha256=sha(app_manifest),
 baseline_names=list(plan.baseline),adapter_sources=dict(plan.adapter_sources),
 migrations=[{'name':m.name,'sha256':m.sha256,'baseline':m.name in plan.baseline,'concurrent':m.concurrent,'indexes':list(m.indexes)} for m in plan.migrations])
new_file(DEST/'migration-plan.json',encoded(report))
primary=[app_path,ctrl_path,exec_path]
summary={'schema':'igreja12.a4-code-artifacts/1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'pins':{'application':APP,'executor':EXEC,'controller':CTRL},'python':sys.version.split()[0],
 'zlib':zlib.ZLIB_VERSION,'plan_digest':plan.digest,'adapter_sources_digest':report['adapter_sources_digest'],
 'package_manifest_sha256':sha(app_manifest),'preflight_sha256':sha(preflight),'executor_sha256':sha(executor),
 'counts':{'active':129,'baseline':78,'pending':51,'transactional':43,'concurrent':8,'controller_modules':12,'application_files':len(app_files)},
 'artifacts':[{'file':p.name,'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())} for p in primary],
 'production_ready':False,'runtime_operations':False,'images_built':False,'real_data_read':False}
new_file(DEST/'A4-RECEIPT.json',encoded(summary))
files=sorted(p for p in DEST.rglob('*') if p.is_file())
require(all(not p.is_symlink() and stat.S_ISREG(p.lstat().st_mode) for p in files),'artifact-entry-type')
lines=[sha(p.read_bytes())+'  '+str(p.relative_to(DEST)) for p in files]
new_file(DEST/'SHA256SUMS',('\n'.join(lines)+'\n').encode())
# Independent second pass checks every artifact/source/manifest recorded on disk.
for line in (DEST/'SHA256SUMS').read_text().splitlines():
 h,n=line.split('  ',1);require(sha((DEST/n).read_bytes())==h,'final-checksum')
for n,b in controller.items():require((DEST/'controller'/n).read_bytes()==git('show',CTRL+':deploy/'+n),'controller-origin')
require((DEST/'executor/backend/scripts/migrate.py').read_bytes()==git('show',EXEC+':backend/scripts/migrate.py'),'executor-origin')
require((DEST/'preflight/backend/scripts/release_preflight.py').read_bytes()==git('show',APP+':backend/scripts/release_preflight.py'),'preflight-origin')
summary.update(verified_files=len(files),sha256sums_sha256=sha((DEST/'SHA256SUMS').read_bytes()),destination=str(DEST))
print(json.dumps(summary,indent=2),flush=True)
