"""Explicit fixture tools for harness contract tests; no real sensors or locomotion."""
import asyncio
import time
import uuid
from ..core import Evidence
from .single_frame_vlm import Interpretation

class FixtureTools:
    locations = {
        'east_inspection': {'description':'East-side inspection view'},
        'southeast_inspection': {'description':'Alternative southeast view'}}
    def __init__(self, *, fail_first=False, limited=False):
        self.started=time.monotonic();self.current=None;self.stopped=0
        self.fail_first=fail_first;self.limited=limited;self.moves=[];self.captures=[]
    async def snapshot(self):return dict(now=time.monotonic()-self.started,playing=True)
    async def inspect(self,target):
        await asyncio.sleep(.01);self.moves.append(target)
        if self.fail_first and len(self.moves)==1:return dict(status='failed')
        self.current=target;return dict(status='arrived')
    async def observe(self,camera,episode):
        await asyncio.sleep(.01);now=(await self.snapshot())['now'];eid=str(uuid.uuid4())
        visible=camera=='body' and self.current is not None
        obs=Interpretation('yes' if visible else 'no','lying' if visible else 'unknown',
            ('lying on ground',) if visible else (),
            ('pixelated texture',) if self.limited else (() if visible else ('occluded',)),
            not visible or self.limited,(eid,))
        evidence=Evidence(eid,episode,camera,now,now,'fixture://'+eid)
        self.captures.append(camera)
        return evidence,obs,dict(status='ok')
    async def stop(self):self.stopped+=1

class FixturePlanner:
    """Test-only policy; never presented as an LLM decision."""
    async def choose(self,state):
        views=[t for t in state['available_tools'] if t['tool']=='inspect']
        last=state['recent_events'][-1] if state['recent_events'] else {}
        if last.get('tool')=='inspect' and last.get('status')=='arrived':
            return dict(tool='observe',target='body',reason='Inspect the new viewpoint evidence.')
        if views:
            return dict(tool='inspect',target=views[0]['target'],reason='Choose an available alternative viewpoint.')
        return dict(tool='escalate',target='',reason='Available viewpoints did not resolve uncertainty.')
