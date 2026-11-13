"""Compose sampled live capture + actual event labels; final evidence held 8s."""
import argparse,bisect,json,subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'artifacts/demo_video_20261110/live'
parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,default=P)
P=parser.parse_args().input.resolve()
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
BOLD='/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
f=lambda n,b=False:ImageFont.truetype(BOLD if b else FONT,n)
r=json.loads((P/'trials/demo01/result.json').read_text());record=json.loads((P/'trials/demo01/record.json').read_text())
events=r['trace'];opened=next(e['sim_time'] for e in events if e['kind']=='opened')
end=max(e['sim_time'] for e in events)
samples=[json.loads(l) for l in (P/'camera_timeline.jsonl').read_text().splitlines()]
samples=[x for x in samples if 'frames' in x and opened<=x['snapshot']['now']<=end]
assert len(samples)>10
wall=[x['wall_elapsed'] for x in samples];duration=wall[-1]-wall[0];speed=duration/22
refs=record['normalization']['answer_evidence_ids']
evidence=next((x for x in r.get('captured_evidence',[]) if x['id'] in refs),None)
answer={'lying':'누워 있음','standing':'서 있음','unknown':'미확인'}.get(record['inspection_question_answer'],'미확인')
decisions=[e for e in events if e['kind']=='decision']
def canvas():
 im=Image.new('RGB',(1920,1080),'#101B2B');d=ImageDraw.Draw(im)
 d.text((35,22),'TRACE | 관측 → 재관측 → 판단·인계',font=f(40,True),fill='white')
 d.text((35,80),'별도 시뮬레이션 시연 · 평가 실행 영상 아님 · 연속 카메라 샘플의 시간 압축',font=f(24),fill='#B5C6D9')
 return im,d
cache={}
def frame(idx,playback_speed=None):
 playback_speed=speed if playback_speed is None else playback_speed
 key=(idx,round(playback_speed,3))
 if key in cache:return cache[key].copy()
 x=samples[idx];im,d=canvas()
 for cam,xy,size,title in [('overview',(0,140),(1280,720),'실험실 전경'),('fixed',(1280,140),(640,360),'고정 카메라'),('body',(1280,500),(640,360),'로봇 카메라')]:
  image=Image.open(x['frames'][cam]['path']).convert('RGB').resize(size)
  im.paste(image,xy);d.rectangle((xy[0],xy[1],xy[0]+230,xy[1]+43),fill='#15243A');d.text((xy[0]+12,xy[1]+4),title,font=f(24),fill='white')
 now=x['snapshot']['now'];current=[e for e in decisions if e['sim_time']<=now]
 action=current[-1]['action'] if current else {};tool=action.get('tool','observe')
 status={'observe':'영상 판독 및 근거 확인 중','inspect':'추가 관측 위치로 이동 중','escalate':'미확인 인계','wait':'추가 근거 대기','stop':'정지'}.get(tool,tool)
 target=action.get('target','');names={'west':'서쪽','door':'문 쪽','entrance':'입구','body':'로봇 카메라','fixed':'고정 카메라'}
 d.text((35,890),status+(' | '+names.get(target,target) if target else ''),font=f(37,True),fill='#63D7D0')
 d.text((35,958),f"시연 경과 {x['wall_elapsed']-wall[0]:.1f}초  |  시뮬레이션 경과 {now-opened:.1f}초",font=f(26),fill='white')
 d.text((35,1005),f'실제 경과시간 기준 약 {playback_speed:.1f}배속 · 약 2 Hz 샘플링 · 이동은 실제 제어기 실행',font=f(23),fill='#B5C6D9')
 if len(cache)>10:cache.clear()
 cache[key]=im.copy();return im
last,d=canvas()
if evidence:
 last.paste(Image.open(evidence['artifact']).convert('RGB').resize((1280,720)),(0,140))
 d.text((1310,160),'최종 인용 프레임',font=f(32,True),fill='#63D7D0')
 d.text((1310,230),'자세 판단: '+answer,font=f(32,True),fill='white')
 d.text((1310,300),'새 실행의 실제 출력',font=f(25),fill='#B5C6D9')
 d.text((1310,350),'전체 안전·부상 판정 아님',font=f(24),fill='#B5C6D9')
 d.text((35,895),'이 프레임을 근거로 자세 질의를 종료',font=f(36,True),fill='#63D7D0')
 d.text((35,960),'마지막 8초: 실제 인용 프레임 정지 화면',font=f(25),fill='white')
else:
 last=frame(len(samples)-1);d=ImageDraw.Draw(last)
 d.rectangle((0,875,1920,1080),fill='#101B2B');d.text((35,905),'시연 결과: 미확인 인계' if answer=='미확인' else '시연 결과: '+answer,font=f(38),fill='white')
 d.text((35,975),'추가 관측 후에도 자세 확인 근거 부족 → 확정하지 않고 인계',font=f(26),fill='#B5C6D9')
output=P.parent/'trace_demo_30s.mp4'
proc=subprocess.Popen(['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','24','-i','-','-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(output)],stdin=subprocess.PIPE)
try:
 # Allocate readable time to actual motion instead of letting long model waits dominate.
 moves=[e for e in events if e['kind']=='decision' and e.get('action',{}).get('tool')=='inspect']
 arrived=[e for e in events if e['kind']=='tool_result' and e.get('tool')=='inspect' and e.get('status')=='arrived']
 segments=[(wall[0],wall[-1],22)]
 if moves and arrived:
  simtimes=[x['snapshot']['now'] for x in samples]
  start=wall[min(bisect.bisect_left(simtimes,moves[0]['sim_time']),len(wall)-1)]
  stop=wall[min(bisect.bisect_left(simtimes,arrived[0]['sim_time']),len(wall)-1)]
  if wall[0]<start<stop<wall[-1]:segments=[(wall[0],start,4),(start,stop,8),(stop,wall[-1],10)]
 for lo,hi,seconds in segments:
  for n in range(seconds*24):
   t=lo+(hi-lo)*n/(seconds*24-1);idx=min(bisect.bisect_left(wall,t),len(samples)-1)
   im=frame(idx,(hi-lo)/seconds);proc.stdin.write(im.tobytes())
 for _ in range(8*24):proc.stdin.write(last.tobytes())
finally:proc.stdin.close()
assert proc.wait()==0
arrivals=[e['sim_time'] for e in events if e['kind']=='tool_result' and e.get('tool')=='inspect' and e.get('status')=='arrived']
reobserve=next((i for i,x in enumerate(samples) if arrivals and x['snapshot']['now']>=arrivals[0]),len(samples)//2)
for name,im in [('01_initial',frame(0)),('02_reobserve',frame(reobserve)),('03_final',last)]:im.save(P.parent/(name+'.png'))
(P.parent/'video_metadata.json').write_text(json.dumps(dict(source='separate live demo',samples=len(samples),live_wall_duration_seconds=duration,mean_playback_speed=speed,segments=[dict(wall_start=lo,wall_end=hi,video_seconds=sec,playback_speed=(hi-lo)/sec) for lo,hi,sec in segments],video_duration_seconds=30,final_hold_seconds=8,answer=record['inspection_question_answer'],evidence_ids=refs),indent=2))
print(output)
