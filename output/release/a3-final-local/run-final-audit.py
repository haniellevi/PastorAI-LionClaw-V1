from pathlib import Path
import subprocess,concurrent.futures,json,hashlib,datetime
root=Path(__file__).resolve().parents[3]
out=Path(__file__).resolve().parent
paths=['deploy/first_transition_host_driver.py','deploy/first_transition_database.py','deploy/first_transition_orchestrator.py','deploy/first_transition_candidate.py','deploy/first_transition_host_contract.py','deploy/first_transition_host_transport.py','deploy/initial_transition_files.py','deploy/package_backend_release.py','deploy/first_transition_adapter.py','deploy/first-transition.example.json','deploy/tests/test_first_transition_database.py','deploy/tests/test_first_transition_orchestrator.py','deploy/tests/test_first_transition_host_driver.py']
files={p:(root/p).read_text() for p in paths}
prompt="""This is the ONE and ONLY independent parallel final audit of completed LOCAL A3 blocks A+B, not authorization for any operation. You are a skeptical reviewer. Use only supplied bytes, NO tools/commands/network/edits. Identify concrete P0/P1 real bugs (functional failure, loss of queue/data, secret/PII leak, unsafe DDL/production sequencing), not malicious in-process callbacks, Docker client-side inspect trust or absence of PROD identifiers. User explicitly says absent real bindings/config are Phase3 inputs, not local-code blockers; injected config must fail closed when missing. Review integrated logic not just fixture green. P2 maximum3 short lines and NO extra framework/proposals. Return GO/NO-GO for local candidate, P0/P1 count with precise reproduction and location; maximum400words. If unsure distinguish from demonstrated issue. Do not demand real execution.
REQUIREMENTS: preserve SQL APPLICATION_SHA afdfb78d71a53f2861632806e13cdda4662d7d63,EXECUTOR_SHA37c7d68d60b6f86cfb1fe75d4c720530537845d6 and local-only adapter guards. Fresh READ ONLY ledger identity/baseline proof before EVERY legacy resume start/restartalways/open-ingress effect, no legacy afterDDLintent marker. Two bounded consecutive fresh observations: both ingressesblocked,4legacyexit0restartno,zero writingsessions+leases; backup+restore+clone receipt verified beforemarker. Canonical pinned migrate.py 51 migrations43TX8NT sequential firstfailure stop, no SQL replacement/no retry ambiguous. DBidentity/visibility rechecked accepting eachmigration. Release_root/SHA exclusive exact package + release-topology.json. A9 create4closedgates restartno without implicitdependency startups, start ONLYbackend,health/ready requiredhealthy and expected workerabsence/degraded okay. Consumers created/neverstarted/StartedAtunchanged/restartno acrosssmoke; oldlegacyoff/supportuntouched/ingressblocked. Objective partial recovery, neverautoUndo norrestoreoverprod. NoA10implicit. All runtime operations only simulated in tests. Inventory real exclusivelyPhase3 A5 alongside A6; noSSHdata needed now. No commit/push/etc authorized. Local docs/results show scope, not environment truth.
"""
for p,s in files.items():prompt+='\nFILE '+p+'\n'+s
prompt+='\nCURRENT ROADMAP TOP\n'+'\n'.join((root/'ROADMAP.md').read_text().splitlines()[:80])
prompt+='\nTRACKED DIFF\n'+subprocess.check_output(['git','diff'],cwd=root,text=True)
prompt+='\nVALIDATION LOG\n'+(out/'acceptance.log').read_text()[-5000:]
(out/'audit-source-hashes.json').write_text(json.dumps({p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},indent=2)+'\n')
cmd1=['/home/raniel-linux/.local/bin/codex','exec','--ignore-user-config','--ephemeral','-m','gpt-6.1-sol','-c','model_reasoning_effort="high"','-c','mcp_servers={}','--sandbox','read-only','-C',str(root),'-']
cmd2=['/home/raniel-linux/.local/bin/claude-ai','-p','--model','claude-opus-5-5','--effort','high','--tools','','--strict-mcp-config','--setting-sources','','--settings','{"disableAllHooks":true}','--no-session-persistence','--output-format','json']
def review(name,cmd):
 try:
  p=subprocess.run(cmd,input=prompt,cwd=root,text=True,capture_output=True,timeout=600)
  (out/(name+'.stdout')).write_text(p.stdout);(out/(name+'.stderr')).write_text(p.stderr)
  result={'reviewer':name,'returncode':p.returncode,'at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 except subprocess.TimeoutExpired:
  result={'reviewer':name,'timeout':True}
 print(json.dumps(result),flush=True)
with concurrent.futures.ThreadPoolExecutor(2) as pool:
 fs=[pool.submit(review,'gpt-final-audit',cmd1),pool.submit(review,'sarah-final-audit',cmd2)]
 for f in fs:f.result()
