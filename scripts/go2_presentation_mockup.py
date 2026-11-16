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
window=Gtk.Window(title='TRACE · 관측 화면 목업');window.set_default_size(1280,820)
css=Gtk.CssProvider();css.load_from_data(b'window {background:#101820;} label {color:#dce6ef;font-family:Sans;} .brand {font-size:28px;font-weight:bold;} .heading {font-size:15px;font-weight:bold;} .muted {color:#8396a7;font-size:12px;} frame {border:1px solid #2c3b49;background:#19242f;} notebook {background:#19242f;} textview,textview text {background:#19242f;color:#dce6ef;font-size:16px;}')
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
root=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=22);root.set_border_width(26);window.add(root)
def label(text,style='heading'):
    widget=Gtk.Label(label=text);widget.set_xalign(0);widget.get_style_context().add_class(style);return widget
header=Gtk.Box();header.pack_start(label('TRACE','brand'),False,False,0);header.pack_start(label('    Robot observation workspace','muted'),False,False,0);header.pack_end(label('목업','muted'),False,False,0);root.pack_start(header,False,False,0)
row=Gtk.Box(spacing=24);root.pack_start(row,True,True,0)
def panel(title,path,width,height):
    box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);box.pack_start(label(title),False,False,0)
    pix=GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path),width,height,True)
    frame=Gtk.Frame();image=Gtk.Image.new_from_pixbuf(pix);frame.add(image);box.pack_start(frame,True,True,0);return box
left=panel('Go2  /  RGB',rgb,760,570);row.pack_start(left,True,True,0)
right=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=20);right.set_size_request(390,-1);row.pack_start(right,False,False,0)
right.pack_start(panel('CCTV',OUT/'cctv.jpg',390,255),False,False,0)
tabs=Gtk.Notebook();right.pack_start(tabs,True,True,0)
box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14);box.set_border_width(18)
box.pack_start(label('Qwen3-VL 8B'),False,False,0)
box.pack_start(label('이전 관측 · '+record['frame_received_local'],'muted'),False,False,0)
text=Gtk.Label(label=record['response']);text.set_line_wrap(True);text.set_max_width_chars(30);text.set_xalign(0);text.set_yalign(0);box.pack_start(text,True,True,0)
tabs.append_page(box,Gtk.Label(label='Qwen'));tabs.append_page(Gtk.Label(label=''),Gtk.Label(label='도구'))
root.pack_start(label('Go2 · RealSense RGB                                     CCTV                                     Qwen','muted'),False,False,0)
window.connect('destroy',Gtk.main_quit);window.show_all()
def capture():
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,window.get_allocated_width(),window.get_allocated_height());window.draw(cairo.Context(surface));surface.write_to_png(str(OUT/'trace-mockup.png'))
    (OUT/'provenance.json').write_text(json.dumps({'rgb':str(rgb),'cctv_video':str(video),'cctv_frame_index':int(count*.35),'qwen':record,'note':'Static composition. Historical Qwen response is from a different observation, not inference on the displayed RGB.'},ensure_ascii=False,indent=2))
    print(str(OUT/'trace-mockup.png'),flush=True);return False
GLib.timeout_add(1200,capture);Gtk.main()
