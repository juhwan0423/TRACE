"""Concept diagram of the TRACE inspection loop (not a code call graph)."""
import math, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
OUT = Path(sys.argv[1])
R = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
B = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
f = lambda n, b=False: ImageFont.truetype(B if b else R, n)
INK, GREY, ACC, ACCBG, GBG = '#1f2933', '#6b7785', '#177e89', '#e3f3f5', '#f1f3f5'

def arrow(d, p, q, color=INK, w=5, dash=False):
    (x0, y0), (x1, y1) = p, q
    L = math.hypot(x1 - x0, y1 - y0); ux, uy = (x1 - x0) / L, (y1 - y0) / L
    if dash:
        s = 0
        while s < L - 22:
            e = min(s + 16, L - 22)
            d.line([(x0 + ux * s, y0 + uy * s), (x0 + ux * e, y0 + uy * e)], fill=color, width=w); s += 28
    else:
        d.line([p, (x1 - ux * 20, y1 - uy * 20)], fill=color, width=w)
    d.polygon([(x1, y1), (x1 - ux * 24 - uy * 12, y1 - uy * 24 + ux * 12), (x1 - ux * 24 + uy * 12, y1 - uy * 24 - ux * 12)], fill=color)

def box(d, xy, title, sub='', fill=GBG, edge=GREY, tcol=INK, ew=3):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle(xy, 18, fill=fill, outline=edge, width=ew)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if sub:
        d.text((cx, cy - 22), title, font=f(34, True), anchor='mm', fill=tcol)
        d.text((cx, cy + 26), sub, font=f(24), anchor='mm', fill=GREY)
    else:
        d.text((cx, cy), title, font=f(34, True), anchor='mm', fill=tcol)

def full(path, simple=False):
    im = Image.new('RGB', (1920, 1080), 'white'); d = ImageDraw.Draw(im)
    y0, y1 = 380, 540; cy = (y0 + y1) // 2
    q = (60, y0, 330, y1); o = (410, y0, 720, y1); v = (800, y0, 1090, y1); t = (1170, y0 - 30, 1500, y1 + 30)
    box(d, q, '점검 질의', '“작업자가 서 있는가?”')
    box(d, o, '관측', '고정 카메라 · 로봇 카메라')
    box(d, v, 'VLM 판독', '사람 · 자세 · 제한 사항')
    box(d, t, '근거 확인', '이 화면으로 답할 수 있는가?', fill=ACCBG, edge=ACC, tcol=ACC, ew=5)
    arrow(d, (330, cy), (410, cy)); arrow(d, (720, cy), (800, cy)); arrow(d, (1090, cy), (1170, cy))
    outs = [(180, '확정', '근거 프레임과 함께 답변'), (460, '재관측', '다른 위치로 이동'), (760, '인계', '기한 내 미확인 시')]
    for oy, name, sub in outs:
        bx = (1600, oy, 1880, oy + 130)
        acc = name == '재관측'
        box(d, bx, name, sub, fill=ACCBG if acc else 'white', edge=ACC if acc else GREY, tcol=ACC if acc else INK, ew=5 if acc else 3)
        arrow(d, (1500, cy + (oy + 65 - cy) * 0.25), (1600, oy + 65), color=ACC if acc else INK)
    # re-observation loop back to observation
    ly = 665
    d.line([(1740, 590), (1740, ly), (565, ly)], fill=ACC, width=5)
    arrow(d, (565, ly), (565, y1), color=ACC)
    d.text((1150, ly + 14), '이동 · 재촬영 → 새 관측', font=f(28, True), anchor='ma', fill=ACC)
    if not simple:
        g = (800, 150, 1090, 270)
        box(d, g, '사람 검출 게이트', 'YOLO · ON일 때만')
        arrow(d, (565, y0), (800, 230), color=GREY, dash=True)
        arrow(d, (1090, 210), (1300, y0 - 30), color=GREY, dash=True)
        d.text((60, 60), 'TRACE: 답하기 전에 근거를 확인하는 점검 루프', font=f(46, True), fill=INK)
        d.text((60, 1010), '개념도. 실제 코드 호출 순서를 그대로 나타낸 것은 아님. 시뮬레이터 정답·마스크는 이 경로에 들어가지 않음(평가 전용).', font=f(22), fill=GREY)
    im.save(path)

full(OUT / 'trace_loop_diagram.png')
full(OUT / 'trace_loop_diagram_simple.png', simple=True)
