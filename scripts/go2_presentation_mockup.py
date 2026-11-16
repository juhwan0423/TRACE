"""Static presentation composition; no camera, inference, or robot commands."""
import json
from pathlib import Path
import cv2
import cairo
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gdk,GdkPixbuf,GLib
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/go2/presentation';OUT.mkdir(parents=True,exist_ok=True)
rgb=ROOT/'artifacts/go2/20261116-165842/frame.jpg'
video=Path.home()/'다운로드/MicrosoftTeams-video.mp4'
cap=cv2.VideoCapture(str(video));count=cap.get(cv2.CAP_PROP_FRAME_COUNT);cap.set(cv2.CAP_PROP_POS_FRAMES,int(count*.35));ok,frame=cap.read();cap.release()
if not ok:raise RuntimeError('CCTV frame unavailable')
frame=cv2.rotate(frame,cv2.ROTATE_90_COUNTERCLOCKWISE)
cv2.imwrite(str(OUT/'cctv.jpg'),frame)
records=[json.loads(x) for x in (ROOT/'artifacts/go2/qwen-live.jsonl').read_text().splitlines()]
record=next((x for x in reversed(records) if '의자' in x['response']),records[-1])
window=Gtk.Window(title='TRACE · 실제 Go2 관측 모니터');window.set_default_size(1440,900)
css=Gtk.CssProvider();css.load_from_data(b'window {background:#13171b;} label {color:#e1e5e9;font-family:Sans;font-size:16px;} .brand {font-size:26px;font-weight:bold;} .heading {font-size:21px;font-weight:bold;} .muted {color:#a4afb9;font-size:13px;} .accent {color:#4fd1c5;font-size:18px;} frame {border:1px solid #47515c;border-radius:8px;background:#1e262e;}')
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
root=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=18);root.set_border_width(20);window.add(root)
def label(text,style='heading'):
    widget=Gtk.Label(label=text);widget.set_xalign(0);widget.get_style_context().add_class(style);return widget
header=Gtk.Box();header.pack_start(label('TRACE 관측 모니터','brand'),False,False,0);header.pack_start(label('    REAL · Go2 / Jetson','accent'),False,False,0);header.pack_end(label('저장된 관측으로 구성한 목업','muted'),False,False,0);root.pack_start(header,False,False,0)
row=Gtk.Box(spacing=20);root.pack_start(row,True,True,0)
left=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);left.set_size_request(610,-1);row.pack_start(left,False,False,0)
def camera(title,path):
    frame=Gtk.Frame();box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);box.set_border_width(8);frame.add(box)
    box.pack_start(label(title),False,False,0)
    pix=GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path),590,330,True)
    box.pack_start(Gtk.Image.new_from_pixbuf(pix),True,True,0);left.pack_start(frame,True,True,0)
camera('실험실 전경 · CCTV',OUT/'cctv.jpg')
camera('로봇 카메라 · RealSense RGB',rgb)
right=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16);row.pack_start(right,True,True,0)
def card(title,lines,accent=False):
    frame=Gtk.Frame();box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);box.set_border_width(18);frame.add(box)
    box.pack_start(label(title,'accent' if accent else 'heading'),False,False,0)
    for text in lines:
        item=Gtk.Label(label=text);item.set_xalign(0);item.set_line_wrap(True);item.set_max_width_chars(43);box.pack_start(item,False,False,0)
    right.pack_start(frame,False,False,0)
card('관측 워크스페이스',['실험실 전경과 로봇 시야를 함께 확인'],True)
right.pack_start(label('관측  →  Qwen 판독  →  도구 제안','muted'),False,False,0)
card('① 고정 카메라 관측',['CCTV · 저장된 영상 프레임'])
card('② 로봇 카메라 관측',['Go2 · RealSense RGB 저장 프레임'])
card('③ Qwen3-VL 8B · 이전 판독',[record['response']],True)
right.pack_start(label('이전 관측 '+record['frame_received_local']+' · 표시된 RGB와 다른 시점의 결과','muted'),False,False,0)
card('실물 연결 검증',['RGB 수신 · 상태 조회 · Qwen 영상 분석','운영자 승인 기립 확인 · 자동 이동 미연결'])
window.connect('destroy',Gtk.main_quit);window.show_all()
def capture():
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,window.get_allocated_width(),window.get_allocated_height());window.draw(cairo.Context(surface));surface.write_to_png(str(OUT/'trace-mockup.png'))
    (OUT/'provenance.json').write_text(json.dumps({'rgb':str(rgb),'cctv_video':str(video),'cctv_frame_index':int(count*.35),'qwen':record,'note':'Static composition. Historical Qwen response is from a different observation, not inference on the displayed RGB.'},ensure_ascii=False,indent=2))
    print(str(OUT/'trace-mockup.png'),flush=True);return False
GLib.timeout_add(1200,capture);Gtk.main()
