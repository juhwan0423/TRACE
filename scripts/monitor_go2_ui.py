"""Go2 read-only continuous RealSense stream over an authenticated SSH channel."""
import base64
import json
import subprocess
import threading
import time
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, GdkPixbuf

REMOTE = r'''
import cv2, json, base64, time, pathlib, shlex, urllib.request
cfg={}
for line in pathlib.Path('/home/unitree/go2_bridge_project/config/bridge.env').read_text().splitlines():
    words=shlex.split(line, comments=True)
    if words and words[0]=='export': words=words[1:]
    if words and '=' in words[0]:
        k,v=words[0].split('=',1);cfg[k]=v
url='http://%s:%s/state'%(cfg.get('BRIDGE_HOST','127.0.0.1'),cfg.get('BRIDGE_PORT','8765'))
cap=cv2.VideoCapture(4,cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,640);cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
cap.set(cv2.CAP_PROP_FPS,30);cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
last_state=0;last_sent=0;state={}
try:
    while cap.isOpened():
        ok,frame=cap.read()
        if not ok: raise RuntimeError('RealSense frame unavailable')
        now=time.monotonic()
        if now-last_sent<0.1: continue
        last_sent=now
        if now-last_state>1:
            try:
                req=urllib.request.Request(url,headers={'X-Bridge-Token':cfg['BRIDGE_TOKEN']})
                with urllib.request.urlopen(req,timeout=1) as r: state=json.load(r)
            except Exception: state={'error':'state request failed'}
            last_state=now
        ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,75])
        if ok: print(json.dumps({'image':base64.b64encode(jpeg).decode(),'state':state}),flush=True)
finally: cap.release()
'''

class Go2Tab(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        self.set_border_width(16);self.process=None;self.latest=None;self.last=0;self.count=0;self.closed=False
        self.status=Gtk.Label(label='Go2 Jetson RealSense · 연결 대기');self.pack_start(self.status,False,False,0)
        layout=Gtk.Box(spacing=18);self.pack_start(layout,True,True,0)
        left=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);layout.pack_start(left,True,True,0)
        left.pack_start(Gtk.Label(label='GO2 / REALSENSE RGB · LIVE'),False,False,0)
        self.image=Gtk.Image();left.pack_start(self.image,True,True,0)
        right=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14);right.set_size_request(360,-1);layout.pack_start(right,False,False,0)
        cctv=Gtk.Frame(label='CCTV · 연결 예정');cctv.set_size_request(360,220)
        cctv.add(Gtk.Label(label='영상 소스 미연결'));right.pack_start(cctv,False,False,0)
        notebook=Gtk.Notebook();right.pack_start(notebook,True,True,0)
        qwen=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16);qwen.set_border_width(18)
        qwen.pack_start(Gtk.Label(label='Qwen3-VL · 관측 / 도구 제안'),False,False,0)
        note=Gtk.Label(label='UI 목업 · Go2 영상 추론 미연결\n\n새 관측을 기다리는 영역입니다.\n모델 출력과 도구 제안은 아직 없습니다.');note.set_line_wrap(True);qwen.pack_start(note,True,True,0)
        action=Gtk.Button(label='현재 프레임 분석 · 연결 예정');action.set_sensitive(False);qwen.pack_start(action,False,False,0)
        notebook.append_page(qwen,Gtk.Label(label='Qwen'))
        tools=Gtk.Label(label='도구 실행 미연결\n\n자동 이동 비활성');notebook.append_page(tools,Gtk.Label(label='도구 기록'))
        self.details=Gtk.Label(label='');self.pack_start(self.details,False,False,0)
        bar=Gtk.Box(spacing=12);self.pack_start(bar,False,False,0)
        self.button=Gtk.Button(label='스트림 연결');self.button.connect('clicked',self.start);bar.pack_start(self.button,False,False,0)
        stop=Gtk.Button(label='스트림 종료');stop.connect('clicked',lambda *_:self.shutdown());bar.pack_start(stop,False,False,0)
        bar.pack_start(Gtk.Label(label='RealSense RGB · 640×480 · 최대 10fps · 상태 조회 전용'),False,False,0)
        GLib.timeout_add(100,self.poll)
    def start(self,*_):
        if self.process and self.process.poll() is None:return
        self.closed=False;self.last=0;self.latest=None;self.count=0
        self.status.set_text('Tailscale SSH 연결 중…')
        self.process=subprocess.Popen(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2','unitree@100.114.58.53','python3 -u -'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        self.process.stdin.write(REMOTE);self.process.stdin.close()
        threading.Thread(target=self.receive,args=(self.process,),daemon=True).start()
    def receive(self,proc):
        try:
            for line in proc.stdout:
                data=json.loads(line)
                if proc is self.process:
                    self.latest=data;self.last=time.monotonic();self.count+=1
        finally: proc.stdout.close();proc.wait()
    def poll(self):
        if self.closed:return True
        age=time.monotonic()-self.last if self.last else float('inf')
        data=self.latest;self.latest=None
        if data:
            loader=GdkPixbuf.PixbufLoader.new_with_type('jpeg');loader.write(base64.b64decode(data['image']));loader.close();self.image.set_from_pixbuf(loader.get_pixbuf())
            s=data['state'];v=s.get('state') or {}
            self.details.set_text('mode: %s · error_code: %s · moving: %s · 상태 age_s: %s'%(v.get('mode'),v.get('error_code'),s.get('moving'),s.get('age_s',s.get('error'))))
        if self.last:self.status.set_text(('수신 중' if age<3 else '영상 지연 / 연결 확인 필요')+' · %d 프레임 · 마지막 수신 %.1f초 전'%(self.count,age))
        if self.process and self.process.poll() is not None:self.status.set_text('연결 종료 · 스트림 연결 버튼으로 다시 연결')
        return True
    def shutdown(self):
        self.closed=True
        if self.process and self.process.poll() is None:self.process.terminate()
        self.status.set_text('스트림 종료');self.image.clear()

if __name__=='__main__':
    window=Gtk.Window(title='TRACE · Go2 실시간');window.set_default_size(1120,760)
    from gi.repository import Gdk
    css=Gtk.CssProvider();css.load_from_data(b'window {background:#131b24;} label {color:#dae5ef;} notebook, frame {background:#1d2936;} button {padding:10px;}')
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    tab=Go2Tab();window.add(tab)
    window.connect('destroy',lambda *_:(tab.shutdown(),Gtk.main_quit()))
    import signal
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,lambda: (tab.shutdown(),Gtk.main_quit(),False)[-1])
    window.show_all();tab.start()
    def capture_mockup():
        if tab.count<20:return True
        import cairo
        from pathlib import Path
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,window.get_allocated_width(),window.get_allocated_height())
        window.draw(cairo.Context(surface))
        path=Path(__file__).resolve().parents[1]/'docs/assets/go2-live-qwen-mockup.png'
        surface.write_to_png(str(path));return False
    import sys
    if '--capture-mockup' in sys.argv:GLib.timeout_add(1000,capture_mockup)
    Gtk.main()
