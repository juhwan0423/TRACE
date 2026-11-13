from pathlib import Path
import json, shutil, hashlib, zipfile
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/ksme_story_assets_20261111'
OUT.mkdir(exist_ok=True)
raw=OUT/'source_frames'; raw.mkdir(exist_ok=True)
base=ROOT/'artifacts/comparisons/20261108_gate060_01'
demo=ROOT/'artifacts/demo_video_20261110_standing/live/trials/demo01'
case=json.loads((base/'failure_audit_20261109/findings.json').read_text())['cases'][0]
result=json.loads((demo/'result.json').read_text())
events=[x for x in result['trace'] if x['kind'] in ('decision','tool_result')]
obs=[x for x in events if x['kind']=='tool_result' and x.get('target')=='body']
font='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
def f(n): return ImageFont.truetype(font,n)
def panel(name,title,sub,frame,lines,bottom,box=None):
 im=Image.new('RGB',(1920,1080),'white'); d=ImageDraw.Draw(im)
 d.text((64,46),title,font=f(48),fill='#171717')
 d.text((64,125),sub,font=f(25),fill='#666666')
 pic=Image.open(frame).convert('RGB')
 if box:
  pd=ImageDraw.Draw(pic);pd.rectangle(box,width=3,outline='#ba3a32')
 im.paste(pic.resize((1088,612),Image.Resampling.LANCZOS),(64,224))
 d.line((1190,224,1190,836),fill='#dddddd',width=2)
 y=230
 for text,size,color in lines:
  d.text((1230,y),text,font=f(size),fill=color);y+=size+26
 d.text((64,886),bottom,font=f(31),fill='#222222')
 d.text((64,1005),'TRACE · 저장된 관측과 구조화 로그 발췌 · 원문 및 출처는 동봉 파일 참조',font=f(21),fill='#777777')
 im.save(OUT/name)
 return im
failure=Path(case['frame_path'])
initial=demo/'frames'/f"{obs[0]['evidence_id']}.png"
final=demo/'frames'/f"{obs[-1]['evidence_id']}.png"
for n,p in [('failure.png',failure),('before.png',initial),('after.png',final)]:shutil.copy2(p,raw/n)
grey='#555555'; black='#222222'
images=[]
images.append(panel('01_failure_answer.png','답은 맞았지만, 이 화면으로 확인했을까?','초기 비교 실험 · t0020 · 게이트 ON · 실제 자세: 서 있음',failure,[
 ('당시 Qwen 구조화 응답',28,grey),('person_visible: yes',28,black),('posture: standing',28,black),('needs_more_observation:',26,black),('false',28,black),('최종 자세 응답: 서 있음',29,black)],
 '실제 자세와 응답은 일치했다. 그러나 인용 프레임의 작업자 픽셀은 0이었다.'))
images.append(panel('02_failure_gate.png','사람 검출 통과가 작업자 확인을 보장하지 않았다','같은 실패 실행 t0020 · 붉은 박스는 저장된 YOLO 검출 좌표',failure,[
 ('당시 검출 게이트',28,grey),('person confidence: 0.6004',27,black),('threshold: 0.60',28,black),('gate_passed: true',28,black),('사후 평가: target pixels = 0',26,'#a52e28')],
 '박스는 설비 영역에 걸렸다. Qwen이 같은 설비를 지칭했는지는 알 수 없다.',case['detector_boxes'][0]['xyxy']))
images.append(panel('03_demo_before.png','확인할 수 없으면, 다른 관측 위치로 이동한다','별도 성공 시연 · demo01 · 앞의 실패 실행과 다른 실행',initial,[
 ('이동 전 관측 로그',28,grey),('person_visible: uncertain',27,black),('posture: unknown',28,black),('needs_more_observation:',26,black),('true',28,black),('다음 도구: inspect / west',27,black)],
 '관측 응답은 불확실했다. 에이전트는 서쪽 시점으로 이동하는 도구를 선택했다.'))
images.append(panel('05_demo_after.png','새 관측을 확보한 뒤, 자세를 확정한다','별도 성공 시연 · demo01 · 이동 후 실제 인용 프레임',final,[
 ('이동 후 관측 로그',28,grey),('person_visible: yes',28,black),('posture: standing',28,black),('needs_more_observation:',26,black),('false',28,black),('질의 해결: presence / lying',25,black)],
 '뒷모습·얼굴 미노출은 기록에 남겼다. 자세는 확인했지만 전체 안전은 확정하지 않았다.'))
shutil.copy2(ROOT/'artifacts/demo_video_20261111_minimal/trace_demo_minimal_30s.mp4',OUT/'04_demo_30s.mp4')
payload={'failure':case,'demo':{'source_result':str(demo/'result.json'),'events':events,'inspection_answer':result['inspection_answer'],'incident_events':result['incident_events']}}
(OUT/'logs_structured.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
text=[
'발표 순서 및 원문 확인','',
'01_failure_answer.png: 답은 실제 자세와 같지만 인용 화면에는 작업자가 없는 사례.',
'02_failure_gate.png: 같은 프레임의 YOLO 박스를 공개. 설비라는 해석은 assistant 시각 진단이며 독립 블라인드 판독이 아님.',
'03_demo_before.png: 별도 시연의 이동 전 관측 및 이동 선택.',
'04_demo_30s.mp4: 별도 시연 편집본. 정지 화면/배속 표시. 초기 fixed 카메라 JSON 오류 및 대기 구간 생략.',
'05_demo_after.png: 새 프레임으로 자세 질의를 해결. overall safety는 미확정.',
'',
'실패와 성공 시연을 한 실행의 수정 전후처럼 설명하지 말 것.',
'영상의 이동 전후는 같은 demo01 실행. 원본 구조화 로그는 logs_structured.json에 보존.',
'tool_result의 accepted=false는 위험 근거 채택 필드이며 자세 질의 해결 여부와 다름.',
'최종 판정은 inspection_answer의 resolved 상태 및 evidence_ids로 확인.',
'',
'--- 실패 당시 Qwen 구조화 응답 원문 ---',
json.dumps(case['qwen_final_interpretation'],ensure_ascii=False,indent=2),
'',
'--- 시연 도구 선택/관측 결과 원문 (모델 내부 추론 아님) ---',
json.dumps(events,ensure_ascii=False,indent=2),
'',
'--- 시연 최종 질의 상태 원문 ---',
json.dumps(result['inspection_answer'],ensure_ascii=False,indent=2),
]
(OUT/'logs_and_usage.txt').write_text('\n'.join(text))
sources=[failure,initial,final,demo/'result.json',base/'failure_audit_20261109/findings.json']
(OUT/'provenance.json').write_text(json.dumps([{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources],indent=2))
sheet=Image.new('RGB',(1280,720),'white')
for i,im in enumerate(images):sheet.paste(im.resize((640,360)),((i%2)*640,(i//2)*360))
sheet.save(OUT/'preview.jpg')
with zipfile.ZipFile(OUT.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as z:
 for p in OUT.rglob('*'):
  if p.is_file():z.write(p,p.relative_to(OUT.parent))
print(OUT)
