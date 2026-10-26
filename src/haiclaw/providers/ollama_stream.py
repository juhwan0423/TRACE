"""Bounded local Ollama streaming; observational events never alter policy input."""
import asyncio
import json
import time
import urllib.request
from .single_frame_vlm import LocalChatTransport


def read_stream(response, emit, timeout, started=None):
    started = time.monotonic() if started is None else started
    total = 0
    thinking, content = [], []
    while True:
        if time.monotonic() - started > timeout:
            raise TimeoutError('Ollama stream deadline')
        line = response.readline(1024 * 1024 + 1)
        if not line:
            raise ValueError('Ollama stream ended without done')
        total += len(line)
        if total > 1024 * 1024:
            raise ValueError('oversized Ollama stream')
        obj = json.loads(line)
        if 'error' in obj:
            raise RuntimeError(obj['error'])
        msg = obj.get('message', {})
        for key, target in [('thinking', thinking), ('content', content)]:
            text = msg.get(key, '')
            if text:
                target.append(text)
                emit({'type': key, 'text': text})
        if obj.get('done'):
            return json.dumps({'message': {'thinking': ''.join(thinking), 'content': ''.join(content)}})


async def stream_chat(endpoint, timeout, payload, emit):
    LocalChatTransport(endpoint, timeout)  # preserve loopback validation
    cancelled = __import__('threading').Event()
    def safe_emit(event):
        if not cancelled.is_set():
            emit(event)
    def post():
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(endpoint, json.dumps(dict(payload, stream=True)).encode(),
                                         {'Content-Type': 'application/json'})
        started = time.monotonic()
        with opener.open(request, timeout=timeout) as response:
            return read_stream(response, safe_emit, timeout, started)
    try:
        return await asyncio.to_thread(post)
    finally:
        cancelled.set()
