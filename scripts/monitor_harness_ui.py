"""Native UI for model decisions and tool execution; does not invent agent steps."""
import json
import os
from pathlib import Path
import signal
import subprocess
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
ROOT=Path(__file__).resolve().parents[1]

class HarnessTab(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=10);self.set_border_width(12)
        self.process=None;self.logfile=None;self.offset=0
        bar=Gtk.Box(spacing=10);self.pack_start(bar,False,False,0)
        self.mode=Gtk.ComboBoxText();self.mode.append('live','실제 Isaac + Qwen');self.mode.append('fixture','도구 fixture + Qwen');self.mode.set_active_id('live');bar.pack_start(self.mode,False,False,0)
        self.start=Gtk.Button(label='하네스 실험 시작');self.start.connect('clicked',self.launch);bar.pack_start(self.start,False,False,0)
        self.stop=Gtk.Button(label='내 실행 중단');self.stop.connect('clicked',self.cancel);self.stop.set_sensitive(False);bar.pack_start(self.stop,False,False,0)
        self.status=Gtk.Label(label='실행 기록 대기');self.status.set_xalign(0);self.pack_start(self.status,False,False,0)
        note=Gtk.Label(label='Real2Sim 실제 모드는 현재 장면에서 운영자 요청에 따른 작업자 상태 확인을 시작합니다.\n이후 카메라·이동·대기·인계는 모델이 선택하며, 종료 판정은 근거 규칙이 검증합니다. LangGraph 없는 native 하네스 · 동시 실행 불가.');note.set_xalign(0);self.pack_start(note,False,False,0)
        self.view=Gtk.TextView();self.view.set_editable(False);self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR);self.view.set_left_margin(14);self.view.set_right_margin(14)
        sc=Gtk.ScrolledWindow();sc.add(self.view);self.pack_start(sc,True,True,0)
        self.footer=Gtk.Label(label='기록의 fixture/live 구분은 실행 결과 JSON을 기준으로 확인하세요.');self.footer.set_xalign(0);self.pack_start(self.footer,False,False,0)
        GLib.timeout_add(200,self.poll)
    def launch(self,*args):
        if self.process and self.process.poll() is None:return
        mode=self.mode.get_active_id();path=ROOT/'artifacts/logs/harness-desktop.log';self.logfile=path.open('a')
        real2sim=os.environ.get('TRACE_SCENE','real2sim')=='real2sim' and mode=='live'
        command=[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_real2sim_harness.py')] if real2sim else [str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_harness.py'),'--mode',mode,'--planner','ollama']
        self.event_path=ROOT/('artifacts/live_real2sim/harness.jsonl' if real2sim else 'artifacts/live/harness.jsonl')
        self.process=subprocess.Popen(command,cwd=ROOT,stdout=self.logfile,stderr=subprocess.STDOUT)
        self.start.set_sensitive(False);self.stop.set_sensitive(True);self.status.set_text('시작 요청: '+mode+' · 초기 관측 중에는 Qwen 탭 확인')
    def cancel(self,*args):
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGINT);self.status.set_text('중단 요청 · 도구 정지/기록 저장 대기')
    def shutdown(self):self.cancel()
    def append(self,text):
        buf=self.view.get_buffer();buf.insert(buf.get_end_iter(),text+'\n')
        if buf.get_char_count()>150000:buf.delete(buf.get_start_iter(),buf.get_iter_at_offset(50000))
        self.view.scroll_to_iter(buf.get_end_iter(),0,False,0,1)
    def poll(self):
        if self.process and self.process.poll() is not None:
            self.footer.set_text('실행 프로세스 종료 코드 '+str(self.process.returncode)+' · 상세: artifacts/logs/harness-desktop.log / artifacts/harness' )
            self.process=None;self.start.set_sensitive(True);self.stop.set_sensitive(False)
            if self.logfile:self.logfile.close();self.logfile=None
        path=getattr(self,'event_path',ROOT/('artifacts/live_real2sim/harness.jsonl' if os.environ.get('TRACE_SCENE','real2sim')=='real2sim' else 'artifacts/live/harness.jsonl'))
        if not path.exists():return True
        try:
            if path.stat().st_size<self.offset:self.offset=0
            with path.open('rb') as f:
                f.seek(self.offset)
                for _ in range(100):
                    line=f.readline()
                    if not line or not line.endswith(b'\n'):break
                    self.offset=f.tell();e=json.loads(line);kind=e['kind']
                    if kind in ('opened','bootstrap'):
                        self.append('\n━━ '+e.get('mode','mode: 결과 JSON 확인')+' / '+e['episode']+' ━━')
                        self.status.set_text(e.get('stage','사건 시작'))
                    if kind=='planning':
                        c=e['context'];self.status.set_text('모델 행동 선택 중 · 남은 simulation %.1fs'%c['remaining_sim_seconds'])
                        self.append('계획 요청: '+', '.join(t['tool']+':'+t['target'] for t in c['available_tools']))
                    elif kind=='decision':
                        a=e['action'];self.append('선택 → '+a['tool']+'('+a['target']+')\n근거: '+a['reason']);self.status.set_text('선택: '+a['tool']+' '+a['target'])
                    elif kind in ('tool_result','rejected','planner_error','terminal','aborted','stop_failed','finished'):
                        self.append(json.dumps({k:v for k,v in e.items() if k not in ('episode','wall_elapsed')},ensure_ascii=False))
                        if kind=='finished':self.status.set_text('실행 종료: '+str(e.get('state'))+' · completed='+str(e['completed']))
        except Exception as err:self.status.set_text('기록 읽기 실패: '+str(err)[:100])
        return True
