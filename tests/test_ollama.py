import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from haiclaw.core import Evidence
from haiclaw.providers.ollama import make_adapter


class OllamaTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_schema_binds_id_without_scenario_leak(self):
        captured = []
        class Transport:
            def __init__(self, *args):
                pass
            async def __call__(self, payload):
                captured.append(payload)
                return json.dumps({'message': {'content': json.dumps(dict(
                    person_visible='yes', posture='standing', visible_risk_cues=[],
                    observation_limitations=[], needs_more_observation=True, evidence_ids=['opaque']))}})
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'hidden_truth_lying.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
            with patch('haiclaw.providers.ollama.LocalChatTransport', Transport):
                adapter = make_adapter(dict(endpoint='http://127.0.0.1:11434/api/chat',
                                            timeout_seconds=1, model='qwen3-vl:8b'))
                _, record = await adapter.infer(Evidence('opaque', 'secret_episode', 'body', 1, 1, str(image)))
        self.assertEqual(record['status'], 'ok')
        payload = captured[0]
        ids = payload['format']['properties']['evidence_ids']
        self.assertEqual(ids['type'], 'array')
        self.assertEqual(ids['items']['enum'], ['opaque'])
        self.assertNotIn('hidden_truth', json.dumps(payload))
        self.assertNotIn('secret_episode', json.dumps(payload))
        self.assertFalse(payload['stream'])
