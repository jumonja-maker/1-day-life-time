#!/usr/bin/env python3
"""Read saved 26.3 region chunks, export requested columns after native generation.
No world mutation. Quart palette cells are explicitly not BiomeManager lookup.
"""
from pathlib import Path
import argparse,csv,gzip,json,math,zlib
from fabric_smoke import NBT

def load_chunk(world,cx,cz):
 region=world/'dimensions/minecraft/overworld/region'/f'r.{cx//32}.{cz//32}.mca'
 if not region.exists():region=world/'region'/region.name
 b=region.read_bytes();index=(cx%32+cz%32*32)*4;sector=int.from_bytes(b[index:index+4],'big')>>8
 if not sector:raise ValueError('Chunk absent')
 at=sector*4096;length=int.from_bytes(b[at:at+4],'big');kind=b[at+4];payload=b[at+5:at+4+length]
 if kind&128:payload=(region.parent/f'c.{cx}.{cz}.mcc').read_bytes();kind&=127
 if kind==1:payload=gzip.decompress(payload)
 elif kind==2:payload=zlib.decompress(payload)
 elif kind!=3:raise ValueError('Compression '+str(kind))
 root=NBT(payload).root();return root.get('Level',root)
def palette_value(container,index,minbits):
 palette=container['palette'];packed=container.get('data')
 if not packed:return palette[0]
 bits=max(minbits,(len(palette)-1).bit_length());perlong=64//bits;word=packed[index//perlong] & ((1<<64)-1);position=(word>>((index%perlong)*bits))&((1<<bits)-1);return palette[position]
def packed_height(data,index,bits=9):
 perlong=64//bits;word=data[index//perlong]&((1<<64)-1);return (word>>((index%perlong)*bits))&((1<<bits)-1)
def block_fields(state):
 # 26.3 palettes use either an identifier string or id/properties compounds;
 # heterogeneous NBT lists wrap primitive entries in a compound with key "".
 if isinstance(state,str):return state,{}
 if '' in state:return block_fields(state[''])
 return state.get('id',state.get('Name')),state.get('properties',state.get('Properties',{}))
def main():
 a=argparse.ArgumentParser();a.add_argument('--world',type=Path,required=True);a.add_argument('--config',type=Path,required=True);a.add_argument('--output',type=Path,required=True);args=a.parse_args();args.output.mkdir(parents=True,exist_ok=True);cfg=json.loads(args.config.read_text());rows=[];summ=[];quarts=[]
 for p in cfg['points']:
  x,z=p['x'],p['z'];chunk=load_chunk(args.world,x//16,z//16);sections={int(s['Y']):s for s in chunk.get('sections',[])};localx=x%16;localz=z%16;cells=[]
  for y in range(-64,320):
   s=sections.get(y//16)
   if not s or 'block_states' not in s:block={'Name':'minecraft:air'};biome='unknown'
   else:
    block=palette_value(s['block_states'],((y%16)<<8)|(localz<<4)|localx,4)
    biome=palette_value(s['biomes'],(((y%16)//4)<<4)|((localz//4)<<2)|(localx//4),1)
   name,properties=block_fields(block)
   row={'point':p['name'],'seed':cfg['seed'],'x':x,'y':y,'z':z,'block':name,'properties':json.dumps(properties,sort_keys=True),'quart_palette_biome':biome};rows.append(row);cells.append(row)
  for sy,s in sections.items():
   for qy in range(4):
    for qz in range(4):
     for qx in range(4):
      biome=palette_value(s['biomes'],qy*16+qz*4+qx,1)
      quarts.append({'point':p['name'],'seed':cfg['seed'],'chunk_x':x//16,'chunk_z':z//16,'quart_x':x//16*4+qx,'quart_y':sy*4+qy,'quart_z':z//16*4+qz,'sample_block_x':(x//16*4+qx)*4,'sample_block_y':(sy*4+qy)*4,'sample_block_z':(z//16*4+qz)*4,'biome':biome})
  heights={k:packed_height(v,localz*16+localx)-64-1 for k,v in chunk.get('Heightmaps',{}).items()};summ.append({'name':p['name'],'seed':cfg['seed'],'x':x,'z':z,'chunk_status':chunk.get('Status'),'native_heightmap_top_block_y':heights,'solid_or_fluid_at_surface_band':[r for r in cells if 45<=r['y']<=75]})
 with (args.output/'target_columns.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
 with (args.output/'saved_quart_biomes.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=quarts[0].keys());w.writeheader();w.writerows(quarts)
 (args.output/'target_columns_summary.json').write_text(json.dumps(summ,ensure_ascii=False,indent=2))
 print(json.dumps([{k:v for k,v in r.items() if k!='solid_or_fluid_at_surface_band'} for r in summ],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
