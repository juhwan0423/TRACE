"""Real2Sim implementation of TRACE's framework-independent inspection tools."""
import asyncio
import base64
import io
import json
import math
import uuid
from pathlib import Path
from PIL import Image
from haiclaw.core import Evidence

async def remote(code, *, timeout=10, **args):
    async def call():
        reader,writer=await asyncio.open_connection('127.0.0.1',8227)
        try:
            writer.write(json.dumps(dict(context='real2sim',code=code,args=args)).encode())
            await writer.drain();writer.write_eof()
            chunks=[];size=0
            while block:=await reader.read(65536):
                size+=len(block)
                if size>12*1024*1024:raise ValueError('Oversized simulator reply')
                chunks.append(block)
            reply=json.loads(b''.join(chunks))
            if reply.get('status')!='ok':raise RuntimeError(reply.get('evalue',str(reply)))
            return json.loads(reply['output'].strip().splitlines()[-1])
        finally:
            writer.close();await writer.wait_closed()
    return await asyncio.wait_for(call(),timeout)

class Real2SimTools:
    def __init__(self, adapter, locations, output, requester=remote):
        self.adapter,self.locations,self.output,self.remote=adapter,locations,Path(output),requester
        self.latest={};self.arrived_at=-1.;self.motion_records=[];self.action_id=None
        self.output.mkdir(parents=True,exist_ok=True)

    async def snapshot(self):
        return await self.remote('real2sim_navigation.guard(); print(json.dumps(real2sim_navigation.snapshot()))')

    async def observe(self,camera,episode):
        if camera not in ('fixed','body'):raise ValueError('Unknown camera')
        state=await self.snapshot()
        after=max(state['now'],self.latest.get(camera,-1),self.arrived_at if camera=='body' else -1)
        for _ in range(40):
            result=await self.remote('print(json.dumps(real2sim_monitor_frames()))')
            frame=result['frames'][camera];received=result['snapshot']['now'];stamp=frame['capture_time']
            if not result['snapshot']['playing']:raise RuntimeError('Simulation paused')
            if all(math.isfinite(v) for v in (stamp,received)) and after<stamp<=received:break
            await asyncio.sleep(.1)
        else:raise RuntimeError('No fresh post-request camera frame')
        eid=str(uuid.uuid4());path=self.output/(eid+'.png')
        Image.open(io.BytesIO(base64.b64decode(frame['image'],validate=True))).convert('RGB').save(path)
        self.latest[camera]=stamp
        evidence=Evidence(eid,episode,camera,stamp,received,str(path))
        obs,record=await self.adapter.infer(evidence)
        return evidence,obs,record

    async def inspect(self,target):
        if target not in self.locations:raise ValueError('Unknown viewpoint')
        self.action_id=str(uuid.uuid4());action_id=self.action_id
        try:
            await self.remote('print(json.dumps(real2sim_navigation.navigate(target,request_id=request_id,final_yaw=heading)))',
                target=target,request_id=action_id,heading=self.locations[target]['yaw'])
            while True:
                state=await self.snapshot();nav=state['navigation']
                if nav.get('id')!=action_id:raise RuntimeError('Navigation replaced by another operator')
                if not state['playing']:raise RuntimeError('Simulation paused during movement')
                if nav['status']!='moving':
                    self.motion_records.append(dict(target=target,navigation=nav))
                    if nav['status']=='arrived':self.arrived_at=nav['arrived_at']
                    return dict(status=nav['status'])
                await asyncio.sleep(.2)
        finally:
            # Also covers timeout/cancellation after a request was accepted but before its reply.
            await self.remote('print(json.dumps(real2sim_navigation.stop(request_id=request_id)))',request_id=action_id)

    async def stop(self):
        if self.action_id:
            await self.remote('print(json.dumps(real2sim_navigation.stop(request_id=request_id)))',request_id=self.action_id)
