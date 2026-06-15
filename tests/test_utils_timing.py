"""Unit tests for StepTimer utility."""

from __future__ import annotations

import time

from ate_rag_kb.utils.timing import StepTimer


class TestStepTimerContextManager:
    """Tests for the step() context manager."""

    def test_step_records_timing(self) -> None:
        timer = StepTimer()
        with timer.step("dense_search"):
            time.sleep(0.01)  # 10 ms

        result = timer.to_dict()
        assert "timing_dense_search_ms" in result
        assert result["timing_dense_search_ms"] >= 8.0  # allow small variance

    def test_step_records_even_on_exception(self) -> None:
        timer = StepTimer()
        try:
            with timer.step("failing_step"):
                raise ValueError("boom")
        except ValueError:
            pass

        result = timer.to_dict()
        assert "timing_failing_step_ms" in result

    def test_multiple_steps(self) -> None:
        timer = StepTimer()
        with timer.step("step_a"):
            pass
        with timer.step("step_b"):
            pass

        result = timer.to_dict()
        assert "timing_step_a_ms" in result
        assert "timing_step_b_ms" in result


class TestStepTimerManualRecord:
    """Tests for the record() method."""

    def test_record_manual_entry(self) -> None:
        timer = StepTimer()
        timer.record("manual_phase", 0.003)

        result = timer.to_dict()
        assert result["timing_manual_phase_ms"] == 3.0

    def test_record_overwrites_existing(self) -> None:
        timer = StepTimer()
        timer.record("phase", 0.01)
        timer.record("phase", 0.02)

        result = timer.to_dict()
        assert result["timing_phase_ms"] == 20.0


class TestStepTimerToDict:
    """Tests for the to_dict() method."""

    def test_key_format(self) -> None:
        timer = StepTimer()
        timer.record("search", 0.1)

        result = timer.to_dict()
        assert list(result.keys()) == ["timing_search_ms"]

    def test_values_are_ms_rounded(self) -> None:
        timer = StepTimer()
        timer.record("step", 0.12345)  # 123.45 ms

        result = timer.to_dict()
        assert result["timing_step_ms"] == 123.5  # rounded to 1 decimal

    def test_returns_new_dict_each_call(self) -> None:
        timer = StepTimer()
        timer.record("x", 0.1)

        dict1 = timer.to_dict()
        dict2 = timer.to_dict()
        assert dict1 is not dict2
        assert dict1 == dict2

    def test_empty_timer_returns_empty_dict(self) -> None:
        timer = StepTimer()
        assert timer.to_dict() == {}


class TestStepTimerTotalSeconds:
    """Tests for the total_seconds() method."""

    def test_total_seconds_sums_all(self) -> None:
        timer = StepTimer()
        timer.record("a", 0.1)
        timer.record("b", 0.2)

        assert timer.total_seconds() == 0.3

    def test_total_seconds_empty(self) -> None:
        timer = StepTimer()
        assert timer.total_seconds() == 0.0


class TestStepTimerImmutability:
    """Verify that returned dicts do not share state with the timer."""

    def test_to_dict_does_not_mutate_timer(self) -> None:
        timer = StepTimer()
        timer.record("step", 0.05)

        result = timer.to_dict()
        result["timing_step_ms"] = 9999.0  # mutate returned dict

        # Original timer is unaffected
        assert timer.to_dict()["timing_step_ms"] == 50.0
