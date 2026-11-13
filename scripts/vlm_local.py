"""Run local Qwen vision on a saved PNG; no live incident or robot commands."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tracebot.core import Evidence
from tracebot.providers.ollama import make_adapter


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/vlm_local.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    image = args.image.resolve(strict=True)
    adapter = make_adapter(config)
    # Zero is an offline replay coordinate, not a claim of a new camera capture.
    evidence = Evidence(str(uuid.uuid4()), str(uuid.uuid4()), "saved_rgb_replay", 0, 0, str(image))
    _, record = await adapter.infer(evidence)
    record.update(mode="saved_image_local_inference", image=str(image),
                  image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                  live_incident=False)
    output = args.output or ROOT / "artifacts/vlm_local" / f"{evidence.id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"Report: {output}")
    return 0 if record["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
