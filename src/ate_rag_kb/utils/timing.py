"""Lightweight step-level execution timer for retrieval pipeline observability.

Usage::

    timer = StepTimer()
    with timer.step("dense_search"):
        ...  # do work
    timer.record("manual_phase", 0.003)  # manual entry in seconds
    timings = timer.to_dict()
    # -> {"timing_dense_search_ms": 12.3, "timing_manual_phase_ms": 3.0}
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from types import TracebackType


class StepTimer:
    """Accumulates named timing entries using wall-clock ``perf_counter``.

    Thread safety: each call site should create its own instance.
    """

    def __init__(self) -> None:
        self._entries: dict[str, float] = {}

    @contextmanager
    def step(self, name: str):
        """Context manager that records wall time for *name* in milliseconds."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._entries[name] = elapsed_ms

    def record(self, name: str, seconds: float) -> None:
        """Manually record *seconds* for *name* (converted to ms)."""
        self._entries[name] = seconds * 1000.0

    def to_dict(self) -> dict[str, float]:
        """Return a new dict with ``timing_{name}_ms`` keys and ms values."""
        return {
            f"timing_{name}_ms": round(value, 1)
            for name, value in self._entries.items()
        }

    def total_seconds(self) -> float:
        """Return the sum of all recorded steps in seconds."""
        return sum(self._entries.values()) / 1000.0


class _StepContext:
    """Helper that bridges StepTimer.step() into ``with`` blocks."""

    __slots__ = ("_timer", "_name", "_start")

    def __init__(self, timer: StepTimer, name: str) -> None:
        self._timer = timer
        self._name = name
        self._start: float = 0.0

    def __enter__(self) -> None:
        self._start = time.perf_counter()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        self._timer._entries[self._name] = elapsed_ms
