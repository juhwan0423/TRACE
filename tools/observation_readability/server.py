"""First-pass blinded readability review: largest verified target image per failed trial."""
import importlib.util,json,random,argparse,fcntl
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'artifacts/comparisons/20261108_gate060_01/observation_audit_20261109'
spec=importlib.util.spec_from_file_location('posture_review_base',ROOT/'tools/posture_annotation/server.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def prepare(directory):
 directory.mkdir(parents=True,exist_ok=True);mp=directory/'private_manifest.json';source=BASE/'results.json'
 if not mp.exists():
  data=json.loads(source.read_text());cases=[]
  for t in data['trials']:
   if not t['answerable'] or t['grounded_correct'] is True or not t['best_frame']:continue
   b=t['best_frame'];cases.append(dict(trial_id=t['trial_id'],evidence_ids=[b['evidence_id']],path=b['image'],sha256=b['frame_sha256']))
  assert len(cases)==22
  random.Random(202611091).shuffle(cases)
  for i,c in enumerate(cases):c['id']=f'R{i+1:02}'
  base.atomic(mp,dict(schema=1,role='failed_trial_max_target_area_readability_first_pass',source_hashes={str(source):base.sha(source)},cases=cases,
   selection='One maximum verified target-pixel image per failed answerable trial. No VLM answer, gate outcome or posture label used for image selection. Unreadable representative does not establish all frames unreadable.'))
 m=json.loads(mp.read_text())
 for p,h in m['source_hashes'].items():
  if base.sha(p)!=h:raise ValueError('Audit source changed')
 for c in m['cases']:
  if base.sha(c['path'])!=c['sha256']:raise ValueError('Image changed')
 return m

base.prepare=prepare
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,default=BASE/'human_readability_first_pass');parser.add_argument('--port',type=int,default=6175);args=parser.parse_args()
 args.directory.mkdir(parents=True,exist_ok=True)
 with (args.directory/'server.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  server=base.make_server(args.directory,args.port)
  print(f'Readability review: http://127.0.0.1:{server.server_port}',flush=True);server.serve_forever()
