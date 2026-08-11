"""Dedicated tests for the OpenRouter streaming client (planner/eval/openrouter.py).

Covers payload construction, SSE stream parsing, usage/cost/TTFT extraction,
the non-streaming fallback, retry behavior, and the usage-to-metrics mapping.
"""

import email.message
import json
from unittest.mock import patch

import pytest

from planner.eval import openrouter as or_mod


# --------------------------- _build_payload --------------------------------


def test_build_payload_minimal():
    p = or_mod._build_payload(
        "m1", [{"role": "user", "content": "hi"}], None, None, None, 0.0, True
    )
    assert p["model"] == "m1"
    assert p["messages"] == [{"role": "user", "content": "hi"}]
    assert p["temperature"] == 0.0
    assert p["stream"] is True
    assert "provider" not in p
    assert "max_tokens" not in p


def test_build_payload_with_routing_options_max_tokens():
    p = or_mod._build_payload(
        "m1",
        [{"role": "user", "content": "hi"}],
        ["Together", "DeepInfra"],
        {"thinking": "max"},
        4096,
        0.0,
        True,
    )
    assert p["provider"] == {
        "order": ["together", "deepinfra"],
        "allow_fallbacks": False,
    }
    assert p["thinking"] == "max"
    assert p["max_tokens"] == 4096


# --------------------------- _usage_to_metrics -----------------------------


def test_usage_to_metrics_full():
    m = or_mod._usage_to_metrics(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cost": 0.002,
        },
        ttft=0.42,
        latency=1.5,
    )
    assert m.prompt_tokens == 10
    assert m.completion_tokens == 5
    assert m.total_tokens == 15
    assert m.cost_usd == 0.002
    assert m.ttft_seconds == 0.42
    assert m.latency_seconds == 1.5


def test_usage_to_metrics_empty_and_null_ttft():
    m = or_mod._usage_to_metrics({}, ttft=None, latency=2.0)
    assert m.prompt_tokens is None
    assert m.cost_usd is None
    assert m.ttft_seconds is None  # never 0 for undefined TTFT
    assert m.latency_seconds == 2.0


# --------------------------- _parse_sse_stream ------------------------------


class FakeSSEResponse:
    """A fake iterable HTTP response yielding SSE lines as bytes."""

    status: int = 200

    def __init__(self, lines):
        self._lines = [line.encode("utf-8") for line in lines]
        self._idx = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._idx >= len(self._lines):
            raise StopIteration
        line = self._lines[self._idx]
        self._idx += 1
        return line

    def close(self):
        pass


def test_parse_sse_stream_extracts_content_usage_ttft():
    lines = [
        ": OPENROUTER PROCESSING",
        f"data: {json.dumps({'choices': [{'delta': {'content': 'Hello'}}]})}",
        f"data: {json.dumps({'choices': [{'delta': {'content': ' world'}}]})}",
        f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12, 'cost': 0.001}})}",
        "data: [DONE]",
    ]
    resp = FakeSSEResponse(lines)
    content, usage, ttft = or_mod._parse_sse_stream(resp)
    assert content == "Hello world"
    assert usage["prompt_tokens"] == 10
    assert usage["cost"] == 0.001
    assert ttft is not None and ttft >= 0.0


def test_parse_sse_stream_no_content_delta_ttft_none():
    """When no content delta is received, TTFT must be None (not 0)."""
    lines = [
        f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 5, 'completion_tokens': 0, 'total_tokens': 5}})}",
        "data: [DONE]",
    ]
    resp = FakeSSEResponse(lines)
    content, usage, ttft = or_mod._parse_sse_stream(resp)
    assert content == ""
    assert ttft is None
    assert usage["total_tokens"] == 5


def test_parse_sse_stream_skips_malformed_lines():
    lines = [
        "not a data line",
        "data: not json",
        f"data: {json.dumps({'choices': [{'delta': {'content': 'ok'}}]})}",
        "data: [DONE]",
    ]
    resp = FakeSSEResponse(lines)
    content, usage, ttft = or_mod._parse_sse_stream(resp)
    assert content == "ok"
    assert usage == {}


# --------------------------- stream_completion -----------------------------


@patch("planner.eval.openrouter.urllib.request.urlopen")
def test_stream_completion_success(mock_urlopen):
    lines = [
        f"data: {json.dumps({'choices': [{'delta': {'content': 'result'}}]})}",
        f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 3, 'completion_tokens': 1, 'total_tokens': 4, 'cost': 0.0001}})}",
        "data: [DONE]",
    ]
    mock_resp = FakeSSEResponse(lines)
    mock_resp.status = 200
    mock_urlopen.return_value = mock_resp

    content, metrics = or_mod.stream_completion(
        model="test/model",
        messages=[{"role": "user", "content": "hi"}],
        api_key="key",
    )
    assert content == "result"
    assert metrics.prompt_tokens == 3
    assert metrics.cost_usd == 0.0001
    assert metrics.ttft_seconds is not None


@patch("planner.eval.openrouter.urllib.request.urlopen")
def test_stream_completion_non_streaming_fallback(mock_urlopen):
    """When streaming fails, the non-streaming fallback returns content with ttft=None."""

    class FakeNonStreamResp:
        status = 200

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": "fallback result"}}],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
                        "cost": 0.0002,
                    },
                }
            ).encode("utf-8")

        def close(self):
            pass

    # First MAX_ATTEMPTS calls raise (simulating streaming failures),
    # then the non-streaming fallback succeeds.
    stream_error = OSError("connection reset")
    mock_urlopen.side_effect = [
        stream_error,
        stream_error,
        stream_error,
        stream_error,
        FakeNonStreamResp(),
    ]

    content, metrics = or_mod.stream_completion(
        model="test/model",
        messages=[{"role": "user", "content": "hi"}],
        api_key="key",
    )
    assert content == "fallback result"
    assert metrics.ttft_seconds is None  # non-streaming => no TTFT
    assert metrics.cost_usd == 0.0002


@patch("planner.eval.openrouter.urllib.request.urlopen")
@patch("planner.eval.openrouter.time.sleep", return_value=None)
def test_stream_completion_retries_on_429(mock_sleep, mock_urlopen):
    import urllib.error

    lines = [
        f"data: {json.dumps({'choices': [{'delta': {'content': 'ok'}}]})}",
        f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})}",
        "data: [DONE]",
    ]
    mock_resp = FakeSSEResponse(lines)
    mock_resp.status = 200
    mock_urlopen.side_effect = [
        urllib.error.HTTPError("url", 429, "Too Many", email.message.Message(), None),
        mock_resp,
    ]

    content, metrics = or_mod.stream_completion(
        model="test/model",
        messages=[{"role": "user", "content": "hi"}],
        api_key="key",
    )
    assert content == "ok"
    assert mock_urlopen.call_count == 2


@patch("planner.eval.openrouter.urllib.request.urlopen")
def test_stream_completion_4xx_not_retried(mock_urlopen):
    """A 400 (non-429 4xx) must not be retried — it raises immediately."""
    import urllib.error

    mock_urlopen.side_effect = urllib.error.HTTPError(
        "url", 400, "Bad Request", email.message.Message(), None
    )

    with pytest.raises(urllib.error.HTTPError):
        or_mod.stream_completion(
            model="test/model",
            messages=[{"role": "user", "content": "hi"}],
            api_key="key",
        )
    assert mock_urlopen.call_count == 1
