import asyncio
import json
import tempfile
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch
from tracebot.core import Evidence, Incident, State
from tracebot.providers.single_frame_vlm import (validate, incident_decision, request_payload,
    SingleFrameVLM, IncidentVLM, LocalChatTransport)
from tracebot.providers.gemini import GeminiTransport, gemini_payload, response_text, MODEL


def observation(eid='f', posture='standing'):
    return dict(person_visible='yes',posture=posture,visible_risk_cues=[],
                observation_limitations=[],needs_more_observation=False,evidence_ids=[eid])


def envelope(data):
    return json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(data)}]}}]})


class Contracts(unittest.TestCase):
    def test_standing_and_seated_never_map_to_safe_activity(self):
        for posture in ('standing','seated'):
            d=incident_decision(validate(observation(posture=posture),'f'))
            self.assertTrue(d.insufficient_evidence)
            self.assertEqual(d.observable_posture,'unknown')

    def test_bad_enum_boolean_extra_keys_and_foreign_ref(self):
        for change in ({'person_visible':True},{'posture':'walking'}, {'needs_more_observation':1},
                       {'evidence_ids':['other']},{'diagnosis':'unconscious'}):
            with self.assertRaises(ValueError): validate(observation()|change,'f')

    def test_visible_lying_with_limitations_does_not_trigger_danger(self):
        d=incident_decision(validate(observation(posture='lying')|{'observation_limitations':['occluded']},'f'))
        self.assertTrue(d.insufficient_evidence)

    def test_no_api_without_explicit_opt_in_and_key(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(ValueError): GeminiTransport()
            with self.assertRaises(ValueError): GeminiTransport(allow_api=True)
        with self.assertRaises(ValueError): LocalChatTransport('https://example.com/chat')

    def test_incomplete_blocked_and_thought_response_rejected_or_filtered(self):
        with self.assertRaises(ValueError): response_text({'candidates':[{'finishReason':'MAX_TOKENS'}]})
        self.assertEqual(response_text({'candidates':[{'finishReason':'STOP','content':{'parts':[
            {'thought':True,'text':'private reasoning'}, {'text':'{}'}]}}]}),'{}')

    def test_model_payload_cannot_leak_filename_scenario_or_pose(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'GROUND_TRUTH_lying_coordinates.png'
            path.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
            payload=gemini_payload(request_payload(path,'opaque-id',2.,MODEL))
            body=json.dumps(payload)
            self.assertNotIn(str(path),body)
            self.assertNotIn('GROUND_TRUTH',body)
            self.assertEqual(json.loads(payload['contents'][0]['parts'][0]['text']),
                             {'evidence_id':'opaque-id','capture_time':2.})
            self.assertNotIn('tools',payload)


class Asynchronous(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=Path(self.folder.name)/'f.png'
        self.path.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        self.e=Evidence('f','ep','robot',2.,2.,str(self.path))
        self.i=Incident('ep',0.,10.)
        attempt=self.i.motion('moving',.5)
        self.i.motion('arrived',1.,attempt_id=attempt)

    async def asyncTearDown(self): self.folder.cleanup()

    def coordinator(self, transport, timeout=1.):
        a=SingleFrameVLM(transport,MODEL,timeout,decoder=response_text)
        return IncidentVLM(self.i,a)

    async def drain(self,c,now):
        await asyncio.gather(*(t for e,t in c.pending.values()))
        c.tick(now)

    async def test_actual_schema_danger_maps_to_core(self):
        async def call(payload): return envelope(observation(posture='lying'))
        c=self.coordinator(call); c.submit(self.e); await self.drain(c,3.)
        self.assertEqual(self.i.state,State.DANGER)

    async def test_standing_remains_open_until_deadline(self):
        async def call(payload): return envelope(observation())
        c=self.coordinator(call); c.submit(self.e); await self.drain(c,3.)
        self.assertEqual(self.i.state,State.VERIFYING)
        c.tick(10.); self.assertEqual(self.i.state,State.UNKNOWN)

    async def test_completed_evidence_is_not_sent_twice(self):
        calls=[]
        async def call(payload):
            calls.append(payload)
            return envelope(observation())
        c=self.coordinator(call); c.submit(self.e); await self.drain(c,3.)
        c.submit(self.e)
        self.assertFalse(c.pending)
        self.assertEqual(len(calls),1)

    async def test_ready_danger_at_exact_deadline_precedes_unknown(self):
        async def call(payload): return envelope(observation(posture='lying'))
        c=self.coordinator(call); c.submit(self.e); await self.drain(c,10.)
        self.assertEqual(self.i.state,State.DANGER)

    async def test_schema_server_failure_and_timeout_are_unknown(self):
        async def malformed(p): return '{}'
        async def offline(p): raise ConnectionError('offline')
        async def slow(p): await asyncio.sleep(.1)
        for transport in (malformed,offline,slow):
            c=self.coordinator(transport,timeout=.01); c.submit(self.e)
            await self.drain(c,3.)
            self.assertNotEqual(self.i.state,State.SAFE)
            self.assertTrue(c.audit[-1]['inference']['interpretation']['needs_more_observation'])

    async def test_timer_runs_while_model_pending_and_late_answer_does_not_rewrite(self):
        release=asyncio.Event()
        async def slow(p):
            await release.wait(); return envelope(observation(posture='lying'))
        c=self.coordinator(slow); c.submit(self.e)
        await asyncio.sleep(0)
        c.tick(10.); self.assertEqual(self.i.state,State.UNKNOWN)
        release.set(); await self.drain(c,11.)
        self.assertEqual(self.i.state,State.UNKNOWN)

    async def test_old_motion_and_episode_results_rejected(self):
        for reset_episode in (False,True):
            release=asyncio.Event()
            async def slow(p):
                await release.wait(); return envelope(observation(posture='lying'))
            c=self.coordinator(slow); c.submit(self.e); await asyncio.sleep(0)
            if reset_episode:
                current=Incident('other',0,10,generation=1); c.reset(current)
            else:
                self.i.motion('moving',2.5); self.i.motion('arrived',2.6); current=self.i
            release.set(); await self.drain(c,3.)
            self.assertTrue(c.audit[-1]['rejected_stale'])
            self.assertNotEqual(current.state,State.DANGER)
            self.i=Incident('ep',0,10); self.i.motion('arrived',1)


class GeminiWire(unittest.TestCase):
    def test_rest_request_key_header_only_and_no_live_network(self):
        import io
        captured=[]
        class Opener:
            def open(self, request, timeout):
                captured.append(request)
                return io.BytesIO(envelope(observation()).encode())
        with patch.dict('os.environ',{'GEMINI_API_KEY':'fixture-not-a-key'}), patch(
                'urllib.request.build_opener',return_value=Opener()):
            transport=GeminiTransport(allow_api=True)
            raw=transport._post({'contents':[]})
        self.assertIn('candidates',json.loads(raw))
        self.assertEqual(captured[0].get_header('X-goog-api-key'),'fixture-not-a-key')
        self.assertNotIn('fixture-not-a-key',captured[0].full_url)
        self.assertNotIn(b'fixture-not-a-key',captured[0].data)

    def test_http_error_body_and_key_not_logged(self):
        import io
        from urllib.error import HTTPError
        class Opener:
            def open(self, request, timeout):
                raise HTTPError(request.full_url,429,'echo fixture-not-a-key',{},io.BytesIO(b'private error body'))
        with patch.dict('os.environ',{'GEMINI_API_KEY':'fixture-not-a-key'}), patch(
                'urllib.request.build_opener',return_value=Opener()):
            transport=GeminiTransport(allow_api=True)
            with self.assertRaisesRegex(RuntimeError,'Gemini HTTP 429; no automatic retry') as caught:
                transport._post({})
        self.assertNotIn('fixture-not-a-key',str(caught.exception))
