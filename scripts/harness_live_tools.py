"""Live tools on the owned Isaac context; independent of agent choice policy."""
import asyncio
import uuid
from tracebot.core import Evidence
from run_closed_loop import remote

CAPTURE = '''
trace_guard()
_hsensor = trace_camera if camera_name == 'fixed' else demo.camera
_hclock = trace_clock if camera_name == 'fixed' else inspection.clock
_hend = time.monotonic()+20.
_hresult = None
while time.monotonic() < _hend:
    trace_guard()
    if not omni.timeline.get_timeline_interface().is_playing():
        raise RuntimeError('Simulation paused during capture')
    _hstamp = float(_hclock.get_data().get('simulationTime',-1))
    if _hstamp > after:
        _hdata, _ = _hsensor.get_data('rgb')
        if _hdata is not None:
            _himage = _hdata.numpy()
            if _himage.size and _himage[:,:,:3].mean()>20:
                _hpath = trace_output/(str(uuid.uuid4())+'.png')
                Image.fromarray(_himage).save(_hpath)
                _hresult = dict(artifact=str(_hpath),capture_time=_hstamp,
                    received_time=SimulationManager.get_simulation_time())
                break
    await app_utils.update_app_async(steps=2)
if _hresult is None:
    raise RuntimeError('No fresh camera buffer')
print(json.dumps(_hresult))
'''

class LiveTools:
    def __init__(self,adapter,locations):
        self.adapter=adapter;self.locations=locations;self.latest={};self.arrived_at=-1.;self.motion_records=[]
    async def snapshot(self):return await remote('print(json.dumps(trace_snapshot()))',timeout=4)
    async def observe(self,camera,episode):
        now=(await self.snapshot())['now']
        after=max(now,self.latest.get(camera,-1),self.arrived_at if camera=='body' else -1)
        frame=await remote(CAPTURE,camera_name=camera,after=after,timeout=25)
        self.latest[camera]=frame['capture_time']
        e=Evidence(str(uuid.uuid4()),episode,camera,**frame)
        obs,record=await self.adapter.infer(e)
        return e,obs,record
    async def inspect(self,target):
        x,y,yaw=self.locations[target]['pose']
        await remote('trace_guard(); inspection.start(x,y,yaw)',x=x,y=y,yaw=yaw,timeout=5)
        while True:
            s=await self.snapshot();nav=s['navigation']
            if nav and nav['status']!='moving':
                self.motion_records.append(dict(target=target,navigation=nav))
                if nav['status']=='arrived':self.arrived_at=nav['arrived_at']
                return dict(status=nav['status'])
            await asyncio.sleep(.2)
    async def stop(self):
        await remote('trace_guard(); inspection.cancel(); demo.hold()',timeout=4)
