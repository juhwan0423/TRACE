"""Captioned presentation edit of the recorded demo01 run.

Same source run and frames as render_trace_demo_minimal.py. Adds the operator
question and the recorded reason for re-observation as captions. No new
simulation or inference; captions paraphrase the saved structured log.
"""
import bisect, hashlib, json, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts/demo_video_20261110_standing/live'
OUT = ROOT / 'artifacts/demo_video_20261111_captioned'
OUT.mkdir(exist_ok=True)

r = json.loads((SOURCE / 'trials/demo01/result.json').read_text())
rec = json.loads((SOURCE / 'trials/demo01/record.json').read_text())
assert rec['inspection_question_answer'] == 'standing'
refs = rec['normalization']['answer_evidence_ids']
last = next(e for e in r['captured_evidence'] if e['id'] in refs)
first = next(e for e in r['captured_evidence'] if e['source'] == 'body' and e['id'] not in refs)
events = r['trace']
results = [e for e in events if e['kind'] == 'tool_result']
first_obs = next(e for e in results if e.get('evidence_id') == first['id'])['observation']
last_obs = next(e for e in results if e.get('evidence_id') == last['id'])['observation']
# Captions below are only valid for this recorded sequence.
assert first_obs['person_visible'] == 'uncertain' and first_obs['posture'] == 'unknown'
assert first_obs['needs_more_observation'] is True
assert last_obs['person_visible'] == 'yes' and last_obs['posture'] == 'standing'
move = next(e for e in events if e['kind'] == 'decision' and e['action']['tool'] == 'inspect')
assert move['action']['target'] == 'west'
arrive = next(e for e in results if e.get('tool') == 'inspect' and e.get('status') == 'arrived')

samples = [json.loads(l) for l in (SOURCE / 'camera_timeline.jsonl').read_text().splitlines()]
samples = [s for s in samples if 'frames' in s]
stamps = [s['snapshot']['now'] for s in samples]
a = bisect.bisect_left(stamps, move['sim_time'])
b = bisect.bisect_left(stamps, arrive['sim_time'])
lo, hi = samples[a]['wall_elapsed'], samples[b]['wall_elapsed']

FPS = 24
SEG = dict(question=3, before=6, move=8, after=7, compare=6)
assert sum(SEG.values()) == 30
speed = (hi - lo) / SEG['move']

FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
BOLD = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
f = lambda n, bold=False: ImageFont.truetype(BOLD if bold and Path(BOLD).exists() else FONT, n)
SIZE = (1920, 1080)
TAG = '별도 시뮬레이션 시연'


def image(path, size=SIZE):
    return Image.open(path).convert('RGB').resize(size, Image.Resampling.LANCZOS)


