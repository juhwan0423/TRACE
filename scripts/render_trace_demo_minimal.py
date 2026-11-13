"""Presentation edit of recorded demo: plain footage, small captions, no dashboard."""
import bisect,hashlib,json,subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'artifacts/demo_video_20261110_standing/live'
OUT=ROOT/'artifacts/demo_video_20261111_minimal';OUT.mkdir(exist_ok=True)
r=json.loads((SOURCE/'trials/demo01/result.json').read_text())
rec=json.loads((SOURCE/'trials/demo01/record.json').read_text())
assert rec['inspection_question_answer']=='standing'
refs=rec['normalization']['answer_evidence_ids']
last=next(e for e in r['captured_evidence'] if e['id'] in refs)
first=next(e for e in r['captured_evidence'] if e['source']=='body' and e['id'] not in refs)
events=r['trace'];move=next(e for e in events if e['kind']=='decision' and e['action']['tool']=='inspect')
arrive=next(e for e in events if e['kind']=='tool_result' and e.get('tool')=='inspect' and e.get('status')=='arrived')
samples=[json.loads(l) for l in (SOURCE/'camera_timeline.jsonl').read_text().splitlines()]
samples=[s for s in samples if 'frames'in s]
stamps=[s['snapshot']['now'] for s in samples]
a=bisect.bisect_left(stamps,move['sim_time']);b=bisect.bisect_left(stamps,arrive['sim_time'])
lo,hi=samples[a]['wall_elapsed'],samples[b]['wall_elapsed'];speed=(hi-lo)/8
font='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
f=lambda n:ImageFont.truetype(font,n)
size=(1920,1080)
def image(path,size=size):
 return Image.open(path).convert('RGB').resize(size,Image.Resampling.LANCZOS)
def label(im,caption,note):
 d=ImageDraw.Draw(im)
 d.text((44,980),caption,font=f(38),fill='white',stroke_width=2,stroke_fill='#161616')
 d.text((1876,42),'별도 시뮬레이션 시연',font=f(22),anchor='ra',fill='white',stroke_width=1,stroke_fill='#161616')
 d.text((1876,1036),note,font=f(22),anchor='ra',fill='white',stroke_width=1,stroke_fill='#161616')
 return im
before=label(image(first['artifact']),'초기 관측','실제 관측 프레임 · 정지 화면')
after=label(image(last['artifact']),'재관측: 서 있음','실제 인용 프레임 · 정지 화면')
compare=Image.new('RGB',size,'white');d=ImageDraw.Draw(compare)
for path,x,title in [(first['artifact'],40,'이동 전'),(last['artifact'],980,'이동 후')]:
 compare.paste(image(path,(900,506)),(x,266));d.text((x,204),title,font=f(32),fill='#222222')
d.text((960,840),'재관측 후 자세 확정',font=f(36),anchor='ma',fill='#222222')
d.text((1876,42),'별도 시뮬레이션 시연',font=f(22),anchor='ra',fill='#555555')
d.text((1876,1036),'동일 실행의 실제 관측 프레임',font=f(22),anchor='ra',fill='#555555')
proc=subprocess.Popen(['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','24','-i','-','-an','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(OUT/'trace_demo_minimal_30s.mp4')],stdin=subprocess.PIPE)
wall=[s['wall_elapsed'] for s in samples];motion_mid=None
try:
 for _ in range(7*24):proc.stdin.write(before.tobytes())
 for n in range(8*24):
  t=lo+(hi-lo)*n/(8*24-1);idx=min(bisect.bisect_left(wall,t),len(samples)-1)
  im=label(image(samples[idx]['frames']['overview']['path']),'관측 위치 이동',f'약 {speed:.1f}배속 · 약 2 Hz 촬영')
  proc.stdin.write(im.tobytes())
  if n==4*24:motion_mid=im.copy()
 for _ in range(8*24):proc.stdin.write(after.tobytes())
 for _ in range(7*24):proc.stdin.write(compare.tobytes())
finally:proc.stdin.close()
assert proc.wait()==0
frames=[before,motion_mid,after,compare]
for i,im in enumerate(frames,1):im.save(OUT/f'{i:02}.png')
sheet=Image.new('RGB',(1280,720),'white')
for i,im in enumerate(frames):sheet.paste(im.resize((640,360)),((i%2)*640,(i//2)*360))
sheet.save(OUT/'storyboard.jpg')
(OUT/'edit_manifest.json').write_text(json.dumps(dict(source=str(SOURCE),style='Plain footage/captions; no dashboard',segments=[dict(seconds=7,kind='initial_body_still',evidence_id=first['id']),dict(seconds=8,kind='recorded_overview_motion',wall_start=lo,wall_end=hi,speed=speed),dict(seconds=8,kind='final_cited_still',evidence_id=last['id']),dict(seconds=7,kind='before_after_stills')],scope='Presentation edit; intermediate fixed-camera JSON failure and model waiting omitted, no new simulation or inference',source_hashes={e['artifact']:hashlib.sha256(Path(e['artifact']).read_bytes()).hexdigest() for e in (first,last)}),ensure_ascii=False,indent=2))
print(OUT)
