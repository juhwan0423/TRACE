"""Local Ollama vision adapter shared by offline and live runners."""
import json
from tracebot.providers.single_frame_vlm import LocalChatTransport, SingleFrameVLM

def make_adapter(config, event_sink=None):
    transport = LocalChatTransport(config["endpoint"], config["timeout_seconds"])

    async def json_transport(payload):
        parts = payload["messages"][1]["content"]
        evidence_id = json.loads(parts[0]["text"])["evidence_id"]
        schema = {
            "type": "object", "additionalProperties": False,
            "properties": {
                "person_visible": {"type": "string", "enum": ["yes", "no", "uncertain"]},
                "posture": {"type": "string", "enum": ["standing", "seated", "lying", "unknown"]},
                "visible_risk_cues": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "observation_limitations": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "needs_more_observation": {"type": "boolean"},
                "evidence_ids": {"type": "array", "items": {"type": "string", "enum": [evidence_id]},
                                 "minItems": 1, "maxItems": 1},
            },
            "required": ["person_visible", "posture", "visible_risk_cues",
                         "observation_limitations", "needs_more_observation", "evidence_ids"],
        }
        native = {
            "model": payload["model"], "stream": False, "think": True,
            "format": schema,
            "options": {"temperature": 0, "num_predict": 4096, "num_ctx": 8192},
            "messages": [payload["messages"][0], {
                "role": "user", "content": parts[0]["text"],
                "images": [parts[1]["image_url"]["url"].split(",", 1)[1]]}],
        }
        if event_sink is None:
            return await transport(native)
        from .ollama_stream import stream_chat
        def emit(event):
            event_sink(dict(event, evidence_id=evidence_id))
        emit({'type': 'start', 'model': config['model']})
        try:
            result = await stream_chat(config['endpoint'], config['timeout_seconds'], native, emit)
            emit({'type': 'done'})
            return result
        except BaseException as error:
            emit({'type': 'error', 'text': type(error).__name__ + ': ' + str(error)})
            raise

    return SingleFrameVLM(json_transport, config["model"], config["timeout_seconds"],
                             decoder=lambda response: response["message"]["content"])
