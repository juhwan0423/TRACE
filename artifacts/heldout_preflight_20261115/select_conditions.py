"""Deterministic geometric selection of held-out placements (no model/detector outputs).
Rule fixed before any policy inference:
 answerable: W/E family; per posture a rotation whose useful-view (west for W, entrance for E)
   evaluator body pixels >=5000, fixed <1000, every other body view <1000.
 rotation: standing cycle [s90,s180,sm90], lying cycle [l90,l0,l180,lm90] starting at placement index.
 unanswerable: O family, zero pixels in all 3 body views + fixed, for all tested rotations.
 spread: farthest-point sampling from prior positions; 12 W, 12 E, 6 O.
 cohorts: seed 20261115 shuffle within family, round-robin into 3 cohorts (4W+4E+2O each)."""
import json,math,random
import numpy as np
from PIL import Image
from collections import defaultdict
from pathlib import Path
OUT=Path(__file__).resolve().parent
prior=[(-5.15,.32),(-5.35,.32),(-5.15,.15),(-5.35,.15),(.15,1.0),(.45,.65),(.3,1.3),(.6,1.0),(3.4,1.2),(3.4,2.1),(-5.3,.2),(-3,2.1),(3,1.5)]
P=defaultdict(lambda:defaultdict(dict));pos={}
for tag in ('phaseB','phaseB2_off','phaseB3_e'):
 for v in ('entrance','west','door'):
  for r in json.loads((OUT/f'{tag}_{v}.json').read_text()):
   P[r['name']][r['rot_key']][v]=r['pixels']['body'];P[r['name']][r['rot_key']]['fixed']=r['pixels']['fixed'];P[r['name']][r['rot_key']]['cap_'+v]=r['capture']
cands={c['name']:c for f in ('render_candidates.json','render_candidates_off2.json','render_candidates_e3.json') for c in json.loads((OUT/f).read_text())}
def eligible(name,rk):
 p=P[name][rk];fam=name[0];u={'W':'west','E':'entrance'}[fam]
 if not(p[u]>=5000 and p['fixed']<1000 and all(p[v]<1000 for v in ('entrance','west','door') if v!=u)):return False
 m=np.asarray(Image.open(Path(p['cap_'+u]).parent/'body-human-mask.png'))>0;ys,xs=np.nonzero(m);H,W=m.shape
 edges={e for e,c in (('T',ys.min()==0),('B',ys.max()==H-1),('L',xs.min()==0),('R',xs.max()==W-1)) if c}
 return not edges or (fam=='W' and rk[0]=='l' and edges=={'B'})
ans={'W':[],'E':[]};off=[]
for name,rots in P.items():
 if name[0]=='O':
  if all(all(rots[rk][v]==0 for v in ('entrance','west','door','fixed')) for rk in rots):off.append(name)
 elif any(eligible(name,rk) for rk in rots if rk[0]=='s') and any(eligible(name,rk) for rk in rots if rk[0]=='l'):ans[name[0]].append(name)
def fps(names,k):
 chosen=[];anchors=list(prior)
 names=sorted(names)
 while len(chosen)<k:
  best=max((n for n in names if n not in chosen),key=lambda n:min(math.dist((cands[n]['x'],cands[n]['y']),a) for a in anchors))
  chosen.append(best);anchors.append((cands[best]['x'],cands[best]['y']))
 return chosen
sel={'W':fps(ans['W'],8),'E':fps(ans['E'],8),'O':fps(off,4)}
rng=random.Random(20261115);cohorts=[[],[]]
for fam in ('W','E','O'):
 names=sorted(sel[fam]);rng.shuffle(names)
 for i,n in enumerate(names):cohorts[i%2].append(n)
SC=['s90','s180','sm90'];LC=['l90','l0','l180','lm90']
def pick(name,cycle,i):
 order=cycle[i%len(cycle):]+cycle[:i%len(cycle)]
 for rk in order:
  if rk in P[name] and (name[0]=='O' or eligible(name,rk)):return rk
 raise ValueError(name)
out=dict(rule=__doc__,eligible=dict(W=sorted(ans['W']),E=sorted(ans['E']),O=sorted(off)),selected=sel,cohorts=[])
idx=0
for ci,names in enumerate(cohorts):
 rows=[]
 for n in names:
  c=cands[n];fam=n[0]
  for posture,cycle in (('standing',SC),('lying',LC)):
   rk=pick(n,cycle,idx);p=P[n][rk]
   rows.append(dict(placement=n,family=fam,posture=posture,rot_key=rk,rotation=c['rotations'][rk],x=c['x'],y=c['y'],pixels={k:p[k] for k in ('entrance','west','door','fixed')},captures={v:p['cap_'+v] for v in ('entrance','west','door')}))
  idx+=1
 out['cohorts'].append(rows)
(OUT/'selection.json').write_text(json.dumps(out,indent=1))
print({k:len(v) for k,v in ans.items()},len(off))
for ci,rows in enumerate(out['cohorts']):
 print('cohort',ci+1)
 for r in rows:print(' ',r['placement'],r['posture'],r['rot_key'],r['pixels'])
