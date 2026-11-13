"""One explicitly separate live demo; reuse existing harness and capture camera feeds.
No changes to frozen evaluation outputs. Records sampled frames and timestamps.
"""
import argparse,asyncio,base64,fcntl,json,time,hashlib
from pathlib import Path
from real2sim_harness_tools import remote
from run_real2sim_comparison import run_trial,write_json,ROOT
OUT=ROOT/'artifacts/demo_video_20261110/live'
async def main(source_trial):
 OUT.mkdir(parents=True,exist_ok=False)
 cfg=json.loads((ROOT/'artifacts/comparisons/20261109_scoped_limitations_01/protocol.json').read_text())
 entry=next(x for x in cfg['schedule'] if x['trial_id']==source_trial);entry=dict(entry,trial_id='demo01')
 cfg['manifest']['archive_all_detector_frames']=False
 initial=await remote('print(json.dumps(real2sim_navigation.snapshot()))')
 write_json(OUT/'demo_manifest.json',dict(kind='separate_live_demonstration_not_evaluation',source_trial=source_trial+' condition only; fresh decisions',entry=entry,config=cfg['config'],model=cfg['model_config'],initial=initial,capture_target_hz=2,source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src/tracebot').rglob('*.py')}))
 stop=asyncio.Event();started=time.monotonic()
 async def capture():
  folder=OUT/'camera_samples';folder.mkdir();i=0
  with (OUT/'camera_timeline.jsonl').open('w') as log:
   while not stop.is_set():
    tick=time.monotonic()
    try:
     packet=await remote('print(json.dumps(real2sim_monitor_frames()))',timeout=12)
     paths={}
     for cam,f in packet['frames'].items():
      path=folder/f'{i:06}_{cam}.jpg';path.write_bytes(base64.b64decode(f['image']))
      paths[cam]=dict(path=str(path),capture_time=f['capture_time'])
     log.write(json.dumps(dict(index=i,wall_elapsed=time.monotonic()-started,snapshot=packet['snapshot'],frames=paths))+'\n');log.flush();i+=1
    except Exception as e:
     log.write(json.dumps(dict(error=str(e),wall_elapsed=time.monotonic()-started))+'\n');log.flush()
    try:await asyncio.wait_for(stop.wait(),timeout=max(.01,.5-(time.monotonic()-tick)))
    except asyncio.TimeoutError:pass
 task=asyncio.create_task(capture())
 try:
  await run_trial(OUT,cfg,entry)
  await asyncio.sleep(2)
 finally:
  stop.set();await task
  write_json(OUT/'gate_cleanup.json',await remote('print(json.dumps(trace_confirmatory_gate.restore()))'))
 print('DEMO_COMPLETE',OUT,flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser()
 parser.add_argument('--source-trial',default='t0008')
 parser.add_argument('--output',type=Path,default=OUT)
 args=parser.parse_args();OUT=args.output.resolve()
 with (ROOT/'artifacts/closed_loop/runner.lock').open('a') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  asyncio.run(main(args.source_trial))
