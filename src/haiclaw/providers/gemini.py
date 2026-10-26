"""Explicit opt-in Gemini Robotics ER 2 transport. No key persistence/retries."""
import asyncio
import json
import math
import os
import urllib.error
import urllib.request

MODEL = 'gemini-robotics-er-2-preview'
SCHEMA = {
    'type':'object', 'additionalProperties':False,
    'properties': {
        'person_visible':{'type':'string','enum':['yes','no','uncertain']},
        'posture':{'type':'string','enum':['standing','seated','lying','unknown']},
        'visible_risk_cues':{'type':'array','items':{'type':'string'}},
        'observation_limitations':{'type':'array','items':{'type':'string'}},
        'needs_more_observation':{'type':'boolean'},
        'evidence_ids':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':1},
    },
    'required':['person_visible','posture','visible_risk_cues','observation_limitations','needs_more_observation','evidence_ids'],
}


def gemini_payload(request):
    content=request['messages'][1]['content']
    image=content[1]['image_url']['url']
    prefix='data:image/png;base64,'
    if not image.startswith(prefix):
        raise ValueError('PNG required')
    return {
        'systemInstruction':{'parts':[{'text':request['messages'][0]['content']}]},
        'contents':[{'role':'user','parts':[{'text':content[0]['text']},
                     {'inlineData':{'mimeType':'image/png','data':image[len(prefix):]}}]}],
        'generationConfig':{'temperature':0, 'maxOutputTokens':2048,
                            'responseFormat':{'text':{'mimeType':'APPLICATION_JSON','schema':SCHEMA}}},
    }


def response_text(envelope):
    candidates=envelope.get('candidates',[])
    if not candidates or candidates[0].get('finishReason')!='STOP':
        raise ValueError('blocked, incomplete or missing Gemini candidate')
    parts=candidates[0].get('content',{}).get('parts',[])
    return ''.join(p['text'] for p in parts if 'text' in p and not p.get('thought',False))


class GeminiTransport:
    def __init__(self, *, allow_api=False, timeout=20., model=MODEL):
        if not allow_api:
            raise ValueError('API disabled: explicit --allow-api required')
        if model!=MODEL:
            raise ValueError('Only the reviewed ER 2 model is enabled')
        if not math.isfinite(timeout) or timeout<=0:
            raise ValueError('invalid timeout')
        if not os.environ.get('GEMINI_API_KEY'):
            raise ValueError('Set GEMINI_API_KEY in your shell; do not put it in files')
        self.timeout, self.model = timeout, model

    async def __call__(self, payload):
        return await asyncio.to_thread(self._post, gemini_payload(payload))

    def _post(self, payload):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        endpoint=f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        request=urllib.request.Request(endpoint,json.dumps(payload).encode(),
            {'Content-Type':'application/json','x-goog-api-key':os.environ['GEMINI_API_KEY']})
        try:
            with opener.open(request,timeout=self.timeout) as response:
                raw=response.read(1024*1024+1)
        except urllib.error.HTTPError as error:
            # Do not log server error bodies/headers which could echo credentials.
            raise RuntimeError(f'Gemini HTTP {error.code}; no automatic retry') from None
        except Exception:
            raise RuntimeError('Gemini connection failed; no automatic retry') from None
        if len(raw)>1024*1024:
            raise ValueError('oversized Gemini response')
        return raw.decode('utf-8')
