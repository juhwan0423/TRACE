"""Code-reviewed system architecture and documentation-only VSS comparison."""
import json
import subprocess
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GdkPixbuf
ROOT=Path(__file__).resolve().parents[1]
STYLE='''rankdir=LR; bgcolor="#13171b"; pad="0.3"; nodesep="0.35"; ranksep="0.6";
node [shape=box,style="rounded,filled",fillcolor="#273340",color="#61738a",fontcolor="#e1e5e9",fontname="sans-serif",fontsize=13];
edge [color="#82b6bd",fontcolor="#c7d9df",fontname="sans-serif",fontsize=10];'''
SYSTEM='digraph System {'+STYLE+'''
subgraph cluster_sim {label="Isaac Sim process";fontcolor="#bdd4ea";color="#42566a";
 sim [label="Isaac Sim 6.2\nScene / physics / Spot policy"];
 sensor [label="Fixed + body RGB\nSensor timestamp"];
 bridge [label="haiclaw_spot_bridge\nrclpy + Nav2Inspection"];
 sim -> sensor [label="render"];
 bridge -> sim [label="velocity lease / locomotion"];
 sim -> bridge [label="pose / collision rays"];
}
subgraph cluster_trace {label="TRACE Python process";fontcolor="#bdd4ea";color="#42566a";
 runner [label="run_closed_loop.py\nFixed workflow executor"];
 core [label="LossTracker / ClosedLoop\nIncident / evidence gate"];
 adapter [label="SingleFrameVLM / Ollama adapter\nSchema + evidence ID validation"];
 runner -> core [label="observation / motion / tick"];
 core -> adapter [label="post-arrival evidence"];
 runner -> adapter [label="initial / lost-frame inference"];
 adapter -> core [label="validated observation"];
}
nav [label="Nav2 container / ROS 2 Jazzy\nplanner / controller / costmaps",fillcolor="#29453e"];
qwen [label="Ollama :11434\nQwen3-VL 8B / local GPU",fillcolor="#423a50"];
ui [label="GTK Monitor\nscene / ROS graph / reasoning"];
files [label="Local artifacts\nresult.json / qwen.jsonl",shape=folder];
runner -> bridge [label="TCP :8226\ninspection.start / snapshot"];
sensor -> runner [label="TCP :8226 metadata\nPNG file read locally"];
bridge -> nav [label="NavigateToPose action\n/scan /odom /tf /clock"];
nav -> bridge [label="action result\n/plan /cmd_vel"];
adapter -> qwen [label="HTTP /api/chat\nbase64 RGB + prompt + schema"];
qwen -> adapter [label="NDJSON thinking + content"];
runner -> files [label="audit / events"];
adapter -> files [label="stream events"];
files -> ui [label="local file tail"];
sim -> ui [label="TCP :8226\nJPEG overview + sensor frames",style=dashed];
bridge -> ui [label="DDS graph read via TCP",style=dashed];
}'''
TOOLS='digraph Tools {'+STYLE+'''
runner [label="Python executor\npredefined sequence",fillcolor="#29453e"];
setup [label="trace_present / trace_occlude\nexperiment scenario only\ntruth excluded from model"];
capture [label="trace_capture\nRGB + sensor timestamp"];
move [label="inspection.start / cancel\nNavigateToPose / bounded stop"];
observe [label="trace_snapshot\npose / arrival / simulation clock"];
vlm [label="adapter.infer\nQwen observation JSON"];
policy [label="IncidentVLM + Incident\nfreshness / limitations / deadline"];
result [label="resolved_safe / danger_confirmed\nescalated_unknown\n(policy states, not all live-tested)"];
runner -> setup [label="fixed call"];
runner -> capture [label="fixed call"];
runner -> move [label="on observed loss"];
runner -> observe [label="poll"];
capture -> vlm [label="one frame"];
vlm -> policy [label="validated evidence"];
observe -> policy [label="arrival / tick"];
policy -> result [label="rules"];
missing [label="NOT IMPLEMENTED\nLLM planner / autonomous tool selection\nMCP tool server / adaptive viewpoints\nvideo memory / multi-agent runtime",style="rounded,dashed",fillcolor="#28252a",color="#af8b8b"];
vlm -> missing [style=dashed,arrowhead=none,label="no tool calls from Qwen"];
}'''
VSS='digraph Compare {'+STYLE+'''
subgraph cluster_current {label="TRACE - implemented";fontcolor="#bcd5e7";color="#4d6174";
 c1 [label="RGB still frame"];c2 [label="Qwen3-VL\nsingle-frame inference"];c3 [label="Evidence / deadline rules"];c4 [label="Nav2 active inspection"];
 c1 -> c2 -> c3;c3 -> c4 [label="fixed inspection step"];c4 -> c1 [label="new body frame"];
}
subgraph cluster_vss {label="NVIDIA VSS 3.3 - documentation reference / NOT deployed";fontcolor="#c8d8b7";color="#64764d";
 v1 [label="Video input / VST"];
 v2 [label="RT-CV / RT-VLM / embeddings\nprofile-dependent components"];
 v3 [label="Analytics / alert verification\nincidents / storage"];
 v4 [label="MCP tools\nclips / snapshots / search"];
 v5 [label="Top Agent / report agents"];
 v1 -> v2 -> v3;v3 -> v4 -> v5;v5 -> v4 [label="tool requests"];
}
}'''
HARNESS='digraph Harness {'+STYLE+"""
state [label="Episode state / bounded memory\\nobservations + outcomes + remaining budget"];
planner [label="Qwen3-VL 8B text planner\\nselect next tool + concise rationale",fillcolor="#423a50"];
gate [label="Harness action validation\\nallowlist / target / repeats / step budget"];
tools [label="observe / inspect / wait / stop / escalate\\nLiveTools: Isaac + Nav2 + VLM",fillcolor="#29453e"];
policy [label="Host-owned evidence policy\\nfreshness / generation / uncertainty"];
clock [label="Independent sim deadline + wall watchdog"];
end [label="Policy terminal state / local handoff"];
state -> planner [label="context + available tools"];
planner -> gate [label="structured action"];
gate -> tools [label="validated dispatch"];
gate -> state [label="invalid action feedback"];
tools -> policy [label="new evidence"];
tools -> state [label="success / failure / timeout"];
policy -> state [label="unresolved: replan"];
policy -> end [label="sufficient evidence"];
clock -> end [label="budget expired: unresolved"];
clock -> tools [label="cancel + hold"];
}"""
HARNESS_TEXT="""TRACE harness v1 — 모델 선택/도구 실행 루프

Qwen이 현재 상태·관측·실패 이력·남은 예산을 읽고 다음 도구를 선택합니다. Python 하네스는 출력과 대상이 허용됐는지 검증한 뒤 실행합니다. 결과를 다시 모델에 전달해 재계획합니다.

구현된 도구
observe(fixed/body): 새 프레임 VLM 관측
inspect(등록된 지점): Nav2 이동
wait: 짧은 재관측 대기
stop: 이동 취소/정지
escalate: 미확인 로컬 인계 요청

도구 출력에 시나리오 정답/사람 좌표는 없습니다. 임의 Python·좌표·ROS 명령은 모델이 실행할 수 없습니다. 모델이 safe/danger를 직접 선언하지 않습니다.

구현 범위
실제 로컬 Qwen planner + 사건별 기억 + 도구 dispatch + 재계획 + 기한/중단 + 감사 로그.
MCP 서버와 다중 에이전트는 아직 없습니다. 한 모델이 planning/vision 역할을 별도 호출로 수행합니다. 고정 후보 위치에서 선택하며 자유 공간 탐색은 아닙니다.

검증 구분
실제 Qwen + fixture 도구로 이동 실패 후 대체 지점 선택을 검증했습니다. 실제 Isaac에서 모델 선택8회, 첫 지점 도착, 두 번째 이동 실패 후 재관측, 전체 예산 종료·hold를 확인했습니다. 결과는 미확인 인계였습니다. 이후 도착 후 관측 사전조건을 보완했고 테스트/실제 모델 probe로 확인했습니다. baseline 대비 성능 개선은 아직 미검증입니다.

실행: 에이전트 실행 탭의 하네스 실험 시작.
기존 run_closed_loop.py는 고정 순서 baseline으로 보존합니다."""
SYSTEM_TEXT='''현재 구현된 통신

① Isaac Sim ↔ 실행기: localhost TCP 8226 Python Server. 실행기는 캡처·이동·스냅샷 함수를 호출합니다. 영상 파일은 로컬에서 읽습니다.

② Isaac Sim ↔ Nav2: ROS 2 / DDS, DOMAIN 173. NavigateToPose action과 /scan, /odom, /tf, /clock, /plan, /cmd_vel을 사용합니다. 세부 실제 endpoint는 ROS 탭에서 확인합니다.

③ TRACE adapter ↔ Qwen: Ollama HTTP :11434 /api/chat. RGB·시각·근거 ID를 입력하고 JSON을 검증합니다. Qwen이 ROS에 직접 명령하지 않습니다.

④ 모니터: 전체 장면과 두 카메라를 TCP로 읽고, qwen.jsonl을 표시합니다. 점선은 표시/관찰 경로입니다.

이 그림은 소스 검토에 따른 구성도이며 프로세스가 모두 실행 중이라는 표시가 아닙니다.

대표 코드
scripts/run_closed_loop.py
scripts/nav2_inspection.py
scripts/spot_ros_bridge.py
src/haiclaw/closed_loop.py
src/haiclaw/providers/ollama.py'''
TOOLS_TEXT='''현재 자동화 수준

정해진 Python 실행기 + 규칙 기반 사건 상태 머신 + VLM 관측 공급자입니다. Qwen이 계획을 세우거나 다음 도구를 선택하는 자율 에이전트는 아직 없습니다.

도구에 해당하는 함수
• trace_capture: 새 RGB 확보
• inspection.start/cancel: 이동 / 정지
• trace_snapshot: 시각 / 자세 / 이동 상태
• adapter.infer: 제한된 관측 JSON
• Incident.tick: 기한 및 종료 규칙

이들은 Python 호출이며 MCP에 등록된 LLM 도구가 아닙니다. Nav2 behavior tree와 보행 정책도 LLM 에이전트와 구분합니다.

아직 없는 부분
• 관측 부족 → 다른 위치/카메라/시간 구간 선택
• 목표 기반 LLM planner / tool calling
• 영상 기억·검색 / 다중 에이전트 협업

시나리오 생성 함수는 평가용입니다. 시나리오 정답과 사람 좌표는 모델 입력에 전달하지 않습니다.

이 UI를 만든 개발용 AI 도구와 TRACE 실행 중의 에이전트 구조는 별개입니다.'''
VSS_TEXT='''비교 범위: 공식 VSS 3.3 문서 / 미설치·미연결·미측정

TRACE: 한 프레임 관측 + 사건 근거 규칙 + 로봇의 추가 관측 이동.
VSS: 영상 입력, CV/VLM/임베딩, 분석·알림 검증, 검색/클립 도구, 보고 에이전트의 모듈 구성. 프로필에 따라 일부만 사용합니다.

VSS의 Direct Video Analysis는 영상 업로드 분석 경로를 제공합니다. Agent는 MCP 기반 도구 및 보고 작업을 사용할 수 있습니다. TRACE의 Nav2 이동을 그대로 대신한다고 볼 근거는 없습니다.

이 장비와의 비교
공식 blueprint는 DGX Spark를 core engine 지원 하드웨어에 포함합니다. 그러나 사용할 프로필·모델·ARM64 이미지와 Isaac Sim 동시 실행 메모리 여유는 별도 확인해야 합니다.

VSS가 더 빠르다는 실측은 없습니다. chunk 대기·VLM 추론·검색·보고 시간은 각각 측정해야 합니다.

독립 비교 실험 제안 (미실행)
A. 동일 저장 영상의 동일 시각 프레임 → 현재 Qwen
B. 동일 저장 영상/구간 → VSS 영상 분석 또는 alert verification
모델이 다르면 모델+구성 비교로 명시합니다. 정책 효과와 모델 효과를 분리합니다.
정상 작업 / 누운 자세 / 가림 / 저화질을 반복하고, 첫 유효 판단 wall latency p50/p95, 오탐·미탐·판단불가, 처리량, GPU 메모리를 기록합니다. 타임아웃도 제외하지 않습니다.

미측정 값은 N/A입니다. 현재 3회 요청의 지연과 VSS의 광고 수치를 성능 순위로 비교하지 않습니다.'''

