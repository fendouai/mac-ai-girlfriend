"""Verify voice budgets stop the HTTP stream, and don't erase an actual answer."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from llm import LlamaCppLLM, limit_spoken_reply
from orchestrator import HexOrchestrator

assert limit_spoken_reply('第一句。第二句！第三句不要生成。', 40, 2) == ('第一句。第二句！', True)
assert limit_spoken_reply('你好呀，我在这里。', 40, 2) == ('你好呀，我在这里。', False)
long = '嗯。今天先好好休息一下，喝点水，然后我们可以出去散步放松心情，后面还有很多很多内容。'
limited, stopped = limit_spoken_reply(long, 40, 2)
assert stopped and len(limited)<=40 and '今天先好好休息' in limited and limited.endswith('。')
assert limit_spoken_reply(long, 0, 0) == (long, False)

class Response:
    def __init__(self):
        self.consumed=0
    def raise_for_status(self):
        pass
    def iter_lines(self):
        for text in ['第一句。','第二句！','此后不能继续生成。']:
            self.consumed += 1
            yield 'data: '+json.dumps({'choices':[{'delta':{'content':text}}]})

response=Response()
@contextmanager
def stream(*args, **kwargs):
    yield response

client=LlamaCppLLM(max_reply_chars=40,max_reply_sentences=2)
with patch('llm.httpx.stream',stream):
    assert client.generate([{'role':'user','content':'测试'}])=='第一句。第二句！'
assert response.consumed==2, 'Should stop before generating the third sentence'

# A cached browser persona is preserved, but receives the current voice budget.
session=HexOrchestrator.__new__(HexOrchestrator)
session.cfg={'llm':{'max_reply_chars':40}}
session.persona='默认人设'
session._persona_override='网页自定义人设：请详细回答。'
first=session._effective_persona()
assert first.startswith(session._persona_override) and '不超过40字' in first
session._persona_override=first
assert session._effective_persona()==first, 'Reconnection must not duplicate the policy suffix'
print(json.dumps(dict(passed=True,http_stream_chunks_consumed=response.consumed,
                      budget_chars=40,sentences=2)),flush=True)
