#!/usr/bin/env python3
"""Separate, bounded calibration probe; never changes the live VLM adapter.

`freeze` only reads model metadata. Only explicit `run --exclusive-server` does
inference, and it refuses to run beside the comparison runner. No automatic retry.
"""
import argparse
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
import statistics
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from haiclaw.providers.single_frame_vlm import LocalChatTransport, PROMPT, validate

CONDITIONS = ("chat_think_true", "raw_closed_think")
CALIBRATION = (
    "entrance_west_adjusted_standing/body.png",
    "entrance_west_adjusted_lying_reversed/body.png",
    "west_west_standing/body.png",
    "door_north2_lying/body.png",
)
SOURCE_PATHS = ("scripts/probe_qwen_vision.py",
                "src/haiclaw/providers/single_frame_vlm.py",
                "src/haiclaw/providers/ollama.py")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2).encode()


def write_json(path, value):
    # Exclusive creation prevents silently replacing a prior registration/result.
    with Path(path).open("xb") as handle:
        handle.write(encode(value) + b"\n")


def schema(evidence_id):
    return {"type": "object", "additionalProperties": False, "properties": {
        "person_visible": {"type": "string", "enum": ["yes", "no", "uncertain"]},
        "posture": {"type": "string", "enum": ["standing", "seated", "lying", "unknown"]},
        "visible_risk_cues": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "observation_limitations": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "needs_more_observation": {"type": "boolean"},
        "evidence_ids": {"type": "array", "items": {"type": "string", "enum": [evidence_id]},
                         "minItems": 1, "maxItems": 1}},
        "required": ["person_visible", "posture", "visible_risk_cues",
                     "observation_limitations", "needs_more_observation", "evidence_ids"]}


def payload(condition, image_bytes, evidence_id, model):
    """Only pixels, an opaque ID and constant calibration time enter the model."""
    if condition not in CONDITIONS:
        raise ValueError("unregistered condition")
    if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n") or len(image_bytes) > 10 * 1024 * 1024:
        raise ValueError("expected bounded PNG")
    metadata = json.dumps({"evidence_id": evidence_id, "capture_time": 0.0})
    images = [base64.b64encode(image_bytes).decode("ascii")]
    result = dict(model=model, stream=False, format=schema(evidence_id),
                  options=dict(temperature=0, num_predict=4096, num_ctx=8192))
    if condition == "chat_think_true":
        result.update(think=True, messages=[{"role": "system", "content": PROMPT},
                      {"role": "user", "content": metadata, "images": images}])
    else:
        # Ollama v0.40.11 llm/llama_server.go replaces [img-0] with its
        # runtime media marker. Native <|image_pad|> alone is not this API's marker.
        prompt = ("<|im_start|>system\n" + PROMPT + "<|im_end|>\n"
                  "<|im_start|>user\n[img-0] " + metadata + "<|im_end|>\n"
                  "<|im_start|>assistant\n<think>\n\n</think>\n\n")
        result.update(think=False, raw=True, prompt=prompt, images=images)
    return result


def endpoint_for(config, condition):
    LocalChatTransport(config["endpoint"], 10)  # Validate loopback, no URL credentials.
    if urlsplit(config["endpoint"]).path != "/api/chat":
        raise ValueError("expected existing /api/chat endpoint")
    return config["endpoint"] if condition == "chat_think_true" else config["endpoint"][:-4] + "generate"


def read_metadata(config):
    """Only /api/version, /api/tags and /api/show; none starts inference."""
    endpoint_for(config, CONDITIONS[0])
    base = config["endpoint"].rsplit("/api/", 1)[0]

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(route, data=None):
        req = urllib.request.Request(base + route, data=None if data is None else encode(data),
                                     headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=10) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized metadata")
        return json.loads(raw)

    version = request("/api/version")["version"]
    models = request("/api/tags")["models"]
    matches = [x for x in models if config["model"] in (x.get("name"), x.get("model"))]
    if len(matches) != 1:
        raise ValueError("model must already exist uniquely; probe never pulls weights")
    shown = request("/api/show", {"model": config["model"]})
    result = dict(version=version, digest=matches[0]["digest"], model=config["model"],
                  template=shown.get("template"), parameters=shown.get("parameters"),
                  capabilities=shown.get("capabilities"), thinking=shown.get("thinking"),
                  details=shown.get("details"))
    if (version != "0.40.11" or config["model"] != "qwen3-vl:8b"
            or "vision" not in (result["capabilities"] or [])
            or result["details"].get("runner") != "llamacpp"
            or result["details"].get("family") != "qwen3vl"
            or False not in (result["thinking"] or {}).get("values", [])):
        raise ValueError("runtime differs from the reviewed raw-image implementation")
    return result


