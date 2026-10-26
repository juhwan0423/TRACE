"""Native ROS graph tab: discovered endpoints, explicit publisher/topic/subscriber edges."""
import json
import subprocess
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk, GdkPixbuf, GLib
from monitor_ros import CORE, graph_dot

class GraphTab(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL,spacing=10)
        self.set_border_width(12);self.data=None;self.pixbuf=None;self.selected=None
        bar=Gtk.Box(spacing=10);self.pack_start(bar,False,False,0)
        self.status=Gtk.Label(label='ROS graph 탐색 중');bar.pack_start(self.status,False,False,0)
        self.all_topics=Gtk.CheckButton(label='전체 토픽');self.all_topics.connect('toggled',self.refresh);bar.pack_end(self.all_topics,False,False,0)
        self.search=Gtk.SearchEntry();self.search.set_placeholder_text('토픽 이름 검색');self.search.connect('search-changed',self.refresh);bar.pack_end(self.search,False,False,0)
        split=Gtk.Paned();split.set_position(340);self.pack_start(split,True,True,0)
        sidebar=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);split.pack1(sidebar,False,False)
        self.store=Gtk.ListStore(str,int,int);self.tree=Gtk.TreeView(model=self.store)
        for i,label in enumerate(['토픽','Pub','Sub']):self.tree.append_column(Gtk.TreeViewColumn(label,Gtk.CellRendererText(),text=i))
        self.tree.get_selection().connect('changed',self.select)
        sc=Gtk.ScrolledWindow();sc.set_min_content_width(320);sc.add(self.tree);sidebar.pack_start(sc,True,True,0)
        reset=Gtk.Button(label='선택 해제 · 전체 연결 보기');reset.connect('clicked',self.reset);sidebar.pack_start(reset,False,False,0)
        self.detail=Gtk.TextView();self.detail.set_editable(False);self.detail.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        details=Gtk.ScrolledWindow();details.set_min_content_height(220);details.add(self.detail);sidebar.pack_start(details,False,True,0)
        right=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);split.pack2(right,True,False)
        controls=Gtk.Box(spacing=8);right.pack_start(controls,False,False,0)
        controls.pack_start(Gtk.Label(label='사각형: ROS 노드   타원: 토픽   →: 발행 / 구독'),False,False,0)
        self.zoom=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,.3,1.5,.1);self.zoom.set_value(.8);self.zoom.set_size_request(180,-1);self.zoom.connect('value-changed',self.scale);controls.pack_end(self.zoom,False,False,0)
        self.image=Gtk.Image();self.image.set_halign(Gtk.Align.START);self.image.set_valign(Gtk.Align.START)
        scroll=Gtk.ScrolledWindow();scroll.add(self.image);right.pack_start(scroll,True,True,0)
        note=Gtk.Label(label='카메라 → Qwen: Python 카메라 버퍼 / localhost HTTP (ROS 토픽 아님)\n화살표는 DDS에서 발견한 연결 구조입니다. 메시지 전송량·Hz를 뜻하지 않습니다. 약 5초마다 갱신.');note.set_xalign(0);self.pack_start(note,False,False,0)
    def update(self,data):
        unchanged=self.data is not None and self.data['nodes']==data['nodes'] and self.data['topics']==data['topics']
        self.data=data;self.status.set_text(f"ROS_DOMAIN_ID {data['domain']} · 노드 {len(data['nodes'])} · 토픽 {len(data['topics'])} · "+__import__('time').strftime('%H:%M:%S 갱신'))
        if not unchanged:self.refresh()
        return False
    def error(self,text):
        self.status.set_text('ROS 탐색 실패 · 이전 그래프 유지: '+text[:100]);return False
    def reset(self,*args):
        self.tree.get_selection().unselect_all();self.selected=None;self.refresh()
    def select(self,selection):
        model,it=selection.get_selected();self.selected=model[it][0] if it else None
        self.render()
    def refresh(self,*args):
        if not self.data:return
        query=self.search.get_text().strip().lower();all_topics=self.all_topics.get_active()
        self.visible=[t for t in self.data['topics'] if (all_topics or t['name'] in CORE or query) and query in t['name'].lower()]
        previous=self.selected
        # Avoid re-rendering on intermediate selection changes while refilling rows.
        self.store.clear()
        for t in self.visible:self.store.append([t['name'],len(t['publishers']),len(t['subscribers'])])
        self.selected=previous if any(t['name']==previous for t in self.visible) else None
        self.render()
    def render(self):
        if not self.data:return
        topics=[t for t in self.visible if not self.selected or t['name']==self.selected]
        if self.selected and topics:
            t=topics[0];lines=[t['name'],'\n'.join(t['types'])]
            for field,label in [('publishers','발행 노드'),('subscribers','구독 노드')]:
                lines.append('\n'+label)
                for e in t[field]:lines.append(e['node']+'\n  QoS reliability='+e['reliability']+' durability='+e['durability'])
            self.detail.get_buffer().set_text('\n'.join(lines))
        else:self.detail.get_buffer().set_text('토픽을 선택하면 실제 발행·구독 노드와 타입, QoS를 볼 수 있습니다.\n\n기본 화면: /scan, /odom, /plan, /cmd_vel\n전체 토픽 또는 검색으로 TF·clock·Nav2 내부 토픽을 확인하세요.')
        try:
            result=subprocess.run(['dot','-Tpng'],input=graph_dot(topics).encode(),capture_output=True,timeout=8,check=True)
            loader=GdkPixbuf.PixbufLoader.new_with_type('png');loader.write(result.stdout);loader.close();self.pixbuf=loader.get_pixbuf();self.scale()
        except Exception as e:self.status.set_text('그래프 렌더링 실패: '+str(e)[:100])
    def scale(self,*args):
        if self.pixbuf:
            z=self.zoom.get_value();self.image.set_from_pixbuf(self.pixbuf.scale_simple(max(1,int(self.pixbuf.get_width()*z)),max(1,int(self.pixbuf.get_height()*z)),GdkPixbuf.InterpType.BILINEAR))
