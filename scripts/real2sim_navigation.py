"""Attach the validated Spot runner to the owned Real2Sim session (remote script)."""
import json
import math
import time
import uuid
from pathlib import Path
import numpy as np
import carb.settings
import omni.usd
import omni.timeline
from pxr import UsdGeom, Gf
from isaacsim.core.simulation_manager import SimulationManager
from isaacsim.core.simulation_manager.impl.isaac_events import IsaacEvents
from isaacsim.core.rendering_manager import RenderingManager
from isaacsim.robot.policy.examples import RobotPolicyRunner, get_spot_spec

class Real2SimNavigation:
    def __init__(self, root):
        self.stage = omni.usd.get_context().get_stage()
        self.root = Path(root).resolve()
        assert carb.settings.get_settings().get('/real2sim/workspace') == str(self.root)
        assert self.stage.GetRootLayer().realPath == str(self.root/'lab_west/results/human_door/labwest_optb/human_in_scene.usda')
        if self.stage.GetPrimAtPath('/World/Spot'):
            raise RuntimeError('An unowned Spot already exists')
        self.points = [list(map(float,p.split(','))) for p in json.loads((self.root/'lab_west/work/patrol/spot_plan.json').read_text())['waypoints'].split()]
        self.ready = False
        self.pose = None
        self.elapsed = 0.0
        self.command = dict(status='idle')
        self.route = []
        self.callback = None
        tl = omni.timeline.get_timeline_interface()
        tl.stop()
        self.stage.SetEditTarget(self.stage.GetSessionLayer())
        SimulationManager.set_physics_sim_device('cpu')
        RenderingManager.set_dt(1/60)
        self.runner = RobotPolicyRunner(get_spot_spec(),prim_path='/World/Spot',position=[-1.10,3.32,.55],orientation=[math.cos(-math.pi/4),0,0,math.sin(-math.pi/4)],training_engine='physx')
        self.runner.spawn()
        SimulationManager.set_physics_dt(self.runner.physics_dt)
        self.callback = SimulationManager.register_callback(self.tick,IsaacEvents.POST_PHYSICS_STEP)
        tl.play()

    def guard(self):
        if omni.usd.get_context().get_stage() is not self.stage:
            raise RuntimeError('Real2Sim stage changed')

    def snapshot(self):
        return dict(now=SimulationManager.get_simulation_time(),playing=omni.timeline.get_timeline_interface().is_playing(),pose=self.pose,navigation=dict(self.command),scene='real2sim',spot_attached=True,ready=self.ready)

    def stop(self, reason='operator stop', request_id=None):
        self.guard()
        if request_id is not None and self.command.get('id') != request_id:
            return self.snapshot()
        if request_id is not None and self.command['status']!='moving':
            return self.snapshot()
        self.route=[]
        self.command.update(status='cancelled',reason=reason,remaining=0)
        return self.snapshot()

    def reset_to_entrance(self):
        self.guard()
        if self.command['status']=='moving':
            raise RuntimeError('Stop the active goal before simulation reset')
        self.route=[]
        self.runner.articulation.reset_to_default_state()
        self.runner.initialize()
        self.elapsed=0.0
        self.command=dict(status='idle',reason='Explicit simulation reset to entrance')
        return self.snapshot()

    def navigate(self, target='patrol', request_id=None, final_yaw=None):
        self.guard()
        if request_id is not None and self.command.get('id') == request_id:
            if self.command.get('target') != target or self.command.get('final_yaw') != final_yaw:
                raise ValueError('Request ID reused with different arguments')
            return self.snapshot()
        if final_yaw is not None and not math.isfinite(final_yaw):raise ValueError('Invalid heading')
        if not self.ready or self.elapsed < 4:
            raise RuntimeError('Spot is still settling')
        if not omni.timeline.get_timeline_interface().is_playing():
            raise RuntimeError('Resume the simulation before moving')
        if self.command['status']=='failed':
            raise RuntimeError('Navigation fault requires inspection before retry')
        if self.command['status']=='moving':
            raise RuntimeError('Stop the active goal first')
        # Only the repository A* corridor is exposed, never an unchecked straight-line goal.
        nearest=int(np.argmin([np.linalg.norm(np.array(p)-self.pose[:2]) for p in self.points]))
        if np.linalg.norm(np.array(self.points[nearest])-self.pose[:2]) > .6:
            raise RuntimeError('Spot is outside the validated path corridor')
        targets={'entrance':0,'west':7,'cage':18}
        if target=='patrol':
            if nearest not in (0,23):raise RuntimeError('Return to entrance before starting the full patrol')
            indices=list(range(1,len(self.points)))
        elif target in targets:
            end=targets[target]
            direction=1 if end>=nearest else -1
            indices=list(range(nearest,end+direction,direction))
        else:raise ValueError('Unknown destination')
        self.route=[self.points[i] for i in indices]
        self.command=dict(id=request_id or str(uuid.uuid4()),status='moving',target=target,remaining=len(self.route),started=SimulationManager.get_simulation_time(),final_yaw=final_yaw)
        self.best=float('inf');self.progress=self.elapsed;self.deadline=time.monotonic()+240
        self.runner.initialize()
        return self.snapshot()

    def tick(self, dt, context):
        try:
            self.guard()
            if not self.ready:
                self.runner.initialize();self.runner.articulation.reset_to_default_state();self.runner.initialize()
                self.ready=True
                return
            self.elapsed+=dt
            p,q=self.runner.articulation.get_world_poses()
            p=p.numpy()[0];w,x,y,z=q.numpy()[0]
            yaw=math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))
            self.pose=[float(p[0]),float(p[1]),float(yaw)]
            tilt=math.degrees(math.acos(float(np.clip(1-2*(x*x+y*y),-1,1))))
            cmd=np.zeros(3,dtype=np.float32)
            if tilt>45:
                self.route=[];self.command.update(status='failed',reason='Spot tilted beyond 45 degrees')
            if self.route:
                d=np.array(self.route[0])-p[:2];dist=float(np.linalg.norm(d))
                if dist<.15:
                    self.route.pop(0);self.best=float('inf');self.progress=self.elapsed
                    self.command['remaining']=len(self.route)
                    if not self.route:
                        self.progress=self.elapsed
                        if self.command.get('final_yaw') is None:
                            self.command.update(status='arrived',arrived_at=SimulationManager.get_simulation_time())
                else:
                    err=(math.atan2(d[1],d[0])-yaw+math.pi)%(2*math.pi)-math.pi
                    if abs(err)>.2:cmd[2]=np.clip(1.5*err,-.6,.6)
                    else:cmd[0]=min(.45,1.2*dist);cmd[2]=np.clip(err,-.6,.6)
                    if dist<self.best-.05:self.best=dist;self.progress=self.elapsed
                    if self.elapsed-self.progress>10 or time.monotonic()>self.deadline:
                        self.route=[];cmd[:]=0;self.command.update(status='failed',reason='No progress or goal deadline exceeded')
            if not self.route and self.command['status']=='moving':
                err=(self.command['final_yaw']-yaw+math.pi)%(2*math.pi)-math.pi
                if abs(err)<.10:
                    self.command.update(status='arrived',arrived_at=SimulationManager.get_simulation_time())
                elif self.elapsed-self.progress>15 or time.monotonic()>self.deadline:
                    self.command.update(status='failed',reason='Viewpoint heading timeout')
                else:cmd[2]=np.clip(1.5*err,-.6,.6)
            self.runner.step(dt,cmd)
            camera=self.stage.GetPrimAtPath('/World/TraceReal2Sim/body')
            if camera:
                fwd=np.array([math.cos(yaw),math.sin(yaw),0]);eye=p+.30*fwd+np.array([0,0,.15]);target=eye+2*fwd+np.array([0,0,-.25])
                UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse())
        except Exception as error:
            self.route=[];self.command.update(status='failed',reason=str(error))
            # Pause this owned simulation on controller errors, rather than retain motion targets.
            omni.timeline.get_timeline_interface().pause()

if not globals().get('real2sim_navigation'):
    assert carb.settings.get_settings().get('/real2sim/workspace') == str(Path(real2sim_root).resolve())
    assert omni.usd.get_context().get_stage().GetRootLayer().realPath == str(Path(real2sim_root).resolve()/'lab_west/results/human_door/labwest_optb/human_in_scene.usda')
    if omni.usd.get_context().get_stage().GetPrimAtPath('/World/Spot'):
        raise RuntimeError('An unowned Spot already exists')
    omni.timeline.get_timeline_interface().stop()
    import omni.kit.app
    for _ in range(3):
        await omni.kit.app.get_app().next_update_async()
    real2sim_navigation=Real2SimNavigation(real2sim_root)
print(json.dumps(real2sim_navigation.snapshot()))
