#!/usr/bin/env python3
"""Bounded real Fabric server test: new world, native generation, save, reopen.
Standard library only; no mod transformation/adapters or test mods are installed.
Never point --work at an existing world. All listening is bound to 127.0.0.1.
"""
from pathlib import Path
import argparse,collections,gzip,hashlib,json,os,queue,re,shutil,struct,subprocess,threading,time,urllib.request,zipfile,zlib

class NBT:
 def __init__(self,b):self.b=b;self.i=0
 def take(self,n):v=self.b[self.i:self.i+n];self.i+=n;return v
 def number(self,fmt):return struct.unpack('>'+fmt,self.take(struct.calcsize(fmt)))[0]
 def string(self):return self.take(self.number('H')).decode('utf-8')
 def payload(self,t):
  if t in (1,2,3,4,5,6):return self.number({1:'b',2:'h',3:'i',4:'q',5:'f',6:'d'}[t])
  if t==7:return list(self.take(self.number('i')))
  if t==8:return self.string()
  if t==9:
   sub=self.number('B');n=self.number('i');return [self.payload(sub) for _ in range(n)]
  if t==10:
   d={}
   while (k:=self.number('B'))!=0:
    name=self.string();d[name]=self.payload(k)
   return d
  if t in (11,12):return [self.number('i' if t==11 else 'q') for _ in range(self.number('i'))]
  raise ValueError('Unsupported NBT '+str(t))
 def root(self):t=self.number('B');name=self.string();return self.payload(t)

