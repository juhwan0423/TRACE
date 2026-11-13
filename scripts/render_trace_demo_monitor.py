"""Monitor-style presentation edit of the recorded demo01 run.

Layout and wording follow the TRACE desktop monitor (dark theme, harness log
vocabulary), drawn offline with PIL: this is not a screen recording of the GTK
app. Camera footage is the recorded 2 Hz samples, time-compressed. Every card
line paraphrases a saved structured event of demo01 (asserted below); nothing
is taken from model-internal reasoning. No new simulation or inference.
"""
import argparse, bisect, hashlib, json, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts/demo_video_20261110_standing/live'
_ap = argparse.ArgumentParser()
_ap.add_argument('--lang', choices=('ko', 'en'), default='ko')
LANG = _ap.parse_args().lang
OUT = ROOT / ('artifacts/demo_video_20261112_monitor' + ('_en' if LANG == 'en' else ''))
OUT.mkdir(exist_ok=True)
FPS = 24
W, H = 1920, 1080

# ---------------------------------------------------------------- source run
r = json.loads((SOURCE / 'trials/demo01/result.json').read_text())
rec = json.loads((SOURCE / 'trials/demo01/record.json').read_text())
trace = r['trace']
dec = [e for e in trace if e['kind'] == 'decision']
res = [e for e in trace if e['kind'] == 'tool_result']
answer = next(e for e in trace if e['kind'] == 'inspection_answer')
opened = next(e for e in trace if e['kind'] == 'opened')
ev = {e['id']: e['artifact'] for e in r['captured_evidence']}

# The captions below describe exactly this sequence; fail loudly otherwise.
assert [(d['action']['tool'], d['action']['target']) for d in dec] == \
    [('observe', 'fixed'), ('observe', 'body'), ('inspect', 'west'), ('observe', 'body')]
r_fixed, r_body1, r_move, r_body2 = res
assert r_fixed['valid'] is False and 'JSONDecodeError' in r_fixed['status']
o1, o2 = r_body1['observation'], r_body2['observation']
assert o1['person_visible'] == 'uncertain' and o1['posture'] == 'unknown' and o1['needs_more_observation'] is True
assert o1['observation_limitations'][:2] == ['subject partially obscured by cage structure', 'distance from subject']
assert r_body1['person_gate']['detector_status'] == 'not_detected'
assert 'partial obstruction' in dec[2]['action']['reason'] and 'new line of sight' in dec[2]['action']['reason']
assert r_move['status'] == 'arrived'
assert o2['person_visible'] == 'yes' and o2['posture'] == 'standing' and o2['needs_more_observation'] is False
assert o2['observation_limitations'] == ['face not visible', 'person viewed from rear']
assert r_body2['person_gate']['detector_status'] == 'detected'
q = answer['questions']
assert q['presence']['state'] == 'resolved' and q['presence']['value'] is True
assert q['lying']['state'] == 'resolved' and q['lying']['value'] is False
assert q['lying']['evidence_ids'] == [r_body2['evidence_id']]
assert rec['inspection_question_answer'] == 'standing'
F_FIXED, F_BODY1, F_BODY2 = (ev[x['evidence_id']] for x in (r_fixed, r_body1, r_body2))

samples = [json.loads(l) for l in (SOURCE / 'camera_timeline.jsonl').read_text().splitlines()]
samples = [s for s in samples if 'frames' in s]
stamps = [s['snapshot']['now'] for s in samples]


def sample_at(sim):
    return samples[min(bisect.bisect_left(stamps, sim), len(samples) - 1)]


WALL0 = sample_at(opened['sim_time'])['wall_elapsed']
TOTAL_WALL = r['wall_seconds']

# ------------------------------------------------------------------ timeline
# (key, sim_start, sim_end, video_seconds). sim_start == sim_end means a hold.
T = lambda e: e['sim_time']
SEGMENTS = [
    ('intro',      T(opened), T(dec[0]),   2.5),
    ('fixed_wait', T(dec[0]), T(r_fixed),  2.5),
    ('fixed_done', T(r_fixed), T(r_fixed), 2.0),
    ('body1_wait', T(dec[1]), T(r_body1),  2.5),
    ('body1_done', T(r_body1), T(r_body1), 5.0),
    ('move',       T(dec[2]), T(r_move),   7.0),
    ('body2_wait', T(dec[3]), T(r_body2),  2.5),
    ('body2_done', T(r_body2), T(r_body2), 5.5),
    ('final',      T(r_body2), T(r_body2), 5.0),
]
DURATION = sum(s[3] for s in SEGMENTS)

