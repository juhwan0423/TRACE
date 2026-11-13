"""Append local model stream events for the desktop observer."""
import json
import os
import threading
import time
from pathlib import Path
LOCK = threading.Lock()
PATH = Path(__file__).resolve().parents[1] / ('artifacts/live_real2sim/qwen.jsonl' if os.environ.get('TRACE_SCENE', 'real2sim') == 'real2sim' else 'artifacts/live/qwen.jsonl')

def emit(event):
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOCK, PATH.open('a') as stream:
            stream.write(json.dumps(dict(event, wall_time=time.time()), ensure_ascii=False) + '\n')
    except OSError:
        pass  # a display failure must not change the incident decision
