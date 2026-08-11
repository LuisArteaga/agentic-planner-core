"""OpenRouter streaming chat-completions client for the eval suite.

Distinct from ``scripts/review.py``'s non-streaming ``urllib`` call: the eval
suite requires Time-To-First-Token (TTFT) measurement (ADR-0003 keeps
OpenRouter as the sole gateway), which demands SSE streaming. The
``usage`` object — including ``cost`` — is returned in the final SSE chunk.

Edge case handling (issue #43):
* Non-streaming models: if the response is not an SSE stream, TTFT is logged
  as ``None`` (not 0).
* Rate limits (200 samples x judges = ~1000 calls): exponential backoff with
  retry on 429 / 5xx.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from planner.eval.models import JudgeMetrics

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MAX_ATTEMPTS = 4


def _build_payload(
    model: str,
    messages: List[Dict[str, str]],
    routing: Optional[List[str]],
    options: Optional[Dict[str, Any]],
    max_tokens: Optional[int],
    temperature: float,
    stream: bool,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if routing:
        payload["provider"] = {
            "order": [r.lower() for r in routing],
            "allow_fallbacks": False,
        }
    if options:
        payload.update(options)
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return payload


def _request(
    payload: Dict[str, Any], api_key: str, timeout: float
) -> Tuple[Any, int, str]:
    """Issue a POST and return ``(http_response, status_code, body_text)``.

    For streaming requests ``http_response`` is the raw response object
    (iterable line-by-line) and ``body_text`` is empty. For non-streaming
    requests ``http_response`` is ``None`` and ``body_text`` holds the body.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_ENDPOINT,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "agentic-planner-core/eval-suite",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)  # nosemgrep
    status = resp.status if hasattr(resp, "status") else 200
    if payload.get("stream"):
        return resp, status, ""
    body = resp.read().decode("utf-8")
    resp.close()
    return None, status, body


def _parse_sse_stream(
    resp: Any,
) -> Tuple[str, Dict[str, Any], Optional[float]]:
    """Consume an SSE response, returning ``(content, usage, ttft_seconds)``.

    ``ttft_seconds`` is the wall-clock time from call start to the first
    non-empty content delta. It is ``None`` if no content delta was ever
    received (e.g. an immediate error/final chunk).
    """
    content_parts: List[str] = []
    usage: Dict[str, Any] = {}
    ttft: Optional[float] = None
    stream_start = time.perf_counter()

    for raw_line in resp:
        if not raw_line:
            continue
        line = (
            raw_line.decode("utf-8").rstrip("\r\n")
            if isinstance(raw_line, (bytes, bytearray))
            else raw_line.rstrip("\r\n")
        )
        if not line:
            continue
        if line.startswith(":"):  # keepalive comment
            continue
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:") :].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                if ttft is None:
                    ttft = time.perf_counter() - stream_start
                content_parts.append(piece)
        if chunk.get("usage"):
            usage = chunk["usage"]
    resp.close()
    return "".join(content_parts), usage, ttft


def stream_completion(
    model: str,
    messages: List[Dict[str, str]],
    api_key: str,
    routing: Optional[List[str]] = None,
    options: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    temperature: float = 0.0,
    timeout: float = 180.0,
) -> Tuple[str, JudgeMetrics]:
    """Call OpenRouter with streaming and return ``(content, metrics)``.

    The metrics carry TTFT and ``usage`` (tokens + cost). When a model does
    not support streaming the call transparently falls back to a
    non-streaming request and reports ``ttft_seconds=None`` (issue edge case:
    never log 0 for an undefined TTFT).
    """
    last_error: Optional[str] = None
    call_start = time.perf_counter()

    for attempt in range(MAX_ATTEMPTS):
        try:
            payload = _build_payload(
                model, messages, routing, options, max_tokens, temperature, stream=True
            )
            resp, status, body = _request(payload, api_key, timeout)
            if status != 200:
                last_error = f"HTTP {status}: {body[:300]}"
                raise RuntimeError(last_error)
            content, usage, ttft = _parse_sse_stream(resp)
            latency = time.perf_counter() - call_start
            return content, _usage_to_metrics(usage, ttft, latency)
        except urllib.error.HTTPError as e:
            # 429 / 5xx are retriable; 4xx (non-429) are not.
            if e.code == 429 or 500 <= e.code < 600:
                last_error = f"HTTP {e.code}"
                _backoff(attempt)
                continue
            raise
        except (urllib.error.URLError, RuntimeError, OSError) as e:
            last_error = str(e)
            _backoff(attempt)
            continue

    # Final fallback: a single non-streaming attempt so TTFT is None but we
    # still obtain a verdict when a model refuses to stream.
    try:
        payload = _build_payload(
            model, messages, routing, options, max_tokens, temperature, stream=False
        )
        _resp, status, body = _request(payload, api_key, timeout)
        latency = time.perf_counter() - call_start
        data = json.loads(body) if body else {}
        if "error" in data:
            raise RuntimeError(str(data["error"]))
        content = ""
        choices = data.get("choices") or []
        if choices:
            content = choices[0].get("message", {}).get("content", "") or ""
        usage = data.get("usage") or {}
        return content, _usage_to_metrics(usage, None, latency)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"OpenRouter call failed after {MAX_ATTEMPTS} retries + non-streaming fallback: "
            f"{last_error}; fallback error: {e}"
        )


def _usage_to_metrics(
    usage: Dict[str, Any],
    ttft: Optional[float],
    latency: float,
) -> JudgeMetrics:
    return JudgeMetrics(
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        cost_usd=usage.get("cost"),
        ttft_seconds=ttft,
        latency_seconds=latency,
    )


def _backoff(attempt: int) -> None:
    """Exponential backoff: 4, 8, 16 seconds (mirrors review.py)."""
    import time as _time

    _time.sleep((2**attempt) * 4)
