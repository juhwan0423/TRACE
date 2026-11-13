"""No network, model or simulator calls: calibration-probe construction tests."""
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qwen_probe", ROOT / "scripts/probe_qwen_vision.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def interpretation(eid="calibration-00"):
    return dict(person_visible="yes", posture="standing", visible_risk_cues=[],
                observation_limitations=[], needs_more_observation=False, evidence_ids=[eid])


def envelope(condition, eid="calibration-00"):
    content = json.dumps(interpretation(eid))
    fields = {"response": content} if condition == "raw_closed_think" else {"message": {"content": content}}
    return json.dumps(dict(fields, done=True, done_reason="stop", eval_count=80))


class ProbeTests(unittest.TestCase):
    def test_chat_request_exactly_matches_frozen_adapter(self):
        from haiclaw.providers import ollama
        calls = []

        class Transport:
            def __init__(self, *args):
                pass

            async def __call__(self, native):
                calls.append(native)
                return envelope("chat_think_true")

        image = ROOT / "artifacts/trace_comparison_readiness" / probe.CALIBRATION[0]
        config = json.loads((ROOT / "configs/vlm_local.json").read_text())
        with patch.object(ollama, "LocalChatTransport", Transport):
            adapter = ollama.make_adapter(config)
            asyncio.run(adapter.infer(SimpleNamespace(artifact=image, id="calibration-00", capture_time=0.0)))
        expected = probe.payload("chat_think_true", image.read_bytes(), "calibration-00", config["model"])
        self.assertEqual(calls, [expected])

    def test_raw_has_one_runner_image_marker_and_matched_controls(self):
        data = b"\x89PNG\r\n\x1a\nfixture"
        chat = probe.payload("chat_think_true", data, "calibration-00", "qwen3-vl:8b")
        raw = probe.payload("raw_closed_think", data, "calibration-00", "qwen3-vl:8b")
        self.assertEqual(raw["options"], chat["options"])
        self.assertEqual(raw["format"], chat["format"])
        self.assertEqual(raw["images"], chat["messages"][1]["images"])
        self.assertEqual(raw["prompt"].count("[img-0]"), 1)
        self.assertTrue(raw["prompt"].endswith("<think>\n\n</think>\n\n"))
        self.assertNotIn("<|image_pad|>", raw["prompt"])
        self.assertNotIn("standing/body.png", json.dumps(raw))
        self.assertFalse(raw["think"])

    def test_empty_thinking_only_response_is_failure_without_reasoning_text(self):
        raw = json.dumps(dict(message=dict(content="", thinking="do not retain reasoning"),
                              done=True, done_reason="length", eval_count=4096))
        result = probe.classify_response(raw, "chat_think_true", "calibration-00")
        self.assertTrue(result["empty_content"])
        self.assertFalse(result["schema_valid"])
        self.assertEqual(result["metadata"]["eval_count"], 4096)
        self.assertNotIn("do not retain reasoning", json.dumps(result))

    def test_syntactic_json_does_not_imply_schema_valid(self):
        raw = json.dumps({"response": json.dumps({"answer": "standing"})})
        result = probe.classify_response(raw, "raw_closed_think", "calibration-00")
        self.assertTrue(result["json_valid"])
        self.assertFalse(result["schema_valid"])

    def test_wrong_evidence_binding_fails(self):
        result = probe.classify_response(envelope("raw_closed_think", "wrong"),
                                         "raw_closed_think", "calibration-00")
        self.assertTrue(result["json_valid"])
        self.assertFalse(result["schema_valid"])

    def test_endpoint_and_output_fields_for_each_condition(self):
        config = {"endpoint": "http://127.0.0.1:11435/api/chat"}
        self.assertEqual(probe.endpoint_for(config, "raw_closed_think"), "http://127.0.0.1:11435/api/generate")
        for condition in probe.CONDITIONS:
            self.assertTrue(probe.classify_response(envelope(condition), condition, "calibration-00")["schema_valid"])
        with self.assertRaises(ValueError):
            probe.endpoint_for({"endpoint": "https://example.com/api/chat"}, "raw_closed_think")

    def test_active_comparison_runner_blocks_probe(self):
        fake_process = MagicMock()
        fake_process.name = "1234"
        (fake_process / "cmdline").read_bytes.return_value = b"python\0/a/run_real2sim_comparison.py\0run\0--output\0/a\0"
        with patch.object(probe.Path, "iterdir", return_value=[fake_process]):
            with self.assertRaisesRegex(RuntimeError, "still active"):
                probe.assert_no_comparison_runner()

    def test_no_inference_without_explicit_run_flag(self):
        with patch.object(probe, "read_metadata") as metadata, patch.object(probe, "bounded_post") as inference:
            with self.assertRaises(ValueError):
                probe.run(Path("/unused"))
        metadata.assert_not_called()
        inference.assert_not_called()

    def test_freeze_and_verify_do_not_infer_and_detect_snapshot_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "registered"
            with patch.object(probe, "read_metadata", return_value={"fixture": True}), patch.object(probe, "bounded_post") as inference:
                probe.freeze(output)
                registration = probe.verify(output)
                self.assertEqual(len(registration["schedule"]), 8)
                self.assertEqual([x["condition"] for x in registration["schedule"][:4]],
                                 ["chat_think_true", "raw_closed_think", "raw_closed_think", "chat_think_true"])
                inference.assert_not_called()
            snapshot = output / "source/scripts/probe_qwen_vision.py"
            snapshot.write_text("changed fixture snapshot")
            with self.assertRaisesRegex(ValueError, "source changed"):
                probe.verify(output)

    def test_transport_failure_aborts_without_retry_or_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "registered"
            with patch.object(probe, "read_metadata", return_value={"fixture": True}), \
                    patch.object(probe, "assert_no_comparison_runner"), \
                    patch.object(probe, "bounded_post", side_effect=TimeoutError) as inference:
                probe.freeze(output)
                result = probe.run(output, True)
                self.assertFalse(result["complete"])
                self.assertEqual(inference.call_count, 1)
                self.assertEqual(result["inference_calls_attempted"], 1)
                with self.assertRaises(FileExistsError):
                    probe.run(output, True)
                self.assertEqual(inference.call_count, 1)

    def test_complete_mock_run_is_exactly_eight_calls(self):
        def answer(transport, request):
            eid = request["format"]["properties"]["evidence_ids"]["items"]["enum"][0]
            return envelope("raw_closed_think" if request.get("raw") else "chat_think_true", eid)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "registered"
            with patch.object(probe, "read_metadata", return_value={"fixture": True}), \
                    patch.object(probe, "assert_no_comparison_runner"), \
                    patch.object(probe, "bounded_post", side_effect=answer) as inference:
                probe.freeze(output)
                result = probe.run(output, True)
                self.assertTrue(result["complete"])
                self.assertEqual(inference.call_count, 8)
                for condition in probe.CONDITIONS:
                    self.assertEqual(result["conditions"][condition]["strict_schema_valid"], 4)


if __name__ == "__main__":
    unittest.main()