def freeze(output):
    config_path = ROOT / "configs/vlm_local.json"
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    if config["timeout_seconds"] != 180:
        raise ValueError("expected the unchanged 180-second baseline timeout")
    metadata = read_metadata(config)
    image_root = ROOT / "artifacts/trace_comparison_readiness"
    images = []
    schedule = []
    for index, relative in enumerate(CALIBRATION):
        path = (image_root / relative).resolve()
        data = path.read_bytes()
        item = dict(id=f"calibration-{index:02d}", path=str(path), sha256=sha(data))
        images.append(item)
        order = CONDITIONS if index % 2 == 0 else CONDITIONS[::-1]
        for condition in order:
            request = payload(condition, data, item["id"], config["model"])
            schedule.append(dict(call_id=f"c{len(schedule):02d}", image_id=item["id"],
                                 condition=condition, payload_sha256=sha(encode(request))))
    sources = {p: (ROOT / p).read_bytes() for p in SOURCE_PATHS}
    protocol = dict(
        version=1, created_utc=datetime.now(timezone.utc).isoformat(),
        status="registered_before_probe_inference", config=config,
        config_sha256=sha(config_bytes), runtime=metadata,
        sources={p: sha(b) for p, b in sources.items()}, images=images, schedule=schedule,
        max_inference_calls=8, timeout_seconds=180, run_wall_budget_seconds=1500,
        retry_count=0, automatic_resume=False, holdout="development calibration only",
        controls="same weights, pixels, instruction/schema, temperature, context and token cap",
        experimental_change="chat/template/think=true versus explicit raw image prompt/closed think/think=false",
        limitations=["Raw prompt efficacy and vision grounding remain unvalidated before execution.",
                     "Four repeated calibration images are not independent evaluation cases.",
                     "No simulator clock: wall latency cannot be equated to the live 45-second sim TTL.",
                     "No pose accuracy label or policy/safety/closure conclusion is computed.",
                     "Counterbalanced order does not eliminate cache/load or thermal effects.",
                     "A transport timeout aborts the probe; server cancellation is not assumed."],
        official_sources=["https://docs.ollama.com/api/generate",
                          "https://docs.ollama.com/capabilities/thinking",
                          "https://github.com/ollama/ollama/blob/v0.40.11/server/routes.go",
                          "https://github.com/ollama/ollama/blob/v0.40.11/llm/llama_server.go#L1741-L1758",
                          "https://github.com/ollama/ollama/blob/v0.40.11/model/renderers/qwen3vl.go"])
    output.mkdir(parents=True, exist_ok=False)
    for relative, data in sources.items():
        path = output / "source" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    write_json(output / "protocol.json", protocol)
    (output / "protocol.sha256").write_text(sha((output / "protocol.json").read_bytes()) + "\n")
    return dict(status="prepared_no_inference", output=str(output), planned_calls=len(schedule))


