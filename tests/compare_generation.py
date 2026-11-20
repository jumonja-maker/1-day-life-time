"""Compare saved FULL chunks by decoded values, not palette or compressed byte order."""
from pathlib import Path
import collections,gzip,hashlib,json,sys
from inspect_saved_chunks import load_chunk,palette_value,block_fields,packed_height

def norm_biome(value):
 if isinstance(value,dict) and '' in value:return norm_biome(value[''])
 return value

def canon_state(value):
 name,properties=block_fields(value)
 return name+('['+','.join(f'{k}={v}' for k,v in sorted(properties.items()))+']' if properties else '')

def digest(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def compare(a,b,points,out):
 out.mkdir(parents=True,exist_ok=True);rows=[];diffs=[];summary=collections.Counter()
 for p in points:
  cx,cz=p['x']//16,p['z']//16;ca,cb=load_chunk(a,cx,cz),load_chunk(b,cx,cz)
  assert ca['Status']==cb['Status']=='minecraft:full',(cx,cz)
  for tag,c in [('forward',ca),('reverse',cb)]:
   (out/f'{tag}_{cx}_{cz}.nbt.json.gz').write_bytes(gzip.compress(json.dumps(c,sort_keys=True).encode(),mtime=0))
  sa={s['Y']:s for s in ca['sections']};sb={s['Y']:s for s in cb['sections']}
  row={'name':p['name'],'area':p.get('area'),'chunk_x':cx,'chunk_z':cz,'blocks':0,'quarts':0,'block_changes':0,'biome_changes':0};hashes={k:hashlib.sha256() for k in ['block_a','block_b','biome_a','biome_b']}
  for sy in sorted(set(sa)|set(sb)):
   for key,count,bits,normalizer in [('block_states',4096,4,canon_state),('biomes',64,1,norm_biome)]:
    aa,bb=sa.get(sy,{}).get(key),sb.get(sy,{}).get(key)
    if aa is None and bb is None:continue
    if aa is None or bb is None:raise ValueError(('Missing section container',cx,sy,cz,key))
    values_a=[normalizer(palette_value(aa,i,bits)) for i in range(count)];values_b=[normalizer(palette_value(bb,i,bits)) for i in range(count)]
    short='block' if key=='block_states' else 'biome';hashes[short+'_a'].update((str(sy)+json.dumps(values_a,separators=(',',':'))).encode());hashes[short+'_b'].update((str(sy)+json.dumps(values_b,separators=(',',':'))).encode())
    row['blocks' if count==4096 else 'quarts']+=count
    for i,(va,vb) in enumerate(zip(values_a,values_b)):
     if va!=vb:
      row[short+'_changes']+=1
      if count==4096:x=cx*16+(i&15);z=cz*16+((i>>4)&15);y=sy*16+(i>>8)
      else:x=cx*16+(i&3)*4;z=cz*16+((i>>2)&3)*4;y=sy*16+(i>>4)*4
      diffs.append({'kind':short,'x':x,'y':y,'z':z,'a':va,'b':vb,'area':p.get('area')})
  row['hashes']={k:v.hexdigest() for k,v in hashes.items()}
  row['heightmaps_equal']=ca.get('Heightmaps')==cb.get('Heightmaps')
  row['structures_equal']=ca.get('structures')==cb.get('structures')
  row['block_entities_equal']=sorted(ca.get('block_entities',[]),key=lambda d:(d.get('x',0),d.get('y',0),d.get('z',0)))==sorted(cb.get('block_entities',[]),key=lambda d:(d.get('x',0),d.get('y',0),d.get('z',0)))
  for k in ['blocks','quarts','block_changes','biome_changes']:summary[k]+=row[k]
  rows.append(row)
 result={'world_a':str(a),'world_b':str(b),'scope':'Original unmodified mod, native FULL chunks; explicit target request order reversed; frozen simulation before target requests; palette/packing differences ignored. Not all internal parallel stage orders are controlled.','total':dict(summary),'chunks':rows,'differences':diffs}
 (out/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result['total']));return result

if __name__=='__main__':
 cfg=json.loads(Path(sys.argv[3]).read_text());compare(Path(sys.argv[1]),Path(sys.argv[2]),cfg['points'],Path(sys.argv[4]))
