#!/usr/bin/env python3
"""CPU-only deterministic question lifecycle demonstration (not live perception)."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from tracebot.context import ContextGraph
from tracebot.core import Evidence
from tracebot.providers.single_frame_vlm import Interpretation


def main():
    graph=ContextGraph('context-demo',max_age=5)
    stages=[]
    def save(label):
        stages.append(dict(label=label, snapshot=graph.snapshot()))
    def observe(eid,t,posture):
        e=Evidence(eid,'context-demo','body',t,t,'fixture://'+eid)
        o=Interpretation('yes',posture,(),(),False,(eid,))
        graph.observe(e,o,t)
    graph.advance(0);save('unresolved')
    observe('E1',1,'lying');save('resolved from E1')
    observe('E2',2,'standing');save('conflicting evidence reopens dependent judgment')
    graph.revoke('E2',3);save('explicit withdrawal of E2 restores E1 support')
    graph.advance(6);save('E1 expires; no contrary conclusion is inferred')
    action=graph.bind(dict(tool='observe',target='body',reason='Refresh expired posture evidence.',question_id='lying'))
    observe('E3',7,'lying');save('new evidence resolves again')
    print(json.dumps(dict(mode='fixture',action=action,stages=stages),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
