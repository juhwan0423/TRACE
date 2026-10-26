#!/usr/bin/env python3
"""Export selected historical development results without images or model prose.

Raw artifacts are local and intentionally not shipped. A fresh checkout can read
reports/evidence/checkpoint.json; regeneration requires the original result files.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = [
    ('closed_loop', '263c92fc-bb26-492b-869d-d822a8e2e2ab'),
    ('harness', '2ea9500a-f344-465e-b250-8ed6845d4c10'),
    ('harness', '505ab74c-3903-49cf-aedc-a27f8f7bdc70'),
    ('harness', '1d7ed205-0500-4626-b385-1e675d99f5df'),
    ('harness', 'c83e19de-077a-42d6-a979-ccc113d34d1b'),
]
FIELDS = ('episode', 'mode', 'planner', 'model', 'evaluation_case', 'completed',
          'state', 'wall_seconds', 'agent_decisions', 'executed_tools',
          'agent_cycle_exercised')


def main():
    records = []
    for family, episode in RUNS:
        path = ROOT / 'artifacts' / family / episode / 'result.json'
        raw = path.read_bytes()
        data = json.loads(raw)
        record = {key: data[key] for key in FIELDS if key in data}
        record.update(family=family, source=str(path.relative_to(ROOT)),
                      source_sha256=hashlib.sha256(raw).hexdigest())
        # Preserve absent vs null: older runs did not record all fields.
        for key in ('error', 'stop_error'):
            if key in data:
                record[key + '_present'] = data[key] is not None
        record['tool_results'] = [
            {key: event[key] for key in (
                'wall_elapsed', 'sim_time', 'tool', 'target', 'status',
                'latency_wall_seconds', 'valid', 'accepted') if key in event}
            for event in data.get('trace', []) if event.get('kind') == 'tool_result'
        ]
        record['incident_events'] = [
            {key: event[key] for key in ('time', 'state', 'motion', 'attempt_id',
              'request_fresh_frame', 'local_alert') if key in event}
            for event in data.get('incident_events', data.get('events', []))
        ]
        records.append(record)
    output = {
        'schema_version': 1,
        'selection': 'Selected development checkpoints, not a benchmark dataset.',
        'limitations': [
            'Historical runs predate the final post-arrival and viewpoint fixes.',
            'No source commit was recorded per run; do not attribute these to the export commit.',
            'Fixture perception/motion is not real vision or navigation validation.',
            'completed includes escalated_unknown and does not mean correct resolution.',
            'Absent fields were not recorded; raw images and model text are excluded.',
            'Raw local result hashes support identification, not independent verification.',
        ],
        'runs': records,
    }
    target = ROOT / 'reports/evidence/checkpoint.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n')
    print(target.relative_to(ROOT))


if __name__ == '__main__':
    main()