# --------------------------------------------------------------------- style
R_ = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
B_ = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
_fonts = {}


def f(n, bold=False):
    key = (n, bold)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(B_ if bold else R_, n)
    return _fonts[key]


BG, PANEL, CARD, EDGE = '#13171b', '#171d23', '#1e262e', '#47515c'
TEXT, MUTED, DIM = '#e1e5e9', '#a4afb9', '#6f7a85'
TEAL, AMBER, BAD, GOOD = '#4fd1c5', '#f6c453', '#f08a7b', '#7bd88f'

LX, LW = 24, 848
LH = LW * 9 // 16            # 477
V1Y, V2Y = 96, 96 + LH + 12  # overview, robot camera
RX, RW = LX + LW + 24, W - (LX + LW + 24) - 24   # right column


def fit(path, size):
    return Image.open(path).convert('RGB').resize(size, Image.Resampling.BILINEAR)


def chip(d, xy, text, fg=TEXT, bg='#0d1114', size=22, bold=False, anchor='la'):
    x, y = xy
    font = f(size, bold)
    w = d.textlength(text, font=font)
    if anchor == 'ra':
        x -= w + 24
    d.rounded_rectangle([x, y, x + w + 24, y + size + 16], 8, fill=bg)
    d.text((x + 12, y + 6), text, font=font, fill=fg)
    return x + w + 24


def pill(d, x, y, text, color):
    """Status pill whose right edge sits at x."""
    font = f(22, True)
    w = d.textlength(text, font=font)
    x -= w + 28
    d.rounded_rectangle([x, y, x + w + 28, y + 38], 19, fill=color)
    d.text((x + 14, y + 4), text, font=font, fill='#101418')
    return x + w + 28


def row(d, x, y, label, value, color=TEXT):
    d.text((x, y), label, font=f(22), fill=MUTED)
    d.text((x + 132, y), value, font=f(24), fill=color)


# English card text for --lang en. Keys are the Korean strings drawn below.
EN = {
    '관측': 'Observe',
    'VLM 판독': 'VLM read',
    '근거 확인': 'Check',
    '확정': 'Answer',
    '재관측': 'Re-observe',
    '인계': 'Hand off',
    'TRACE 점검 모니터': 'TRACE inspection monitor',
    '별도 시뮬레이션 시연 · 저장된 실행 기록의 시간 압축 재생': 'Separate simulation demo · time-compressed replay of a saved run',
    '점검 요청': 'Inspection request',
    '작업자가 있는지, 어떤 자세인지 확인하라': 'Is a worker there, and in what posture?',
    '① 고정 카메라 관측': '① Fixed camera observation',
    '무효 처리': 'Rejected',
    'VLM 응답이 형식 오류 → 근거로 쓰지 않음': 'VLM reply was malformed → not used as evidence',
    'VLM 판독 중…': 'VLM reading…',
    '② 로봇 카메라 관측 · 입구': '② Robot camera observation · entrance',
    '근거 불충분': 'Insufficient',
    '사람 불확실 · 자세 미확인 · 추가 관측 필요': 'person uncertain · posture unknown · needs more observation',
    '기록된 제한': 'Limits',
    '구조물에 일부 가림 · 대상과 거리가 멂': 'partly hidden by cage structure · far from subject',
    '사람 검출': 'Detector',
    '검출 안 됨': 'no person detected',
    '→ 이 화면으로는 답할 수 없다. 답을 확정하지 않는다.': '→ This frame cannot support an answer. No answer is given.',
    '③ 재관측 결정 · 서쪽 관측 위치로 이동': '③ Re-observe · move to the west viewpoint',
    '도착': 'Arrived',
    '이동 중': 'Moving',
    '선택 도구': 'Tool',
    '선택 설명': 'Reason',
    '로봇 카메라 화면이 일부 가려짐 → 새 시선에서 본다': 'robot camera view partly obstructed → take a new line of sight',
    '④ 로봇 카메라 관측 · 서쪽': '④ Robot camera observation · west',
    '근거 채택': 'Accepted',
    '사람 보임 · 서 있음 · 추가 관측 불필요': 'person visible · standing · no further observation needed',
    '얼굴 안 보임 · 뒷모습 (자세 질의에는 지장 없음)': 'face not visible · rear view (does not block the posture question)',
    '1명 검출': 'one person detected',
    '→ 이 프레임을 근거로 답할 수 있다.': '→ This frame can support the answer.',
    '답변': 'Answer',
    '작업자 있음 · 서 있음': 'Worker present · standing',
    '근거 프레임 ': 'Cited frame ',
    '자세 질의만 해결 · 전체 안전은 미확정': 'Posture only · overall safety not established',
    'VLM 판독 중': 'VLM reading',
    '이동 전 · 입구에서 본 화면': 'Before moving · view from the entrance',
    '답하지 않음': 'No answer',
    '이동 후 · 서쪽에서 본 화면': 'After moving · view from the west',
    '답의 근거': 'Cited evidence',
    '실험실 전경': 'Lab overview',
    '로봇 이동 중': 'Robot moving',
    '고정 카메라': 'Fixed camera',
    '로봇 카메라 · 판독에 쓴 프레임': 'Robot camera · frame sent to the VLM',
    '로봇 카메라': 'Robot camera',
    '실제 경과 %d:%02d / %d:%02d': 'Real elapsed %d:%02d / %d:%02d',
    '   ·   약 %.0f배속': '   ·   about %.0fx speed',
}


