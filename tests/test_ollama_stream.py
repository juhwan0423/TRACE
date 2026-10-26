import io
import json
import unittest
from haiclaw.providers.ollama_stream import read_stream

class StreamTests(unittest.TestCase):
    def test_chunks_preserve_thinking_and_final_content(self):
        events=[]
        rows=[{'message':{'thinking':'look '},'done':False},
              {'message':{'thinking':'again','content':'{"a":'},'done':False},
              {'message':{'content':'1}'},'done':True}]
        result=json.loads(read_stream(io.BytesIO(b''.join(json.dumps(r).encode()+b'\n' for r in rows)),events.append,2))
        self.assertEqual(result['message'],{'thinking':'look again','content':'{"a":1}'})
        self.assertEqual([e['type'] for e in events],['thinking','thinking','content','content'])
    def test_incomplete_stream_is_not_success(self):
        with self.assertRaisesRegex(ValueError,'without done'):
            read_stream(io.BytesIO(b'{"message":{"content":"{}"}}\n'),lambda e:None,2)
    def test_server_error_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError,'unavailable'):
            read_stream(io.BytesIO(b'{"error":"unavailable"}\n'),lambda e:None,2)
    def test_oversized_stream_rejected(self):
        with self.assertRaisesRegex(ValueError,'oversized'):
            read_stream(io.BytesIO(b'x'*(1024*1024+1)),lambda e:None,2)
