"""Tests for the per-draft wall-clock budget utility (ADR-0021)."""

import signal
import threading
import time

import pytest

from planner.timeout import DraftTimeoutError, run_with_wall_timeout


def test_returns_result_when_within_budget():
    assert run_with_wall_timeout(lambda: 42, 5.0) == 42


def test_no_budget_when_none_or_zero():
    # None / non-positive -> uncapped (per-call transport timeout still bounds).
    assert run_with_wall_timeout(lambda: "ok", None) == "ok"
    assert run_with_wall_timeout(lambda: "ok", 0) == "ok"
    assert run_with_wall_timeout(lambda: "ok", -1) == "ok"


def test_raises_draft_timeout_error_on_overrun():
    with pytest.raises(DraftTimeoutError):
        run_with_wall_timeout(lambda: time.sleep(5), 0.2)


def test_timeout_error_message_contains_budget():
    try:
        run_with_wall_timeout(lambda: time.sleep(5), 0.1)
    except DraftTimeoutError as e:
        assert "0.1s" in str(e)


def test_passes_args_and_kwargs():
    def add(a, b, c=0):
        return a + b + c

    assert run_with_wall_timeout(add, 5.0, 1, 2, c=3) == 6


def test_restores_prior_signal_handler():
    prev = signal.getsignal(signal.SIGALRM)
    try:
        run_with_wall_timeout(lambda: None, 5.0)
    finally:
        pass
    assert signal.getsignal(signal.SIGALRM) is prev


def test_no_alarm_pending_after_run():
    # No leftover itimer after a normal completion.
    run_with_wall_timeout(lambda: 1, 5.0)
    remaining, _ = signal.getitimer(signal.ITIMER_REAL)
    assert remaining == 0.0


def test_off_main_thread_runs_uncapped_without_alarm():
    """Off the main thread SIGALRM is unavailable: run uncapped (no raise)."""

    result: dict[str, object] = {}

    def worker():
        # A budget that *would* fire on the main thread must NOT raise here.
        result["value"] = run_with_wall_timeout(lambda: time.sleep(0.3), 0.1)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert result["value"] is None