def t(text):
    return EN[text] if LANG == 'en' else text


# ------------------------------------------------------------- right column
ORDER = [s[0] for s in SEGMENTS]
FLOW = [t('관측'), t('VLM 판독'), t('근거 확인'), t('확정'), t('재관측'), t('인계')]
FLOW_AT = dict(intro=None, fixed_wait=1, fixed_done=2, body1_wait=1, body1_done=2, move=4,
               body2_wait=1, body2_done=2, final=3)


def card(d, im, y, h, title, active, tone=None):
    edge = {None: EDGE, 'bad': BAD, 'good': GOOD}[tone] if not active else AMBER
    d.rounded_rectangle([RX, y, RX + RW, y + h], 12, fill=CARD, outline=edge, width=3 if (active or tone) else 1)
    d.text((RX + 22, y + 14), title, font=f(27, True), fill=TEXT)


def panel(key):
    """Static UI for one segment: everything except the live camera views."""
    i = ORDER.index(key)
    at = lambda k: i >= ORDER.index(k)
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    # header
    d.rectangle([0, 0, W, 80], fill=PANEL)
    d.text((LX, 20), t('TRACE 점검 모니터'), font=f(32, True), fill=TEXT)
    d.text((W - 24, 28), t('별도 시뮬레이션 시연 · 저장된 실행 기록의 시간 압축 재생'), font=f(21), anchor='ra', fill=MUTED)
    # question
    d.rounded_rectangle([RX, 96, RX + RW, 212], 12, fill=PANEL, outline=TEAL if key == 'intro' else EDGE,
                        width=3 if key == 'intro' else 1)
    d.text((RX + 22, 108), t('점검 요청'), font=f(22), fill=TEAL)
    d.text((RX + 22, 142), t('작업자가 있는지, 어떤 자세인지 확인하라'), font=f(40, True), fill=TEXT)
    # flow strip
    x = RX
    for n, name in enumerate(FLOW):
        on = FLOW_AT[key] == n
        font = f(24, on)
        w = d.textlength(name, font=font)
        d.rounded_rectangle([x, 228, x + w + 36, 272], 8, fill=TEAL if on else PANEL, outline=None if on else EDGE)
        d.text((x + 18, 234), name, font=font, fill='#101418' if on else MUTED)
        x += w + 36
        if n < len(FLOW) - 1:
            d.text((x + 8, 234), '→' if n < 3 else '/', font=f(24), fill=DIM)
            x += 44 if n < 3 else 30
    y = 290
    tx = RX + 22
    # 1. fixed camera
    if at('fixed_wait'):
        done = at('fixed_done')
        card(d, im, y, 88, t('① 고정 카메라 관측'), key == 'fixed_wait', 'bad' if key == 'fixed_done' else None)
        if done:
            pill(d, RX + RW - 16, y + 12, t('무효 처리'), BAD)
            d.text((tx, y + 50), t('VLM 응답이 형식 오류 → 근거로 쓰지 않음'), font=f(24), fill=TEXT)
        else:
            d.text((tx, y + 50), t('VLM 판독 중…'), font=f(24), fill=AMBER)
        y += 88 + 10
    # 2. robot camera at entrance
    if at('body1_wait'):
        done = at('body1_done')
        card(d, im, y, 200, t('② 로봇 카메라 관측 · 입구'), key == 'body1_wait', 'bad' if key == 'body1_done' else None)
        if done:
            pill(d, RX + RW - 16, y + 12, t('근거 불충분'), BAD)
            row(d, tx, y + 54, t('VLM 판독'), t('사람 불확실 · 자세 미확인 · 추가 관측 필요'))
            row(d, tx, y + 88, t('기록된 제한'), t('구조물에 일부 가림 · 대상과 거리가 멂'))
            row(d, tx, y + 122, t('사람 검출'), t('검출 안 됨'))
            d.text((tx, y + 158), t('→ 이 화면으로는 답할 수 없다. 답을 확정하지 않는다.'), font=f(25, True), fill=BAD)
        else:
            d.text((tx, y + 54), t('VLM 판독 중…'), font=f(24), fill=AMBER)
        y += 200 + 10
    # 3. re-observation decision
    if at('move'):
        arrived = at('body2_wait')
        card(d, im, y, 124, t('③ 재관측 결정 · 서쪽 관측 위치로 이동'), key == 'move')
        if arrived:
            pill(d, RX + RW - 16, y + 12, t('도착'), TEAL)
        else:
            pill(d, RX + RW - 16, y + 12, t('이동 중'), AMBER)
        row(d, tx, y + 52, t('선택 도구'), 'inspect / west')
        row(d, tx, y + 86, t('선택 설명'), t('로봇 카메라 화면이 일부 가려짐 → 새 시선에서 본다'))
        y += 124 + 10
    # 4. robot camera at west
    if at('body2_wait'):
        done = at('body2_done')
        card(d, im, y, 200, t('④ 로봇 카메라 관측 · 서쪽'), key == 'body2_wait', 'good' if key == 'body2_done' else None)
        if done:
            pill(d, RX + RW - 16, y + 12, t('근거 채택'), GOOD)
            row(d, tx, y + 54, t('VLM 판독'), t('사람 보임 · 서 있음 · 추가 관측 불필요'))
            row(d, tx, y + 88, t('기록된 제한'), t('얼굴 안 보임 · 뒷모습 (자세 질의에는 지장 없음)'))
            row(d, tx, y + 122, t('사람 검출'), t('1명 검출'))
            d.text((tx, y + 158), t('→ 이 프레임을 근거로 답할 수 있다.'), font=f(25, True), fill=GOOD)
        else:
            d.text((tx, y + 54), t('VLM 판독 중…'), font=f(24), fill=AMBER)
        y += 200 + 10
    # answer bar
    if at('body2_done'):
        hot = key == 'final'
        d.rounded_rectangle([RX, y, RX + RW, y + 96], 12, fill='#17301f' if hot else PANEL, outline=GOOD, width=4 if hot else 2)
        d.text((tx, y + 10), t('답변'), font=f(22), fill=GOOD)
        d.text((tx, y + 36), t('작업자 있음 · 서 있음'), font=f(38, True), fill=TEXT)
        d.text((RX + RW - 22, y + 20), t('근거 프레임 ') + r_body2['evidence_id'][:8], font=f(21), anchor='ra', fill=MUTED)
        d.text((RX + RW - 22, y + 52), t('자세 질의만 해결 · 전체 안전은 미확정'), font=f(21), anchor='ra', fill=MUTED)
    return im


