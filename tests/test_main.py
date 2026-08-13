"""Tests for refine-CLI helpers (planner/__main__.py)."""

import json
from unittest.mock import MagicMock

import pytest
import requests

from planner.__main__ import _check_github_rate_limit


def _make_rate_limit_response(remaining: int) -> tuple[requests.Response, MagicMock]:
    """Build a rate-limit response and a close() spy (to assert no CLOSE-WAIT leak)."""
    resp = requests.Response()
    resp.status_code = 200
    resp._content = json.dumps(
        {"resources": {"core": {"remaining": remaining}}}
    ).encode("utf-8")
    resp.encoding = "utf-8"
    close_mock = MagicMock(name="close")
    resp.close = close_mock
    return resp, close_mock


def test_check_github_rate_limit_returns_remaining_and_closes_socket():
    session = MagicMock(spec=requests.Session)
    resp, close_mock = _make_rate_limit_response(4999)
    session.get.return_value = resp

    remaining, required = _check_github_rate_limit(session, 10)

    assert remaining == 4999
    # max(50, draft_count * 3) => max(50, 30) == 50
    assert required == 50
    session.get.assert_called_once_with("https://api.github.com/rate_limit")
    # The response was used as a context manager -> close() called (no CLOSE-WAIT leak, #71).
    close_mock.assert_called_once()


def test_check_github_rate_limit_required_scales_with_draft_count():
    session = MagicMock(spec=requests.Session)
    resp, close_mock = _make_rate_limit_response(5000)
    session.get.return_value = resp

    remaining, required = _check_github_rate_limit(session, 20)

    assert remaining == 5000
    # max(50, 20 * 3) == 60
    assert required == 60
    close_mock.assert_called_once()


def test_check_github_rate_limit_raises_on_http_error():
    session = MagicMock(spec=requests.Session)
    resp, close_mock = _make_rate_limit_response(0)
    resp.raise_for_status = MagicMock(side_effect=requests.HTTPError("403 Forbidden"))
    session.get.return_value = resp

    with pytest.raises(requests.HTTPError):
        _check_github_rate_limit(session, 5)
    # Even on error the context manager must close the socket.
    close_mock.assert_called_once()
