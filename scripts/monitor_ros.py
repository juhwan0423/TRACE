"""Read-only ROS graph from the existing simulator ROS node."""
GRAPH_CODE = '''
trace_guard()
def monitor_endpoint(item):
    return dict(node=(item.node_namespace.rstrip('/')+'/'+item.node_name),
                type=item.topic_type, reliability=str(item.qos_profile.reliability),
                durability=str(item.qos_profile.durability))
monitor_topics = []
for monitor_name, monitor_types in ros_bridge.get_topic_names_and_types():
    monitor_topics.append(dict(name=monitor_name, types=monitor_types,
        publishers=[monitor_endpoint(e) for e in ros_bridge.get_publishers_info_by_topic(monitor_name)],
        subscribers=[monitor_endpoint(e) for e in ros_bridge.get_subscriptions_info_by_topic(monitor_name)]))
print(json.dumps(dict(nodes=sorted(set(ns.rstrip('/')+'/'+n for n,ns in ros_bridge.get_node_names_and_namespaces())),
    topics=monitor_topics, domain=173, playing=omni.timeline.get_timeline_interface().is_playing(),
    commands=ros_bridge.commands, scan_messages=ros_bridge.scan_messages)))
'''
CORE = {'/scan','/odom','/plan','/cmd_vel'}

def graph_dot(topics):
    import json
    quote=lambda s:json.dumps(s,ensure_ascii=False)
    lines=['digraph ROS { rankdir=LR; bgcolor="#13171b"; pad="0.3"; nodesep="0.35"; ranksep="0.8";',
           'node [fontname="sans-serif", fontsize=13, color="#61738a", fontcolor="#e1e5e9", style="rounded,filled", fillcolor="#273340", shape=box];',
           'edge [color="#7ca4be", arrowsize=0.7];']
    nodes=set()
    for t in topics:
        tid='topic:'+t['name']
        lines.append(f'{quote(tid)} [label={quote(t["name"])}, fillcolor="#27463e", color="#81b5a2", shape=ellipse];')
        for field in ('publishers','subscribers'):
            for e in t[field]:
                nid='node:'+e['node']
                if nid not in nodes:
                    lines.append(f'{quote(nid)} [label={quote(e["node"])}];');nodes.add(nid)
                a,b=(nid,tid) if field=='publishers' else (tid,nid)
                lines.append(f'{quote(a)} -> {quote(b)};')
    lines.append('}')
    return '\n'.join(lines)
