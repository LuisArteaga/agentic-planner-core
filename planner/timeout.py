"""Hard wall-clock deadline enforcement for refinement drafts (ADR-0021).

The refinement subgraph runs synchronously on the CLI's main thread. Even with
``max_retries=0`` bounding each LLM call, a draft fans out across several
sequential calls (per-query ``web_search`` invokes, ``propose_options`` with
``thinking: max``, the ``apply_decision`` retry loop, …). Without a per-draft
ceiling those bounded calls still sum into hours.

This module wraps a synchronous callable with a Unix ``SIGALRM`` deadline that
interrupts the in-flight blocking syscall *in place* (raising
:class:`DraftTimeoutError`), so the master loop's per-draft ``try/except``
(ADR-0005) can record the draft as failed and continue the batch. A
thread-based timer cannot interrupt a sibling thread's blocking call — only a
signal delivered to the running thread can — so SIGALRM is the correct
primitive for the main-thread CLI path. When not on the main thread SIGALRM is
unavailable; the call then runs uncapped, relying on the per-call transport
timeout (``get_llm`` / ADR-0021) which still bounds every individual LLM call.
"""

import logging
import signal
import threading
from typing import Any, Callable, TypeVar

logger = logging.getLogger("planner.timeout")

T = TypeVar("T")


class DraftTimeoutError(Exception):
    """Raised when a single draft refinement exceeds its wall-clock budget."""


def run_with_wall_timeout(
    func: Callable[..., T],
    timeout_seconds: float | None,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Run ``func(*args, **kwargs)`` under a hard wall-clock deadline.

    On timeout the blocking call is interrupted in place via ``SIGALRM`` and a
    :class:`DraftTimeoutError` is raised (caught by the master loop's generic
    ``except Exception``, ADR-0005). ``timeout_seconds`` of ``None`` or ``<= 0``
    disables the deadline (the per-call transport timeout still applies).
    """
    if timeout_seconds is None or timeout_seconds <= 0:
        return func(*args, **kwargs)

    if threading.current_thread() is not threading.main_thread():
        # SIGALRM is only deliverable to the main thread. Fall back to an
        # uncapped run; every individual LLM call is still bounded by the
        # transport timeout (``get_llm`` / ADR-0021).
        logger.warning(
            "Draft wall-clock budget requires the main thread; running uncapped "
            "(per-call transport timeout still bounds each LLM call)."
        )
        return func(*args, **kwargs)

    def _handler(signum: int, frame: Any) -> None:
        raise DraftTimeoutError(
            f"Draft refinement exceeded {timeout_seconds}s wall-clock budget."
        )

    old_handler = signal.signal(signal.SIGALRM, _handler)
    old_timer = signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
    try:
        return func(*args, **kwargs)
    finally:
        # Cancel the alarm and restore the previous handler/timer exactly.
        signal.setitimer(signal.ITIMER_REAL, old_timer[0], old_timer[1])
        signal.signal(signal.SIGALRM, old_handler)
