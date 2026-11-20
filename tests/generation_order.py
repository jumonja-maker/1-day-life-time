"""Two native Fabric worlds, reversed target request order, decoded comparison.
The game simulation is frozen before target requests, so ordinary grass death,
weather and crop ticks cannot be mistaken for generation-order effects.
Native asynchronous internal work ordering is not forced by this script.
"""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys
from compare_generation import compare

def clone_runtime(source,dest):
 dest.mkdir(parents=True)
 for name in ['server.jar','fabric-server-launch.jar']:
  shutil.copy2(source/name,dest/name)
 shutil.copytree(source/'libraries',dest/'libraries')
 shutil.copytree(source/'mods',dest/'mods')

def main():
 p=argparse.ArgumentParser();p.add_argument('--java',default='java');p.add_argument('--mod',required=True,type=Path);p.add_argument('--work',required=True,type=Path);p.add_argument('--config',type=Path,default=Path(__file__).with_name('pinned_config.json'));p.add_argument('--prepared-base',type=Path);p.add_argument('--trust-store',type=Path);p.add_argument('--port',default=25598,type=int);p.add_argument('--max-seconds',default=900,type=int);a=p.parse_args()
 work=a.work.resolve()
 if work.exists() and any(work.iterdir()):raise RuntimeError('Order audit requires a new empty --work directory')
 work.mkdir(parents=True,exist_ok=True);cfg=json.loads(a.config.read_text());points=[]
 for area,x,z in [('dry_tie',337280,256046),('marine_thermal_edge',-286865,22820)]:
  cx,cz=x//16,z//16
  for dz in [-1,0,1]:
   for dx in [-1,0,1]:points.append({'name':f'{area}_{dx}_{dz}','x':(cx+dx)*16,'z':(cz+dz)*16,'area':area})
 outcomes={}
 try:
  for direction,targets in [('forward',points),('reverse',list(reversed(points)))]:
   case={**cfg,'seed':0,'points':targets};conf=work/f'{direction}_config.json';conf.write_text(json.dumps(case,indent=2));target=work/direction;prepared=False
   if direction=='reverse':clone_runtime(work/'forward',target);prepared=True
   elif a.prepared_base:clone_runtime(a.prepared_base.resolve(),target);prepared=True
   command=[sys.executable,str(Path(__file__).with_name('fabric_smoke.py')),'--java',a.java,'--mod',str(a.mod.resolve()),'--work',str(target),'--config',str(conf),'--max-seconds',str(a.max_seconds),'--port',str(a.port),'--single-boot','--freeze-simulation']
   if prepared:command.append('--prepared')
   if a.trust_store:command+=['--trust-store',str(a.trust_store.resolve())]
   subprocess.run(command,check=True)
   result=json.loads((target/'smoke_result.json').read_text())
   outcomes[direction]={'success':result['success'],'mod_unchanged':result['mod_unchanged'],'simulation_frozen':result['simulation_frozen'],'settings':result['first_boot']['worldgen']['dimensions']['minecraft:overworld']['generator']['settings'],'chunks':result['first_boot']['chunks']}
  result=compare(work/'forward/world',work/'reverse/world',points,work/'evidence')
  success=result['total']['block_changes']==0 and result['total']['biome_changes']==0 and all(c['heightmaps_equal'] and c['structures_equal'] and c['block_entities_equal'] for c in result['chunks'])
  summary={'success':success,'scope':result['scope'],'total':result['total'],'worlds':outcomes,'chunks':result['chunks'],'first_differences':result['differences'][:50]}
 except Exception as exc:
  summary={'success':False,'failure':{'type':type(exc).__name__,'message':str(exc)},'worlds':outcomes}
 (work/'order_result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));encoded=json.dumps(summary,ensure_ascii=False,separators=(',',':'));print('ORDER_RESULT '+encoded)
 if os.environ.get('GITHUB_STEP_SUMMARY'):
  with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write('# Native generation order audit\n\n```json\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n```\n')
 for direction in ['forward','reverse']:
  for filename in ['installer.log','first_boot.log']:
   log=work/direction/filename
   if log.exists():print('LOG '+direction+'/'+filename+'\n'+'\n'.join(log.read_text(errors='replace').splitlines()[-35:]))
 return 0 if summary['success'] else 1

if __name__=='__main__':raise SystemExit(main())