class SystemTab(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=10);self.set_border_width(12);self.pixbuf=None
        bar=Gtk.Box(spacing=10);self.pack_start(bar,False,False,0)
        self.mode=Gtk.ComboBoxText()
        for name in ['TRACE 하네스','Baseline 전체 연결','Baseline 도구 구성','NVIDIA VSS 비교']:self.mode.append_text(name)
        self.mode.set_active(0);self.mode.connect('changed',self.refresh);bar.pack_start(self.mode,False,False,0)
        bar.pack_start(Gtk.Label(label='코드 기준 구성도 · VSS는 문서 비교만'),False,False,0)
        self.zoom=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,.3,1.4,.1);self.zoom.set_value(.8);self.zoom.set_size_request(180,-1);self.zoom.connect('value-changed',self.scale);bar.pack_end(self.zoom,False,False,0)
        split=Gtk.Paned();split.set_position(950);self.pack_start(split,True,True,0)
        self.image=Gtk.Image();self.image.set_halign(Gtk.Align.START);self.image.set_valign(Gtk.Align.START)
        sc=Gtk.ScrolledWindow();sc.add(self.image);split.pack1(sc,True,False)
        self.text=Gtk.TextView();self.text.set_editable(False);self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR);self.text.set_left_margin(12);self.text.set_right_margin(12)
        textsc=Gtk.ScrolledWindow();textsc.set_min_content_width(380);textsc.add(self.text);split.pack2(textsc,True,False)
        self.latency=Gtk.Label();self.latency.set_xalign(0);self.latency.set_line_wrap(True);self.pack_start(self.latency,False,False,0)
        try:
            run=json.loads((ROOT/'artifacts/closed_loop/263c92fc-bb26-492b-869d-d822a8e2e2ab/result.json').read_text())
            vals=[o['inference']['latency_wall_seconds'] for o in run['observations']]+[run['audit'][0]['inference']['latency_wall_seconds']]
            self.latency.set_text('기존 실행 263c92fc · Qwen wall latency: 초기 %.1fs / 소실 %.1fs / 후속 %.1fs\n원인별 프로파일링 전: 초기 관측은 순차 대기, 단일 프레임, think=True·출력 최대4096토큰. 사건 예산70초는 simulation clock이며 wall latency와 직접 비교 불가.'%tuple(vals))
        except Exception:self.latency.set_text('기존 실행 지연 기록을 읽을 수 없습니다.')
        links=Gtk.Box(spacing=10);self.pack_start(links,False,False,0)
        for title,url in [('VSS 아키텍처','https://docs.nvidia.com/vss'),('VSS Agent','https://docs.nvidia.com/vss/vision-agent/vss-agents/agent-overview'),('지원 하드웨어','https://build.nvidia.com/nvidia/video-search-and-summarization/blueprintcard')]:links.pack_start(Gtk.LinkButton.new_with_label(url,title),False,False,0)
        self.refresh()
    def refresh(self,*args):
        idx=self.mode.get_active();self.text.get_buffer().set_text([HARNESS_TEXT,SYSTEM_TEXT,TOOLS_TEXT,VSS_TEXT][idx])
        try:
            r=subprocess.run(['dot','-Tpng'],input=[HARNESS,SYSTEM,TOOLS,VSS][idx].encode(),capture_output=True,check=True,timeout=8)
            loader=GdkPixbuf.PixbufLoader.new_with_type('png');loader.write(r.stdout);loader.close();self.pixbuf=loader.get_pixbuf();self.scale()
        except Exception as e:self.text.get_buffer().set_text('구성도 렌더 실패: '+str(e))
    def scale(self,*args):
        if self.pixbuf:
            z=self.zoom.get_value();self.image.set_from_pixbuf(self.pixbuf.scale_simple(max(1,int(self.pixbuf.get_width()*z)),max(1,int(self.pixbuf.get_height()*z)),GdkPixbuf.InterpType.BILINEAR))
