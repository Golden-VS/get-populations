from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import BaseModel, ValidationError

from tam.ai import (AIBatchError, AIRefusal, CostCapReached, CostTracker,
                    call_parsed, estimate_cost)


class Item(BaseModel):
    x: int


class Batch(BaseModel):
    items: list[Item]


class FakeMessages:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response, exc, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.response


class FakeClient:
    def __init__(self, **kw):
        self.messages = FakeMessages(**kw)


def _resp(stop='end_turn', parsed=None, usage=None):
    return SimpleNamespace(
        stop_reason=stop, parsed_output=parsed,
        usage=usage or SimpleNamespace(input_tokens=1000, output_tokens=500,
                                       cache_creation_input_tokens=None,
                                       cache_read_input_tokens=None))


def test_usage_cost_math():
    t = CostTracker(100)
    cost = t.add_usage(SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000))
    assert cost == pytest.approx(24.0)
    assert t.spent == pytest.approx(24.0)
    t.add_usage(SimpleNamespace(input_tokens=None, output_tokens=None,
                                cache_creation_input_tokens=1_000_000,
                                cache_read_input_tokens=1_000_000))
    assert t.spent == pytest.approx(24.0 + 5.0 + 0.20)


def test_estimate_cost():
    # 10 items, batch 5 -> 2 batches; 1M in + 1M out per batch -> 2 * 24
    assert estimate_cost(10, 5, 1_000_000, 1_000_000) == pytest.approx(48.0)


def test_cap_stops_before_exceeding():
    t = CostTracker(1.0)
    t.spent = 0.90
    client = FakeClient(response=_resp())
    with pytest.raises(CostCapReached):
        call_parsed(client, t, system='s', user='u', output_model=Batch,
                    estimated_cost=0.20)
    assert client.messages.calls == []


def test_success_call_shape_and_usage():
    parsed = Batch(items=[Item(x=1)])
    client = FakeClient(response=_resp(parsed=parsed))
    t = CostTracker(10)
    out = call_parsed(client, t, system='sys', user='usr', output_model=Batch,
                      estimated_cost=0.1)
    assert out is parsed
    kw = client.messages.calls[0]
    assert kw['output_format'] is Batch
    assert kw['output_config'] == {'effort': 'medium'}
    assert 'output_config' not in kw['extra_body']
    assert 'thinking' not in kw
    assert kw['model'] == 'claude-opus-5-5'
    assert kw['max_tokens'] == 16000
    assert kw['system'] == [{'type': 'text', 'text': 'sys',
                             'cache_control': {'type': 'ephemeral'}}]
    assert kw['extra_body'] == {'fallbacks': 'default'}
    assert kw['extra_headers'] == {'anthropic-beta': 'server-side-fallback-2026-07-01'}
    assert t.spent > 0


def test_refusal_raises():
    class Resp:
        stop_reason = 'refusal'
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=0)

        @property
        def parsed_output(self):
            raise AssertionError('parsed_output mag niet gelezen worden')

    client = FakeClient(response=Resp())
    t = CostTracker(10)
    with pytest.raises(AIRefusal):
        call_parsed(client, t, system='s', user='u', output_model=Batch,
                    estimated_cost=0.1)
    assert t.spent == pytest.approx(4.0)


def test_api_error_wrapped_as_batch_error():
    req = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
    exc = anthropic.APIConnectionError(request=req)
    client = FakeClient(exc=exc)
    with pytest.raises(AIBatchError):
        call_parsed(client, CostTracker(10), system='s',
                    user='u', output_model=Batch, estimated_cost=0.1)


def test_validation_error_wrapped():
    with pytest.raises(ValidationError) as excinfo:
        Batch.model_validate({'items': 'x'})
    client = FakeClient(exc=excinfo.value)
    with pytest.raises(AIBatchError):
        call_parsed(client, CostTracker(10), system='s', user='u',
                    output_model=Batch, estimated_cost=0.1)
