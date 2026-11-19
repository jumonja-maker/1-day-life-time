from pathlib import Path
import json,os,sys
work=Path(sys.argv[1]);result=work/'smoke_result.json'
if result.exists():
    obj=json.loads(result.read_text())
    summary={k:obj.get(k) for k in ['success','failure','mod_unchanged','sections_equal_after_reopen','start_utc','end_utc']}
    summary['config']={k:obj['config'].get(k) for k in ['minecraft','loader','fabric_api_version','mod_sha256','seed','preset','settings','points']}
    summary['reopened_chunks']=obj.get('reopen',{}).get('chunks',[])
else:summary={'success':False,'failure':'No smoke_result.json; inspect earlier step'}
text=json.dumps(summary,ensure_ascii=False,indent=2)
print(text)
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write('# Native Fabric generation audit\n\n```json\n'+text+'\n```\n')
for name in ['installer.log','first_boot.log','reopen.log']:
    p=work/name
    if p.exists():
        print('\nLOG '+name+' (last 100 lines)')
        print('\n'.join(p.read_text(errors='replace').splitlines()[-100:]))