def view(base, d, y, img, label, tone=None, note=None):
    base.paste(img, (LX, y))
    color = {None: EDGE, 'wait': AMBER, 'bad': BAD, 'good': GOOD}[tone]
    d.rectangle([LX, y, LX + LW - 1, y + LH - 1], outline=color, width=5 if tone else 1)
    chip(d, (LX + 12, y + 12), label)
    if note:
        fg = '#101418'
        chip(d, (LX + LW - 12, y + 12), note, fg=fg, bg=color, bold=True, anchor='ra')


BODY_TONE = dict(body1_wait=('wait', t('VLM 판독 중')), body1_done=('bad', t('근거 불충분')),
                 body2_wait=('wait', t('VLM 판독 중')), body2_done=('good', t('근거 채택')))
_panels = {}


def compose(key, sim, speed):
    if key not in _panels:
        _panels[key] = panel(key)
    im = _panels[key].copy()
    d = ImageDraw.Draw(im)
    s = sample_at(sim)
    if key == 'final':
        view(im, d, V1Y, fit(F_BODY1, (LW, LH)), t('이동 전 · 입구에서 본 화면'), 'bad', t('답하지 않음'))
        view(im, d, V2Y, fit(F_BODY2, (LW, LH)), t('이동 후 · 서쪽에서 본 화면'), 'good', t('답의 근거'))
    else:
        view(im, d, V1Y, fit(s['frames']['overview']['path'], (LW, LH)), t('실험실 전경'),
             'wait' if key == 'move' else None, t('로봇 이동 중') if key == 'move' else None)
        # fixed camera inset
        iw, ih = 272, 153
        ix, iy = LX + 12, V1Y + LH - ih - 12
        fixed_img = fit(F_FIXED if key == 'fixed_done' else s['frames']['fixed']['path'], (iw, ih))
        im.paste(fixed_img, (ix, iy))
        tone = {'fixed_wait': AMBER, 'fixed_done': BAD}.get(key, EDGE)
        d.rectangle([ix, iy, ix + iw - 1, iy + ih - 1], outline=tone, width=4 if key.startswith('fixed') else 1)
        chip(d, (ix + 6, iy + 6), t('고정 카메라'), size=17)
        # robot camera: live sample, or the exact evidence frame while its verdict is shown
        frozen = {'body1_done': F_BODY1, 'body2_done': F_BODY2}.get(key)
        tone, note = BODY_TONE.get(key, (None, None))
        label = t('로봇 카메라 · 판독에 쓴 프레임') if frozen else t('로봇 카메라')
        view(im, d, V2Y, fit(frozen or s['frames']['body']['path'], (LW, LH)), label, tone, note)
    wall = max(0.0, min(TOTAL_WALL, s['wall_elapsed'] - WALL0)) if key != 'final' else TOTAL_WALL
    clock = t('실제 경과 %d:%02d / %d:%02d') % (wall // 60, wall % 60, TOTAL_WALL // 60, TOTAL_WALL % 60)
    if speed:
        clock += t('   ·   약 %.0f배속') % speed
    title_end = LX + d.textlength(t('TRACE 점검 모니터'), font=f(32, True))
    d.text((max(430, title_end + 32), 28), clock, font=f(21), fill=MUTED)
    return im


# -------------------------------------------------------------------- render
video = OUT / ('trace_demo_monitor_en.mp4' if LANG == 'en' else 'trace_demo_monitor.mp4')
proc = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
                         '-r', str(FPS), '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                         '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)], stdin=subprocess.PIPE)
