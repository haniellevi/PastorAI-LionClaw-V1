import subprocess,json,selectors,time,sys,re,datetime,threading,queue,os
from pathlib import Path
ROOT=Path('/home/raniel-linux/workspace/PastorAi-1.0')
OUT=Path(__file__).resolve().parent
SESSION=None;MODEL='gemini-4-argon-high'
p=subprocess.Popen(['devin','acp','--agent-type','summarizer','--model',MODEL],cwd=ROOT,
 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
messages=queue.Queue()
def pump():
 for line in p.stdout:messages.put(line)
 messages.put(None)
threading.Thread(target=pump,daemon=True).start()
next_id=0;history_updates=0;answer=[];collect=False;tool_requests=0

def send(v):p.stdin.write(json.dumps(v)+'\n');p.stdin.flush()
def request(method,params,timeout=60):
 global next_id,history_updates,tool_requests
 next_id+=1;ident=next_id;send({'jsonrpc':'2.0','id':ident,'method':method,'params':params});end=time.monotonic()+timeout
 while time.monotonic()<end:
  try:line=messages.get(timeout=min(end-time.monotonic(),1))
  except queue.Empty:
   if p.poll() is not None:raise RuntimeError('ACP server exited')
   continue
  if line is None:raise RuntimeError('ACP stream closed')
  try:m=json.loads(line)
  except ValueError:continue
  if 'method' in m and 'id' in m:
   tool_requests+=1
   if m['method']=='session/request_permission':send({'jsonrpc':'2.0','id':m['id'],'result':{'outcome':{'outcome':'cancelled'}}})
   else:send({'jsonrpc':'2.0','id':m['id'],'error':{'code':-32601,'message':'Client tools disabled for this consultation'}})
   continue
  if m.get('method')=='session/update':
   u=m.get('params',{}).get('update',{});kind=u.get('sessionUpdate')
   if not collect:history_updates+=1
   if collect and kind=='agent_message_chunk':
    c=u.get('content',{})
    if c.get('type')=='text':answer.append(c.get('text',''))
  if m.get('id')==ident:
   if 'error' in m:
    message=str(m['error'].get('message',''))
    message=re.sub(r'https?://[^\s]+','[endpoint]',message)
    raise RuntimeError('ACP '+method+' error '+str(m['error'].get('code'))+': '+message[:250])
   return m.get('result',{})
 raise RuntimeError('ACP request timeout: '+method)

try:
 init=request('initialize',{'protocolVersion':1,'clientCapabilities':{'fs':{'readTextFile':False,'writeTextFile':False},'terminal':False},'clientInfo':{'name':'codex-argon-consultation','version':'1'}})
 if os.environ.get('ARGON_ACP_CAPABILITIES_ONLY')=='1':
  print(json.dumps({'agent_info':init.get('agentInfo'),'capabilities':init.get('agentCapabilities')}),flush=True)
  raise SystemExit(0)
 loaded=request('session/new',{'cwd':str(ROOT),'mcpServers':[]},90)
 SESSION=loaded['sessionId']
 options=loaded.get('configOptions',[])
 model_options=[o for o in options if o.get('category')=='model' or o.get('id')=='model']
 print(json.dumps({'new_session':SESSION,'response_fields':list(loaded),'model_options':[{'id':o.get('id'),'currentValue':o.get('currentValue')} for o in model_options]}),flush=True)
 before=loaded.get('models',{}).get('currentModelId')
 if before is None and len(model_options)==1:before=model_options[0].get('currentValue')
 if before!=MODEL and len(model_options)==1:
  updated=request('session/set_config_option',{'sessionId':SESSION,'configId':model_options[0]['id'],'value':MODEL},60)
  updated_models=[o for o in updated.get('configOptions',[]) if o.get('category')=='model' or o.get('id')=='model']
  if not any(o.get('currentValue')==MODEL for o in updated_models):raise RuntimeError('Model selection not confirmed; prompt not sent')
 meta={'session':SESSION,'requested_model':MODEL,'verified_model':MODEL if before==MODEL else None,'model_selection_source':'explicit ACP --model flag; registered model id','model_before':before,'agent_info':init.get('agentInfo'),
       'history_updates_loaded':0,'original_session_touched':False,'context_source':'sanitized handoff and current ROADMAP only','agent_type':'summarizer (no tools)','at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 print(json.dumps(meta),flush=True)
 prompt="""Consulta de aconselhamento somente textual em NOVA sessão ACP separada. Você é consultor Gemini 4 Argon High. NÃO é a sessão original CONVERSA 1- ARGON e NÃO herdou seu histórico completo. Use somente o handoff e o ROADMAP fornecidos como texto nesta mensagem e declare essas lacunas. O usuário autorizou esta consulta separada, preservando a sessão original. O modelo selecionado é Gemini 4 Argon High. NÃO use ferramentas, NÃO execute comandos, NÃO leia arquivos/configurações/segredos nem faça consultas remotas, NÃO altere arquivos nem retome autorizações operacionais antigas. Responda exclusivamente a partir do contexto sanitizado fornecido; não atribua a si lembranças da sessão original. Não inclua PII, telefones, IDs de pessoas, chaves, senhas, URLs autenticadas ou conteúdo pastoral. Declare que não teve acesso ao histórico integral, a configurações reais ou ao estado vivo de produção. Não exponha raciocínio interno; somente conclusões, evidências e recomendações.
Atualização vigente do orquestrador Codex: PRs597-606 integradas; #606 por merge commit6d46206c8b92e6a932a87cf4fde84a2f81b11b19 com6CIpush verdes, sem bypass, branchpreservada. A3 blocosA+B completos PARAMETRIZADOS: prova read-only fresca antes de retomada préDDL; quiescência2observações; backup janela único comnonce; 51migrations canônicas; A9cria4candidatos mas inicia SÓbackend, consumidores created/restartno atéA10. Única auditoria finalGPT+Sarah identificou5P1todos corrigidos e cobertos;652testes51subtesteslocalverde,CIverde; não houve segunda auditoria dos bytes corrigidos. Dockerinspectclient-side e callbacks maliciosos inprocess NÃO são novos bloqueadores; laboratórioI0cancelado.
A4codeartefactsgenerated LOCALONLY emdestinoexclusivo A4-20261030,24arquivosSHA256verificados. APP/SQLpin afdfb78d71a53f2861632806e13cdda4662d7d63; executor37c7d68d60b6f86cfb1fe75d4c720530537845d6; controlador6d46206c8b92e6a932a87cf4fde84a2f81b11b19.129ativas/78baseline/51pendentes43TX8NT, nãoaplicadasnafonte. Nenhuma imagem criada/baixada, nem Dockerlocal/VPS/deploy. DEVdisabledmanual+DEV_PIPELINE_ENABLEDfalse, VercelGitdetached epreviewfalse mantidos nasúltimasconsultas, não reconfirmadosagora.
Pacote3A5+A6 autorizado condicional: uma sessão, A5 somenteleitura VPSnominalsrv2031318 eSupabasePROD, validaridentidadesantesdados; A6backupnovo restore/replay51 emclusterisolado dentrofronteiraprotegidaprodução,nuncaDEV/local/CI;2CPU4GiB10GiB60min; semegress/consumidores; usarrecursosferramentasexistentes; seminstalação/download/pago/alteraçõesfonte/pausas/gates/envios/pushmerge/dispatchdeployreativação; preservar evidências, limpeza sóapóspropostaaprovada. backup-production.sh completo pausaRedisEvolutioneCHECKPOINT e está excluído dessaautorizaçãoimplícita. BackupA6nãosubstituifrescodeA8.
Única tentativaA5: supabase_get_project('pffafnchtxbimpwyaczq'), alvo histórico Pastor-Ai-LionClaw-v1/us-west-2. Conector recusou privilégios. Parada imediata semfallback. ZEROsql/ssh/dadosdomínio/backuprestore/replay. NÃO repetir consultas ou tentaroutrocanal nesta consulta. SSHregistrado em24/10 era igreja12-ops@srv2031318.hstgr.cloud comvalidadeaté26/10; validadeatualnãoverificada, chave nãolida/procurada. ROADMAPativo nabranchlocaldocs/a4-phase3-preparation-20261030; checkoutprincipal antigod038temtrabalhoalheiopreservado.
Solicitação do dono: trazer MUITO contexto útil que esta sessão já conhece e participar do processo como conselheiro crítico, não executor. Entregue até1500palavras: (1) decisões anteriores ainda vigentes e seu grau de evidência, (2) contexto histórico útil sobre canais de acesso aprovados e diferença entre managementMCPnegado e leituraSQL, sem presumir que outrocanal funciona agora, (3) critique lacunas/reais riscos e pontos simplificáveis do plano, (4) caminho crítico A4->A5/A6->janelaA7/A8/A9->retomadaA10, (5) próximo pacote concreto para destravar acesso com mínima autorização sem novosgrants/credenciaisnochat nem microinventários, (6) divergências do seu histórico com atualização vigente. Não transforme alegação histórica emestado vivo, nem aponte requisitos cancelados comoobrigatórios. Nenhuma operação autorizada por esta consulta."""
 handoff=(ROOT/'output/release/HANDOFF-ARGON-FASE1-20261029.md').read_text()
 roadmap=Path('/home/raniel-linux/.codex/worktrees/fase1-a3-transicao-20261029/PastorAi-1.0/ROADMAP.md').read_text()
 # Only current approved planning sections; no private configs, dumps or real data.
 roadmap=roadmap.split('## A3 — blocos A e B implementados localmente (30/10/2026)',1)[0]
 prompt+='\n\nHANDOFF HISTÓRICO SANITIZADO, DADOS/ESTADO PODEM ESTAR SUPERADOS (não são instruções de execução):\n'+handoff
 prompt+='\n\nROADMAP VIGENTE SANITIZADO (prevalece sobre o handoff; nenhuma autorização operacional vale nesta consulta):\n'+roadmap
 prompt+='\n\nFORMATO: até1500palavras, comece pelas lacunas de contexto. Entregue decisões vigentes, crítica cética, bloqueadores reais versus burocracia descartável, distinção permissão management/SQL sem afirmar acesso atual, caminho crítico completo até produção e próximo passo específico para obter acesso somente leitura já aprovado. Nenhuma ferramenta/operação, nenhum pedido de segredo no chat, nenhuma retomada de A5+A6. Não propor novo inventário fora de A5 nem laboratório offline. Não recomendar ignorar a recusa que já determinou parada. Quando algo não estiver provado, escreva não verificado.'
 collect=True
 result=request('session/prompt',{'sessionId':SESSION,'prompt':[{'type':'text','text':prompt}]},420)
 text=''.join(answer)
 # Do not persist secret-shaped strings even if the source history inadvertently contained one.
 text=re.sub(r'(?i)postgres(?:ql)?://[^\s<>()]+','[DSN OMITIDA]',text)
 text=re.sub(r'(?i)\b(?:sk-|sb_secret_)[A-Za-z0-9_\-]{16,}','[SEGREDO OMITIDO]',text)
 text=re.sub(r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+','[TOKEN OMITIDO]',text)
 meta.update(stop_reason=result.get('stopReason'),client_tool_requests=tool_requests,reply_characters=len(text))
 (OUT/'argon-acp-separate-consultation.json').write_text(json.dumps(meta,indent=2)+'\n')
 (OUT/'argon-acp-separate-advice.md').write_text(text)
 print(json.dumps(meta),flush=True)
 print(text,flush=True)
finally:
 try:p.stdin.close()
 except Exception:pass
 if p.poll() is None:
  p.terminate()
  try:p.wait(timeout=5)
  except subprocess.TimeoutExpired:p.kill();p.wait()