def label(im, step, caption, sub, note):
    """Bottom caption band: step number, main sentence, recorded detail."""
    im = im.convert('RGBA')
    band = Image.new('RGBA', SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(band).rectangle([0, 850, 1920, 1080], fill=(0, 0, 0, 170))
    im = Image.alpha_composite(im, band).convert('RGB')
    d = ImageDraw.Draw(im)
    d.text((56, 876), step, font=f(26, True), fill='#ffd166')
    d.text((56, 916), caption, font=f(46, True), fill='white')
    d.text((56, 990), sub, font=f(28), fill='#dddddd')
    d.text((1876, 42), TAG, font=f(22), anchor='ra', fill='white', stroke_width=1, stroke_fill='#161616')
    d.text((1876, 1036), note, font=f(22), anchor='ra', fill='#cccccc')
    return im


question = Image.new('RGB', SIZE, 'white')
d = ImageDraw.Draw(question)
d.text((960, 380), '점검 요청', font=f(36), anchor='ma', fill='#666666')
d.text((960, 450), '“작업자가 있는지, 어떤 자세인지 확인하라”', font=f(64, True), anchor='ma', fill='#111111')
d.text((960, 600), '로봇은 지금 답할지, 다른 위치에서 다시 볼지, 인계할지를 정해야 한다', font=f(32), anchor='ma', fill='#444444')
d.text((1876, 42), TAG, font=f(22), anchor='ra', fill='#555555')

before = label(image(first['artifact']), '① 첫 관측',
               '이 화면으로는 작업자를 확인할 수 없다',
               '관측 응답: 사람 여부 불확실 · 자세 미확인 · 추가 관측 필요',
               '실제 관측 프레임 · 정지 화면')
after = label(image(last['artifact']), '③ 재관측',
              '작업자가 보인다 → “서 있음”으로 답한다',
              '관측 응답: 사람 보임 · 서 있음 · 추가 관측 불필요 (뒷모습·얼굴 미노출은 기록)',
              '실제 인용 프레임 · 정지 화면')

compare = Image.new('RGB', SIZE, 'white')
d = ImageDraw.Draw(compare)
for path, x, title in [(first['artifact'], 40, '이동 전: 답하지 않음'), (last['artifact'], 980, '이동 후: 서 있음')]:
    compare.paste(image(path, (900, 506)), (x, 266))
    d.text((x, 204), title, font=f(34, True), fill='#222222')
d.text((960, 830), '답의 근거가 되는 화면을 확보한 뒤에 답했다', font=f(40, True), anchor='ma', fill='#111111')
d.text((960, 900), '자세 질의만 해결 · 전체 안전 여부는 확정하지 않음', font=f(28), anchor='ma', fill='#555555')
d.text((1876, 42), TAG, font=f(22), anchor='ra', fill='#555555')
d.text((1876, 1036), '동일 실행의 실제 관측 프레임', font=f(22), anchor='ra', fill='#555555')

video = OUT / 'trace_demo_captioned_30s.mp4'
proc = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1920x1080',
                         '-r', str(FPS), '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '19',
                         '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)], stdin=subprocess.PIPE)
wall = [s['wall_elapsed'] for s in samples]
motion_mid = None
try:
    for _ in range(SEG['question'] * FPS):
        proc.stdin.write(question.tobytes())
    for _ in range(SEG['before'] * FPS):
        proc.stdin.write(before.tobytes())
    n_move = SEG['move'] * FPS
    for n in range(n_move):
        t = lo + (hi - lo) * n / (n_move - 1)
        idx = min(bisect.bisect_left(wall, t), len(samples) - 1)
        im = label(image(samples[idx]['frames']['overview']['path']), '② 재관측 결정',
                   '근거가 부족하다 → 서쪽 관측 위치로 이동한다',
                   '에이전트가 선택한 도구: inspect / west',
                   f'약 {speed:.1f}배속 · 약 2 Hz 촬영')
        proc.stdin.write(im.tobytes())
        if n == n_move // 2:
            motion_mid = im.copy()
    for _ in range(SEG['after'] * FPS):
        proc.stdin.write(after.tobytes())
    for _ in range(SEG['compare'] * FPS):
        proc.stdin.write(compare.tobytes())
finally:
    proc.stdin.close()
assert proc.wait() == 0

frames = [question, before, motion_mid, after, compare]
names = ['00_question', '01_first_observation', '02_move', '03_reobservation', '04_before_after']
for name, im in zip(names, frames):
    im.save(OUT / f'{name}.png')
sheet = Image.new('RGB', (1920, 720), 'white')
for i, im in enumerate(frames):
    sheet.paste(im.resize((640, 360)), ((i % 3) * 640, (i // 3) * 360))
sheet.save(OUT / 'storyboard.jpg')
(OUT / 'edit_manifest.json').write_text(json.dumps(dict(
    source=str(SOURCE),
    style='Plain footage with question/reason captions',
    segments=[dict(seconds=SEG['question'], kind='question_card'),
              dict(seconds=SEG['before'], kind='initial_body_still', evidence_id=first['id']),
              dict(seconds=SEG['move'], kind='recorded_overview_motion', wall_start=lo, wall_end=hi, speed=speed),
              dict(seconds=SEG['after'], kind='final_cited_still', evidence_id=last['id']),
              dict(seconds=SEG['compare'], kind='before_after_stills')],
    caption_basis=dict(first_observation=first_obs, final_observation=last_obs, move_action=move['action']),
    scope='Presentation edit; captions paraphrase saved structured responses, not model reasoning. '
          'Intermediate fixed-camera JSON failure and model waiting omitted. No new simulation or inference.',
    source_hashes={e['artifact']: hashlib.sha256(Path(e['artifact']).read_bytes()).hexdigest() for e in (first, last)},
), ensure_ascii=False, indent=2))
print(OUT)