def verify(output, live=False):
    protocol_bytes = (output / "protocol.json").read_bytes()
    if sha(protocol_bytes) != (output / "protocol.sha256").read_text().strip():
        raise ValueError("protocol hash changed")
    protocol = json.loads(protocol_bytes)
    for relative, expected in protocol["sources"].items():
        for path in (ROOT / relative, output / "source" / relative):
            if sha(path.read_bytes()) != expected:
                raise ValueError(f"source changed: {relative}")
    if sha((ROOT / "configs/vlm_local.json").read_bytes()) != protocol["config_sha256"]:
        raise ValueError("live VLM config changed")
    for item in protocol["images"]:
        if sha(Path(item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError("calibration image changed")
    if live and read_metadata(protocol["config"]) != protocol["runtime"]:
        raise ValueError("model/runtime metadata changed")
    if len(protocol["schedule"]) != 8 or protocol["max_inference_calls"] != 8:
        raise ValueError("unexpected call bounds")
    return protocol


def assert_no_comparison_runner():
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            args = (process / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        for index, arg in enumerate(args):
            if arg.endswith(b"/run_real2sim_comparison.py") or arg == b"run_real2sim_comparison.py":
                if b"run" in args[index + 1:]:
                    raise RuntimeError(f"comparison runner still active (PID {process.name})")


def classify_response(raw, condition, evidence_id):
    """Persist interpretation/metadata only, never the model's reasoning text."""
    result = dict(response_sha256=sha(raw.encode()), json_valid=False, schema_valid=False)
    try:
        envelope = json.loads(raw)
        content = envelope.get("response", "") if condition == "raw_closed_think" else envelope.get("message", {}).get("content", "")
        thinking = envelope.get("thinking", "") if condition == "raw_closed_think" else envelope.get("message", {}).get("thinking", "")
        if not isinstance(content, str) or not isinstance(thinking, str):
            raise ValueError("invalid content type")
        result.update(content_chars=len(content), content_sha256=sha(content.encode()),
                      thinking_chars=len(thinking), empty_content=not content.strip(),
                      metadata={k: envelope.get(k) for k in ("model", "done", "done_reason",
                          "total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration",
                          "prompt_eval_cached_count", "eval_count", "eval_duration")})
        value = json.loads(content)
        result["json_valid"] = True
        result["interpretation"] = asdict(validate(value, evidence_id))
        result.update(schema_valid=True,
                      status="ok" if envelope.get("done") is True else "incomplete_response")
    except Exception as error:
        # Error text could contain model output; retain only the exception category.
        result.update(status=type(error).__name__)
    return result


def bounded_post(transport, request):
    """Linux main-thread wall timeout, in addition to the socket timeout.

    A socket inactivity timeout alone does not bound a trickling HTTP response.
    Terminating this request does not prove that the server has stopped work.
    """
    def expired(_signum, _frame):
        raise TimeoutError("probe request wall deadline")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 180)
    try:
        return transport._post(request)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def summarize(protocol, records, aborted):
    groups = {}
    for condition in CONDITIONS:
        rows = [r for r in records if r["condition"] == condition]
        latencies = [r["latency_wall_seconds"] for r in rows]
        groups[condition] = dict(attempted=len(rows), planned=4,
            valid_json=sum(r.get("json_valid", False) for r in rows),
            strict_schema_valid=sum(r.get("schema_valid", False) for r in rows),
            completed_schema_valid=sum(r.get("status") == "ok" for r in rows),
            empty_content=sum(r.get("empty_content", False) for r in rows),
            length_stops=sum(r.get("metadata", {}).get("done_reason") == "length" for r in rows),
            median_wall_seconds=statistics.median(latencies) if latencies else None,
            maximum_wall_seconds=max(latencies) if latencies else None,
            total_wall_seconds=sum(latencies))
    return dict(complete=len(records) == len(protocol["schedule"]) and aborted is None,
                inference_calls_attempted=len(records), aborted=aborted, conditions=groups,
                limitations=protocol["limitations"], human_image_grounding_review_required=True)


def run(output, exclusive_server=False):
    if not exclusive_server:
        raise ValueError("run requires --exclusive-server after the frozen pilot releases inference")
    assert_no_comparison_runner()
    protocol = verify(output, live=True)
    # Permanent start record means a partial run cannot invisibly replay any call.
    write_json(output / "STARTED.json", dict(time_utc=datetime.now(timezone.utc).isoformat()))
    started = time.monotonic()
    records, aborted = [], None
    images = {item["id"]: item for item in protocol["images"]}
    try:
        for call in protocol["schedule"]:
            assert_no_comparison_runner()
            verify(output)
            if time.monotonic() - started + 180 > protocol["run_wall_budget_seconds"]:
                aborted = "insufficient remaining wall budget for next bounded call"
                break
            item = images[call["image_id"]]
            request = payload(call["condition"], Path(item["path"]).read_bytes(), item["id"], protocol["config"]["model"])
            if sha(encode(request)) != call["payload_sha256"]:
                raise ValueError("request differs from registration")
            write_json(output / (call["call_id"] + "_started.json"), call)
            begin = time.monotonic()
            record = dict(call)
            try:
                transport = LocalChatTransport(endpoint_for(protocol["config"], call["condition"]), 180)
                raw = bounded_post(transport, request)
                record.update(classify_response(raw, call["condition"], item["id"]))
            except BaseException as error:
                record.update(status=type(error).__name__, json_valid=False, schema_valid=False)
                aborted = "transport failure; no retry, server completion not assumed"
            record["latency_wall_seconds"] = time.monotonic() - begin
            records.append(record)
            write_json(output / (call["call_id"] + "_result.json"), record)
            print(json.dumps({k: record.get(k) for k in ("call_id", "condition", "status", "latency_wall_seconds")}), flush=True)
            if aborted:
                break
        verify(output, live=True)
    except BaseException as error:
        aborted = "interrupted or integrity failure: " + type(error).__name__
        raise
    finally:
        write_json(output / "summary.json", summarize(protocol, records, aborted))
    return summarize(protocol, records, aborted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "verify", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclusive-server", action="store_true",
                        help="assert no concurrent inference; use only after the pilot")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.command == "freeze":
        result = freeze(output)
    elif args.command == "verify":
        protocol = verify(output)
        result = dict(status="offline_integrity_passed", planned_calls=len(protocol["schedule"]))
    else:
        result = run(output, args.exclusive_server)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