stills, manifest = {}, []
try:
    for key, s0, s1, dur in SEGMENTS:
        n = round(dur * FPS)
        w0, w1 = sample_at(s0)['wall_elapsed'], sample_at(s1)['wall_elapsed']
        speed = (w1 - w0) / dur if s1 > s0 else 0
        manifest.append(dict(segment=key, video_seconds=dur, sim_start=s0, sim_end=s1,
                             wall_span_seconds=round(w1 - w0, 2), speed=round(speed, 2)))
        last_idx, frame = None, None
        for k in range(n):
            sim = s0 + (s1 - s0) * k / max(n - 1, 1)
            idx = min(bisect.bisect_left(stamps, sim), len(samples) - 1)
            if idx != last_idx:
                frame = compose(key, sim, speed)
                last_idx = idx
                raw = frame.tobytes()
            proc.stdin.write(raw)
            if k == (n * 3) // 4:
                stills[key] = frame.copy()
finally:
    proc.stdin.close()
assert proc.wait() == 0

for i, (key, im) in enumerate(stills.items()):
    im.save(OUT / f'{i:02}_{key}.png')
keys = ['intro', 'body1_done', 'move', 'body2_done', 'final', 'fixed_done']
sheet = Image.new('RGB', (1920, 720), 'white')
for i, key in enumerate(keys):
    sheet.paste(stills[key].resize((640, 360), Image.Resampling.LANCZOS), ((i % 3) * 640, (i // 3) * 360))
sheet.save(OUT / 'storyboard.jpg', quality=90)
(OUT / 'edit_manifest.json').write_text(json.dumps(dict(
    source=str(SOURCE), duration_seconds=DURATION, fps=FPS, language=LANG,
    style='Offline PIL rendering in the TRACE monitor look; not a screen recording of the GTK app',
    segments=manifest,
    card_basis=dict(decisions=[d['action'] for d in dec],
                    results=[{k: v for k, v in x.items() if k != 'episode'} for x in res],
                    inspection_answer=answer['questions'], scope=answer['scope']),
    scope='Presentation edit of one separate demonstration run. Model waiting is time-compressed, verdict frames '
          'are held. Card text paraphrases saved structured events. No new simulation or inference.',
    source_hashes={p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (F_FIXED, F_BODY1, F_BODY2)},
), ensure_ascii=False, indent=2))
print(OUT, DURATION)
