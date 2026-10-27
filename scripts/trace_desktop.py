#!/usr/bin/python3
"""Native GTK monitor. Read camera buffers without advancing/resetting Isaac Sim."""
import base64
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
ROOT = Path(__file__).resolve().parents[1]
REAL2SIM = os.environ.get('TRACE_SCENE', 'real2sim') == 'real2sim'
ISAAC_PORT = int(os.environ.get('TRACE_ISAAC_PORT', '8227' if REAL2SIM else '8226'))
ISAAC_CONTEXT = 'real2sim' if REAL2SIM else 'spot'
LIVE = ROOT/('artifacts/live_real2sim' if REAL2SIM else 'artifacts/live')
LIVE.mkdir(parents=True, exist_ok=True)
EVENTS = LIVE/'qwen.jsonl'
CAMERA_CODE = """
import io, base64
trace_guard()
if monitor_follow:
    monitor_position = demo.state()[0].tolist()
    aim(stage, '/World/TraceOverviewCamera',
        (monitor_position[0]+7, monitor_position[1]+6, 6),
        (monitor_position[0], monitor_position[1], .5))
elif globals().get('monitor_was_following', False):
    aim(stage, '/World/TraceOverviewCamera', (7,6,6), (0,0,.5))
monitor_was_following = monitor_follow
monitor_frames = {}
for monitor_key, monitor_array, monitor_stamp in [
    ('overview', trace_overview_rgb.get_data(), SimulationManager.get_simulation_time()),
    ('body', demo.camera.get_data('rgb')[0].numpy(), float(inspection.clock.get_data().get('simulationTime', -1))),
    ('fixed', trace_camera.get_data('rgb')[0].numpy(), float(trace_clock.get_data().get('simulationTime', -1)))]:
    monitor_buffer = io.BytesIO()
    Image.fromarray(monitor_array[:,:,:3]).save(monitor_buffer, format='JPEG', quality=80)
    monitor_frames[monitor_key] = dict(image=base64.b64encode(monitor_buffer.getvalue()).decode(),
        capture_time=monitor_stamp, width=int(monitor_array.shape[1]),height=int(monitor_array.shape[0]))
print(json.dumps(dict(frames=monitor_frames, snapshot=trace_snapshot())))
"""

def remote_request(code, args=None, timeout=8):
    with socket.create_connection(('127.0.0.1',ISAAC_PORT),timeout=4) as sock:
        sock.settimeout(timeout)
        sock.sendall(json.dumps({'context':ISAAC_CONTEXT,'code':code,'args':args or {}}).encode())
        sock.shutdown(socket.SHUT_WR)
        chunks=[]
        size=0
        while True:
            block=sock.recv(65536)
            if not block:break
            size+=len(block)
            if size>12*1024*1024:raise ValueError('Camera reply too large')
            chunks.append(block)
    result=json.loads(b''.join(chunks))
    if result.get('status')!='ok':raise RuntimeError(result.get('evalue',str(result)))
    return json.loads(result['output'].strip().splitlines()[-1])

def remote_camera(source=None, follow=False):
    if REAL2SIM:
        return remote_request('print(json.dumps(real2sim_monitor_frames()))')
    return remote_request(CAMERA_CODE, {'monitor_follow':follow})


