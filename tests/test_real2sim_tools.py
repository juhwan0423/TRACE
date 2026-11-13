"""Boundary tests independent of Isaac Sim and the planner framework."""
import asyncio
import base64
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from real2sim_harness_tools import Real2SimTools

class Real2SimToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    async def test_arrival_keeps_global_clock_and_request_identity(self):
        calls=[];identity=None
        async def remote(code,**args):
            nonlocal identity
            calls.append((code,args))
            if 'navigate(' in code:identity=args['request_id'];return {}
            if 'snapshot()' in code:return dict(playing=True,now=1005,navigation=dict(id=identity,status='arrived',arrived_at=1004))
            return {}
        tools=Real2SimTools(None,{'cage':{'yaw':-1.57}},self.temp.name,remote)
        self.assertEqual(await tools.inspect('cage'),{'status':'arrived'})
        self.assertEqual(tools.arrived_at,1004)
        self.assertEqual(calls[-1][1]['request_id'],identity)
    async def test_cancelled_request_sends_scoped_stop(self):
        entered=asyncio.Event();calls=[]
        async def remote(code,**args):
            calls.append((code,args))
            if 'navigate(' in code:entered.set();await asyncio.sleep(100)
            return {}
        tools=Real2SimTools(None,{'cage':{'yaw':0}},self.temp.name,remote)
        task=asyncio.create_task(tools.inspect('cage'));await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertIn('stop(request_id=',calls[-1][0])
        self.assertEqual(calls[0][1]['request_id'],calls[-1][1]['request_id'])
    async def test_replaced_goal_is_not_reported_as_our_arrival(self):
        async def remote(code,**args):
            if 'snapshot()' in code:return dict(playing=True,navigation=dict(id='operator-goal',status='arrived'))
            return {}
        tools=Real2SimTools(None,{'cage':{'yaw':0}},self.temp.name,remote)
        with self.assertRaisesRegex(RuntimeError,'replaced'):await tools.inspect('cage')
        self.assertEqual(tools.arrived_at,-1)
    async def test_unknown_target_never_reaches_simulator(self):
        remote=AsyncMock();tools=Real2SimTools(None,{},self.temp.name,remote)
        with self.assertRaises(ValueError):await tools.inspect('arbitrary')
        remote.assert_not_called()
    async def test_replaced_or_moving_body_view_cannot_be_labeled_as_arrived(self):
        adapter=AsyncMock()
        for navigation in (dict(id='ours',status='moving'),dict(id='ours',status='failed'),dict(id='other',status='arrived')):
            remote=AsyncMock(return_value=dict(now=100,navigation=navigation))
            tools=Real2SimTools(adapter,{},self.temp.name,remote);tools.action_id='ours'
            with self.assertRaises(RuntimeError):await tools.observe('body','episode')
        adapter.infer.assert_not_called()
    async def test_observation_requires_frame_newer_than_arrival(self):
        data=io.BytesIO();Image.new('RGB',(2,2),'white').save(data,format='JPEG')
        image=base64.b64encode(data.getvalue()).decode();frames=iter([99,101])
        async def remote(code,**args):
            if 'snapshot()' in code:return dict(now=100)
            stamp=next(frames)
            return dict(snapshot=dict(now=102,playing=True),frames={'body':dict(image=image,capture_time=stamp)})
        adapter=AsyncMock();adapter.infer.return_value=('observation',{'status':'ok'})
        tools=Real2SimTools(adapter,{},self.temp.name,remote);tools.arrived_at=100
        e,_,_=await tools.observe('body','episode')
        self.assertEqual(e.capture_time,101);self.assertEqual(e.received_time,102)
        self.assertTrue(Path(e.artifact).read_bytes().startswith(b'\x89PNG'))
        adapter.infer.assert_awaited_once()