def sha(path,kind='sha256'):return hashlib.new(kind,Path(path).read_bytes()).hexdigest()
def write(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def fetch(item,path,records):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists():
  req=urllib.request.Request(item['url'],headers={'User-Agent':'FreshGenerator-Independent-Audit/1.0'})
  with urllib.request.urlopen(req,timeout=60) as f,path.open('wb') as out:
   while data:=f.read(1024*1024):out.write(data)
 for alg,expect in item['hashes'].items():
  if sha(path,alg)!=expect:raise RuntimeError('Hash mismatch: '+str(path))
 records.append({'url':item['url'],'path':str(path),'bytes':path.stat().st_size,'sha256':sha(path),'verified_hashes':item['hashes']})

def inspect_world(work,points):
 world=work/'world';level=NBT(gzip.decompress((world/'level.dat').read_bytes())).root();data=level.get('Data',level)
 worldgen=data.get('WorldGenSettings')
 if worldgen is None:
  stored=NBT(gzip.decompress((world/'data/minecraft/world_gen_settings.dat').read_bytes())).root();worldgen=stored.get('data',stored)
 region_dir=world/'dimensions/minecraft/overworld/region'
 if not region_dir.exists():region_dir=world/'region'
 result={'data_version':data.get('DataVersion'),'worldgen':worldgen,'region_directory':str(region_dir),'chunks':[]}
 for p in points:
  cx=p['x']//16;cz=p['z']//16;region=region_dir/f'r.{cx//32}.{cz//32}.mca';b=region.read_bytes();j=(cx%32+cz%32*32)*4;entry=int.from_bytes(b[j:j+4],'big');sector=entry>>8
  if not sector:raise RuntimeError('Target chunk not saved: '+p['name'])
  at=sector*4096;length=int.from_bytes(b[at:at+4],'big');compression=b[at+4];payload=b[at+5:at+4+length]
  if compression&128:payload=(region.parent/f'c.{cx}.{cz}.mcc').read_bytes();compression&=127
  if compression==1:payload=gzip.decompress(payload)
  elif compression==2:payload=zlib.decompress(payload)
  elif compression!=3:raise RuntimeError('Unsupported chunk compression '+str(compression))
  raw=NBT(payload).root();chunk=raw.get('Level',raw);status=chunk.get('Status',chunk.get('status'))
  if status not in ('minecraft:full','full'):raise RuntimeError('Chunk not FULL: '+str(status))
  sections=chunk.get('sections',chunk.get('Sections',[]));biomes=sorted({x for sec in sections for x in sec.get('biomes',{}).get('palette',[])})
  result['chunks'].append({'name':p['name'],'x':p['x'],'z':p['z'],'chunk_x':cx,'chunk_z':cz,'status':status,'data_version':chunk.get('DataVersion'),'last_update':chunk.get('LastUpdate'),'section_count':len(sections),'biome_palette':biomes,'sections_sha256':hashlib.sha256(json.dumps(sections,sort_keys=True).encode()).hexdigest()})
 return result

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--java',default='java');ap.add_argument('--mod',required=True,type=Path);ap.add_argument('--work',required=True,type=Path);ap.add_argument('--config',type=Path,default=Path(__file__).with_name('pinned_config.json'));ap.add_argument('--prepared',action='store_true');ap.add_argument('--single-boot',action='store_true',help='Generate and save only; no reopen');ap.add_argument('--freeze-simulation',action='store_true',help='Freeze native game simulation before target requests');ap.add_argument('--existing-audit',action='store_true',help='Add targets only to a successfully completed world created by this audit');ap.add_argument('--trust-store',type=Path);ap.add_argument('--max-seconds',type=int,default=900);ap.add_argument('--port',type=int,default=25595);args=ap.parse_args()
 cfg=json.loads(args.config.read_text());work=args.work.resolve();mod=args.mod.resolve();work.mkdir(parents=True,exist_ok=True)
 if args.existing_audit:
  previous=json.loads((work/'smoke_result.json').read_text())
  if not previous.get('success') or previous['config']['mod_sha256']!=cfg['mod_sha256'] or previous['config']['seed']!=cfg['seed'] or previous['config']['settings']!=cfg['settings']:raise RuntimeError('Existing audit identity/success mismatch')
 elif (work/'world').exists() or (work/'eula.txt').exists():raise RuntimeError('Refusing existing/tested world directory; use a fresh --work')
 if sha(mod)!=cfg['mod_sha256']:raise RuntimeError('Wrong input mod SHA256')
 if not args.prepared and not args.existing_audit and any(work.iterdir()):raise RuntimeError('Bootstrap requires an empty --work')
 result_path=work/('extra_smoke_result.json' if args.existing_audit else 'smoke_result.json')
 events=[];downloads=[];result={'scope':'Unmodified mod, real dedicated Fabric server, native FULL chunks, save and reopen; no player/visual multiplayer test.','config':cfg,'start_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'success':False,'events':events,'downloads':downloads};deadline=time.monotonic()+args.max_seconds;proc=None;active_log=None
 jvmtrust=['-Djavax.net.ssl.trustStore='+str(args.trust_store)] if args.trust_store else []
 def event(kind,**kw):events.append({'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'kind':kind,**kw});write(result_path,result)
 try:
  if not args.prepared and not args.existing_audit:
   fetch(cfg['server'],work/'server.jar',downloads);fetch(cfg['installer'],work/'installer.jar',downloads);fetch(cfg['fabric_api'],work/'mods'/cfg['fabric_api']['filename'],downloads)
   command=[args.java,'-Xmx512m',*jvmtrust,'-jar',str(work/'installer.jar'),'server','-mcversion',cfg['minecraft'],'-loader',cfg['loader'],'-dir',str(work)]
   with (work/'installer.log').open('w') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=min(180,max(1,deadline-time.monotonic())))
   event('installer',argv=command,exit=r.returncode)
   if r.returncode:raise RuntimeError('Fabric installer failed; inspect installer.log')
  if sha(work/'server.jar','sha1')!=cfg['server']['hashes']['sha1']:raise RuntimeError('Prepared Minecraft hash mismatch')
  api=work/'mods'/cfg['fabric_api']['filename']
  for alg,h in cfg['fabric_api']['hashes'].items():
   if sha(api,alg)!=h:raise RuntimeError('Prepared Fabric API mismatch')
  profile=cfg['launcher_profile']
  for lib in profile['libraries']:
   group,artifact,version=lib['name'].split(':');rel=Path(group.replace('.','/'))/artifact/version/f'{artifact}-{version}.jar';path=work/'libraries'/rel
   if not path.exists():raise RuntimeError('Missing installed loader library '+str(rel))
   for alg in ['sha256','sha1','sha512']:
    if alg in lib and sha(path,alg)!=lib[alg]:raise RuntimeError('Loader library mismatch '+str(rel))
   event('runtime_library',name=lib['name'],sha256=sha(path),bytes=path.stat().st_size)
  if args.existing_audit:
   if sha(work/'mods'/'freshgenerator-audited.jar')!=cfg['mod_sha256']:raise RuntimeError('Existing installed mod mismatch')
  else:
   shutil.copyfile(mod,work/'mods'/'freshgenerator-audited.jar')
   (work/'eula.txt').write_text('eula=true\n')
  props={'server-ip':'127.0.0.1','server-port':str(args.port),'online-mode':'false','enforce-secure-profile':'false','white-list':'true','enforce-whitelist':'true','enable-rcon':'false','enable-query':'false','enable-status':'false','max-players':'1','level-name':'world','level-seed':str(cfg['seed']),'level-type':cfg['preset'],'view-distance':'2','simulation-distance':'2','max-tick-time':'120000','pause-when-empty-seconds':'0','sync-chunk-writes':'true','generate-structures':'true','difficulty':'peaceful','motd':'FreshGenerator isolated generation audit'}
  if not args.existing_audit:
   (work/'server.properties').write_text(''.join(k+'='+v+'\n' for k,v in props.items()));event('created_fresh_world_config',properties=props)
  else:event('continuing_verified_audit_world',original_result=str(work/'smoke_result.json'))
  for phase in (['first_boot'] if args.single_boot else ['first_boot','reopen']):
   logpath=work/(('extra_' if args.existing_audit else '')+phase+'.log');active_log=logpath.open('w',buffering=1);q=queue.Queue();lines=[]
   command=[args.java,'-Xms512m','-Xmx2g','-XX:ActiveProcessorCount=2','-XX:-UsePerfData',*jvmtrust,'-jar',str(work/'fabric-server-launch.jar'),'nogui']
   proc=subprocess.Popen(command,cwd=work,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
   def reader():
    for line in proc.stdout:
     active_log.write(line);lines.append(line);q.put(line)
   thread=threading.Thread(target=reader,daemon=True);thread.start();event('start',phase=phase,argv=command,pid=proc.pid)
   def send(cmd):
    if proc.poll() is not None:raise RuntimeError('Server exited before command: '+cmd)
    proc.stdin.write(cmd+'\n');proc.stdin.flush();event('command',phase=phase,text=cmd)
   def wait_match(pattern,timeout):
    end=min(deadline,time.monotonic()+timeout);rx=re.compile(pattern)
    while time.monotonic()<end:
     try:line=q.get(timeout=.5)
     except queue.Empty:
      if proc.poll() is not None:raise RuntimeError('Server exited '+str(proc.returncode)+' waiting for '+pattern)
      continue
     if rx.search(line):return line.strip()
    raise TimeoutError('Timed out waiting for '+pattern)
   ready=wait_match(r'Done \([0-9.,]+s\)!',min(360,args.max_seconds));event('ready',phase=phase,line=ready)
   send('seed');send('datapack list enabled')
   if args.freeze_simulation:
    send('tick freeze');wait_match(r'(frozen|Frozen)',10);event('simulation_frozen',phase=phase)
    send('weather clear 1000000');wait_match(r'(clear weather|weather to clear)',10)
   for index,p in enumerate(cfg['points']):
    token='FG_AUDIT_LOADED_'+phase+'_'+str(index);send(f'forceload add {p["x"]} {p["z"]}')
    loaded=False;end=min(deadline,time.monotonic()+120)
    while time.monotonic()<end:
     send(f'execute if loaded {p["x"]} 64 {p["z"]} run say {token}')
     try:line=wait_match(token,4);loaded=True;break
     except TimeoutError:pass
    if not loaded:raise TimeoutError('Target did not become loaded '+p['name'])
    event('target_loaded',phase=phase,name=p['name'],line=line)
    send('save-all flush');wait_match(r'Saved the game',60)
    send(f'forceload remove {p["x"]} {p["z"]}')
   send('save-all flush');wait_match(r'Saved the game',60);send('stop')
   try:code=proc.wait(timeout=min(90,max(1,deadline-time.monotonic())))
   except subprocess.TimeoutExpired:proc.terminate();raise TimeoutError('Server did not stop gracefully')
   thread.join(timeout=3);active_log.close();active_log=None;event('stopped',phase=phase,exit=code)
   if code:raise RuntimeError('Nonzero exit after stop: '+str(code))
   proc=None;saved=inspect_world(work,cfg['points']);result[phase]=saved
   gen=saved['worldgen'];settings=gen['dimensions']['minecraft:overworld']['generator']['settings']
   if settings!=cfg['settings']:raise RuntimeError('Wrong actual generator settings '+str(settings))
   event('saved_world_verified',phase=phase,settings=settings,targets=len(saved['chunks']))
  result['sections_equal_after_reopen']=None if args.single_boot else {a['name']:a['sections_sha256']==b['sections_sha256'] for a,b in zip(result['first_boot']['chunks'],result['reopen']['chunks'])}
  if args.single_boot:result['scope']='Unmodified mod, native FULL chunks, single fresh boot and save; no reopen.'
  result['simulation_frozen']=args.freeze_simulation
  result['mod_unchanged']=sha(mod)==cfg['mod_sha256'] and sha(work/'mods'/'freshgenerator-audited.jar')==cfg['mod_sha256'];result['success']=True;event('passed')
 except BaseException as exc:
  result['failure']={'type':type(exc).__name__,'message':str(exc)};event('failed',**result['failure'])
 finally:
  if proc is not None and proc.poll() is None:
   try:proc.stdin.write('stop\n');proc.stdin.flush();proc.wait(timeout=15)
   except Exception:
    proc.terminate()
    try:proc.wait(timeout=10)
    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=10)
  if active_log:active_log.close()
  result['end_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime());write(result_path,result);print(json.dumps({'success':result['success'],'result':str(result_path),'failure':result.get('failure')},ensure_ascii=False))
 return 0 if result['success'] else 1
if __name__=='__main__':raise SystemExit(main())