class Window(Gtk.ApplicationWindow):
    def __init__(self,app):
        super().__init__(application=app,title='TRACE — Isaac Sim / Qwen')
        if REAL2SIM:self.set_title('TRACE — Real2Sim / Spark Qwen')
        self.set_default_size(1540,940)
        self.stop_event=threading.Event();self.source='body';self.frame=None;self.pixbuf=None
        self.worker=None;self.offset=0;self.last_frame_received=0;self.last_stamp=None
        self.follow=False;self.overview_pixbuf=None;self.thumbs={};self.raw_frames={};self.poll_times=[]
        self.connect('destroy',self.close_monitor)
        css=Gtk.CssProvider();css.load_from_data(b'''
        window {background:#13171b;color:#e1e5e9;} label {color:#d9dee3;}
        button,combobox {padding:7px;background:#283039;color:#e1e5e9;border:1px solid #47515c;}
        textview,textview text {background:#171d23;color:#dce4eb;font-family:monospace;font-size:15px;}
        .title {font-size:19px;font-weight:bold;} .muted {color:#a4afb9;font-size:12px;}
        ''');Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);root.set_border_width(16);self.add(root)
        top=Gtk.Box(spacing=12);root.pack_start(top,False,False,0)
        title=Gtk.Label(label='TRACE');title.get_style_context().add_class('title');top.pack_start(title,False,False,0)
        self.status=Gtk.Label(label='Isaac Sim 연결 중');top.pack_start(self.status,False,False,12)
        top.pack_end(Gtk.Label(label='로컬 모니터 · 시뮬레이션 전용'),False,False,0)
        panes=Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL);panes.set_position(920);self.tabs=Gtk.Notebook();root.pack_start(self.tabs,True,True,0);self.tabs.append_page(panes,Gtk.Label(label='실시간 장면 / Qwen'))
        from monitor_graph_ui import GraphTab
        self.graph_tab=GraphTab();self.tabs.append_page(self.graph_tab,Gtk.Label(label='ROS 노드 / 토픽'))
        from monitor_system_ui import SystemTab
        self.system_tab=SystemTab();self.tabs.append_page(self.system_tab,Gtk.Label(label='전체 시스템 / VSS 비교'))
        from monitor_harness_ui import HarnessTab
        self.harness_tab=HarnessTab();self.tabs.append_page(self.harness_tab,Gtk.Label(label='에이전트 실행'))
        if REAL2SIM:
            self.harness_tab.start.set_sensitive(True)
            self.harness_tab.status.set_text('Real2Sim native 하네스 · 작업자 상태 확인 요청 실행 가능')
        self.tabs.set_current_page(3)
        left=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);panes.pack1(left,True,False)
        camera_bar=Gtk.Box(spacing=10);left.pack_start(camera_bar,False,False,0)
        camera_bar.pack_start(Gtk.Label(label='전체 장면 · 분석 카메라:'),False,False,0)
        combo=Gtk.ComboBoxText();combo.append('body','로봇 몸통');combo.append('fixed','고정 카메라');combo.set_active_id('body');combo.connect('changed',self.change_source);camera_bar.pack_start(combo,False,False,0)
        follow=Gtk.CheckButton(label='로봇 따라가기');follow.connect('toggled',lambda b:setattr(self,'follow',b.get_active()));camera_bar.pack_start(follow,False,False,0)
        if REAL2SIM:follow.set_sensitive(False)
        self.analyze=Gtk.Button(label='현재 프레임 Qwen 분석');self.analyze.connect('clicked',self.analyze_frame);camera_bar.pack_end(self.analyze,False,False,0)
        if REAL2SIM:
            navigation_bar=Gtk.Box(spacing=8);left.pack_start(navigation_bar,False,False,0)
            for label,target in [('전체 순찰','patrol'),('서쪽 이동','west'),('케이지 이동','cage'),('입구 복귀','entrance'),('정지','stop'),('입구 재배치','reset')]:
                button=Gtk.Button(label=label);button.connect('clicked',lambda b,t=target:self.navigation_command(t));navigation_bar.pack_start(button,False,False,0)
        self.canvas=Gtk.DrawingArea();self.canvas.set_size_request(500,350);self.canvas.connect('draw',self.draw);left.pack_start(self.canvas,True,True,0)
        self.frame_status=Gtk.Label(label='영상 수신 대기');self.frame_status.set_xalign(0);left.pack_start(self.frame_status,False,False,0)
        self.nav_status=Gtk.Label(label='');self.nav_status.set_xalign(0);left.pack_start(self.nav_status,False,False,0)
        hint=Gtk.Label(label='전체 장면 연속 갱신 · 일시정지 시 로봇과 센서 시각 유지\n분석 버튼은 화면 프레임만 분석합니다. 사건 생성·로봇 이동을 실행하지 않습니다.');hint.set_xalign(0);hint.get_style_context().add_class('muted');left.pack_start(hint,False,False,0)
        right=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);right.set_border_width(8);panes.pack2(right,True,False)
        previews=Gtk.Box(spacing=8);right.pack_start(previews,False,False,0)
        for key,title_text in [('fixed','고정 카메라'),('body','로봇 카메라')]:
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4);previews.pack_start(box,True,True,0)
            box.pack_start(Gtk.Label(label=title_text),False,False,0)
            area=Gtk.DrawingArea();area.set_size_request(220,140);area.connect('draw',self.draw_thumb,key);box.pack_start(area,True,True,0);self.thumbs[key]=[area,None]
        label=Gtk.Label(label='Qwen3-VL 8B · 실시간 추론 출력');label.set_xalign(0);label.get_style_context().add_class('title');right.pack_start(label,False,False,0)
        self.qstatus=Gtk.Label(label='추론 대기');self.qstatus.set_xalign(0);right.pack_start(self.qstatus,False,False,0)
        self.text=Gtk.TextView();self.text.set_editable(False);self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR);self.text.set_left_margin(14);self.text.set_right_margin(14);self.text.set_top_margin(12)
        scroll=Gtk.ScrolledWindow();scroll.add(self.text);right.pack_start(scroll,True,True,0)
        self.autoscroll=Gtk.CheckButton(label='새 출력 자동 스크롤');self.autoscroll.set_active(True);right.pack_start(self.autoscroll,False,False,0)
        note=Gtk.Label(label='Ollama thinking 원문과 최종 JSON을 구분해 표시합니다.\n모델의 추론 텍스트는 사실 확인이나 사건의 최종 판정이 아닙니다.');note.set_xalign(0);note.get_style_context().add_class('muted');right.pack_start(note,False,False,0)
        self.footer=Gtk.Label(label='저장된 과거 추론을 재생하지 않습니다. 새 추론부터 표시합니다.');self.footer.set_xalign(0);root.pack_start(self.footer,False,False,0)
        if EVENTS.exists():self.offset=EVENTS.stat().st_size
        self.channel=None;self.active_evidence=None
        threading.Thread(target=self.camera_loop,daemon=True).start()
        threading.Thread(target=self.graph_loop,daemon=True).start()
        GLib.timeout_add(120,self.poll_events)
        GLib.timeout_add(1000,self.check_worker)
        self.show_all()
        self.tabs.set_current_page(0 if REAL2SIM else 3)
    def close_monitor(self,*args):
        self.stop_event.set()
        self.harness_tab.shutdown()
        if self.worker and self.worker.poll() is None:self.worker.terminate()
    def change_source(self,combo):
        self.source=combo.get_active_id();self.frame=None;self.pixbuf=None;self.last_stamp=None;self.canvas.queue_draw();self.frame_status.set_text('선택한 카메라 수신 중');self.analyze.set_sensitive(False)
    def graph_loop(self):
        if REAL2SIM:
            GLib.idle_add(self.graph_tab.error,'Real2Sim 영상 모드: ROS/Spot 이동 연결 전입니다.')
            return
        from monitor_ros import GRAPH_CODE
        while not self.stop_event.is_set():
            try:
                data=remote_request(GRAPH_CODE)
                (LIVE/'ros_graph.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
                GLib.idle_add(self.graph_tab.update,data)
            except Exception as e:GLib.idle_add(self.graph_tab.error,str(e))
            self.stop_event.wait(5)
    def camera_loop(self):
        try:
            if REAL2SIM:
                remote_request((ROOT/'scripts/real2sim_monitor_scene.py').read_text(),
                    {'real2sim_root':os.environ.get('REAL2SIM_ROOT',str(ROOT.parent/'HAI-Real2Sim'))})
                remote_request((ROOT/'scripts/real2sim_navigation.py').read_text(),
                    {'real2sim_root':os.environ.get('REAL2SIM_ROOT',str(ROOT.parent/'HAI-Real2Sim'))}, timeout=120)
            else:remote_request((ROOT/'scripts/monitor_scene.py').read_text())
        except Exception as e:GLib.idle_add(self.camera_error,str(e))
        while not self.stop_event.is_set():
            source=self.source
            try:GLib.idle_add(self.update_camera,source,remote_camera(source,self.follow))
            except Exception as e:GLib.idle_add(self.camera_error,str(e))
            self.stop_event.wait(.12 if self.tabs.get_current_page()==0 else 1)
    def navigation_command(self, target):
        def send():
            try:
                code='print(json.dumps(real2sim_navigation.stop()))' if target=='stop' else 'print(json.dumps(real2sim_navigation.navigate(target)))'
                if target=='reset':code='print(json.dumps(real2sim_navigation.reset_to_entrance()))'
                result=remote_request(code, {'target':target})
                with (LIVE/'navigation.jsonl').open('a') as log:log.write(json.dumps(dict(action=target,result=result))+'\n')
            except Exception as error:
                GLib.idle_add(self.nav_status.set_text, '이동 명령 오류: '+str(error))
        threading.Thread(target=send,daemon=True).start()

    def camera_error(self,error):
        self.status.set_text('Isaac Sim 연결/센서 오류');self.frame_status.set_text(error[:150]);self.analyze.set_sensitive(False)
        return False
    def update_camera(self,source,record):
        if source!=self.source or self.stop_event.is_set():return False
        for key,item in record['frames'].items():
            data=base64.b64decode(item['image']);loader=GdkPixbuf.PixbufLoader.new_with_type('jpeg');loader.write(data);loader.close();pix=loader.get_pixbuf()
            if key=='overview':self.overview_pixbuf=pix
            else:
                self.thumbs[key][1]=pix;self.thumbs[key][0].queue_draw()
                self.raw_frames[key]=(pix,item['capture_time'])
        self.pixbuf,self.frame=self.raw_frames[self.source][0],self.raw_frames[self.source]
        now=time.monotonic();self.last_frame_received=now;self.poll_times=(self.poll_times+[now])[-20:]
        fps=(len(self.poll_times)-1)/(now-self.poll_times[0]) if len(self.poll_times)>1 else 0
        snap=record['snapshot'];stamp=self.frame[1];stale=self.last_stamp==stamp;self.last_stamp=stamp
        self.status.set_text('Isaac Sim 실행 중' if snap['playing'] else 'Isaac Sim 일시정지')
        self.frame_status.set_text(f"화면 수신 {fps:.1f} FPS  ·  전체 장면 1280×720  ·  분석 카메라 센서 {stamp:.3f}s"+(' · 동일 센서 프레임' if stale else ''))
        if REAL2SIM:
            nav=snap.get('navigation') or {};pose=snap.get('pose')
            position=f"{pose[0]:.2f}, {pose[1]:.2f}m" if pose else '초기화 중'
            self.nav_status.set_text(f"Real2Sim · Spot {nav.get('status','연결 중')} · 위치 {position} · 남은 경유점 {nav.get('remaining',0)} · {nav.get('reason','')}")
        else:
            nav=snap.get('navigation') or {};self.nav_status.set_text(f"시뮬레이션 {snap['now']:.3f}s  |  Nav2: {nav.get('status','대기')}  |  위치: {snap['pose'][0]:.2f}, {snap['pose'][1]:.2f} m")
        self.analyze.set_sensitive(self.worker is None or self.worker.poll() is not None);self.canvas.queue_draw()
        (LIVE/'camera_status.json').write_text(json.dumps(dict(source=source,fps=fps,snapshot=snap,capture_time=stamp)))
        return False
    def draw_thumb(self,widget,cr,key):
        self.paint_image(widget,cr,self.thumbs[key][1])
    def paint_image(self,widget,cr,pix):
        cr.set_source_rgb(.035,.045,.055);cr.paint()
        if pix:
            w,h=widget.get_allocated_width(),widget.get_allocated_height();pw,ph=pix.get_width(),pix.get_height();scale=min(w/pw,h/ph)
            cr.save();cr.translate((w-pw*scale)/2,(h-ph*scale)/2);cr.scale(scale,scale);Gdk.cairo_set_source_pixbuf(cr,pix,0,0);cr.paint();cr.restore()
    def draw(self,widget,cr):
        self.paint_image(widget,cr,self.overview_pixbuf)
    def analyze_frame(self,*args):
        if not self.frame or time.monotonic()-self.last_frame_received>5:return
        if REAL2SIM and not self.spark_ready():
            self.footer.set_text('Spark SSH 터널(127.0.0.1:11435) 연결이 필요합니다.')
            return
        # Freeze the exact displayed evidence; subsequent polling cannot overwrite it.
        path=LIVE/f'preview-{time.time_ns()}.png';self.frame[0].savev(str(path),'png',[],[]);self.analyze.set_sensitive(False)
        self.worker=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/vlm_stream.py'),str(path),str(self.frame[1])],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.footer.set_text('선택한 화면 프레임 분석 중 · 사건 정책에는 전달되지 않습니다.')
    def check_worker(self):
        if self.stop_event.is_set():return False
        if self.worker and self.worker.poll() is not None:
            code=self.worker.returncode;self.worker=None;self.footer.set_text('프레임 분석 완료' if code==0 else '프레임 분석 실패 — 추론 상태 확인');self.analyze.set_sensitive(bool(self.frame))
        if REAL2SIM and self.worker is None:
            ready = self.spark_ready()
            if ready != getattr(self, '_spark_was_ready', None):
                self.footer.set_text('영상 연결됨 · Spark 터널 연결됨 · 현재 프레임 Qwen 분석 가능' if ready else
                    '영상 연결됨 · Spark SSH 터널(127.0.0.1:11435) 연결 대기')
            self._spark_was_ready = ready
        return True
    @staticmethod
    def spark_ready():
        with socket.socket() as sock:
            sock.settimeout(.1)
            return sock.connect_ex(('127.0.0.1',11435)) == 0
    def append(self,text):
        buf=self.text.get_buffer();buf.insert(buf.get_end_iter(),text)
        if self.autoscroll.get_active():self.text.scroll_to_iter(buf.get_end_iter(),0,False,0,1)
    def poll_events(self):
        if self.stop_event.is_set():return False
        try:
            if not EVENTS.exists():return True
            if EVENTS.stat().st_size<self.offset:self.offset=0
            with EVENTS.open('rb') as f:
                f.seek(self.offset)
                for _ in range(200):
                    line=f.readline()
                    if not line or not line.endswith(b'\n'):break
                    self.offset=f.tell();event=json.loads(line)
                    kind=event['type']
                    if kind=='start':
                        self.active_evidence=event.get('evidence_id')
                    elif event.get('evidence_id')!=self.active_evidence:
                        continue
                    if kind=='start':
                        self.text.get_buffer().set_text('');self.channel=None;self.qstatus.set_text('추론 중 · '+event['evidence_id'][:8])
                    elif kind in ('thinking','content','result'):
                        if self.channel!=kind:
                            self.append('\n\n'+{'thinking':'[추론 텍스트 / thinking]','content':'[최종 응답 / content]','result':'[스키마 검증 결과]'}[kind]+'\n');self.channel=kind
                        self.append(event['text'])
                        if kind=='result':self.qstatus.set_text('검증 결과: '+event['status'])
                    elif kind=='done':self.qstatus.set_text('모델 출력 완료 · 스키마 검증/정책 판정은 별도')
                    elif kind=='error':self.qstatus.set_text('추론 오류');self.append('\n[오류] '+event.get('text',''))
        except Exception as e:self.qstatus.set_text('추론 로그 읽기 오류: '+str(e)[:80])
        return True

class App(Gtk.Application):
    def __init__(self):super().__init__(application_id='local.trace.monitor.real2sim' if REAL2SIM else 'local.trace.monitor')
    def do_activate(self):
        if self.get_active_window():self.get_active_window().present()
        else:Window(self)
if __name__=='__main__':
    import signal
    app=App()
    def quit_app():
        for window in app.get_windows():window.close_monitor()
        app.quit();return False
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,quit_app)
    app.run()
