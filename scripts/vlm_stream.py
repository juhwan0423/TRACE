"""Analyze one saved live-monitor frame, with streamed Qwen events."""
import asyncio
import json
from pathlib import Path
import sys
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from haiclaw.core import Evidence
from haiclaw.providers.ollama import make_adapter
from qwen_events import emit
async def main():
    adapter = make_adapter(json.loads((ROOT/'configs/vlm_local.json').read_text()), event_sink=emit)
    evidence = Evidence(str(uuid.uuid4()), 'desktop-preview', 'camera', float(sys.argv[2]),
                        float(sys.argv[2]), sys.argv[1])
    observation, record = await adapter.infer(evidence)
    emit({'type':'result', 'text':json.dumps(record['interpretation'], ensure_ascii=False, indent=2),
          'status':record['status'], 'evidence_id':evidence.id})
    return 0 if record['status']=='ok' else 1
if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
