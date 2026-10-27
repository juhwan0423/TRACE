"""TRACE command interface for the owned Real2Sim Spot session."""
import argparse
import json
import os
from pathlib import Path
import socket

ROOT=Path(__file__).resolve().parents[1]
def request(code, args=None, timeout=15):
    with socket.create_connection(('127.0.0.1',int(os.environ.get('TRACE_ISAAC_PORT','8227'))),timeout=timeout) as sock:
        sock.sendall(json.dumps(dict(context='real2sim',code=code,args=args or {})).encode())
        sock.shutdown(socket.SHUT_WR)
        chunks=[]
        while block:=sock.recv(65536):chunks.append(block)
    reply=json.loads(b''.join(chunks))
    if reply.get('status')!='ok':raise RuntimeError(reply.get('evalue',str(reply)))
    return json.loads(reply['output'].strip().splitlines()[-1])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['state','go','stop','reset'])
    p.add_argument('target',nargs='?',choices=['patrol','west','cage','entrance'],default='patrol')
    a=p.parse_args()
    code={'reset':'real2sim_navigation.reset_to_entrance()','state':'real2sim_navigation.snapshot()','stop':'real2sim_navigation.stop()','go':'real2sim_navigation.navigate(target)'}[a.action]
    result=request('print(json.dumps('+code+'))',{'target':a.target})
    out=ROOT/'artifacts/live_real2sim';out.mkdir(parents=True,exist_ok=True)
    with (out/'navigation.jsonl').open('a') as f:f.write(json.dumps(dict(action=a.action,target=a.target,result=result))+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
