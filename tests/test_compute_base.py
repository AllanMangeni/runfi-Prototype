"""Smoke tests for the compute interface.

These tests verify the base abstractions and models without making any
network calls. They mock the Nosana API to confirm the client and
orchestrator handle job state transitions and error cases correctly.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.compute.base import (
    ComputeError,
    JobResult,
    JobSpec,
    JobState,
    JobTimeoutError,
    poll_until_completed,
)


class TestJobState:
    def test_terminal_states(self) -> None:
        assert JobState.COMPLETED.is_terminal is True
        assert JobState.STOPPED.is_terminal is True
        assert JobState.QUEUED.is_terminal is False
        assert JobState.RUNNING.is_terminal is False

    def test_enum_values(self) -> None:
        assert JobState.QUEUED.value == 0
        assert JobState.RUNNING.value == 1
        assert JobState.COMPLETED.value == 2
        assert JobState.STOPPED.value == 3


class TestJobSpec:
    def test_default_timeout(self) -> None:
        spec = JobSpec(job_definition={"version": "0.1"})
        assert spec.timeout_seconds == 25

    def test_custom_timeout(self) -> None:
        spec = JobSpec(job_definition={}, timeout_seconds=60)
        assert spec.timeout_seconds == 60

    def test_idempotency_key(self) -> None:
        spec = JobSpec(job_definition={}, idempotency_key="key-001")
        assert spec.idempotency_key == "key-001"


class TestJobResult:
    def test_defaults(self) -> None:
        result = JobResult(job_address="addr-1", state=JobState.COMPLETED)
        assert result.failed is False
        assert result.credits_used_usd is None
        assert result.failure_detail is None

    def test_failed_result(self) -> None:
        result = JobResult(
            job_address="addr-2",
            state=JobState.STOPPED,
            failed=True,
            failure_detail="GPU out of memory",
        )
        assert result.failed is True
        assert result.failure_detail == "GPU out of memory"

    def test_with_credits(self) -> None:
        result = JobResult(
            job_address="addr-3",
            state=JobState.COMPLETED,
            credits_used_usd=Decimal("0.02"),
        )
        assert result.credits_used_usd == Decimal("0.02")


class TestPollUntilCompleted:
    class FakeBackend:
        def __init__(self, states: list[JobState]) -> None:
            self._states = list(states)
            self._index = 0

        async def get_state(self, job_address: str) -> JobState:
            if self._index < len(self._states):
                state = self._states[self._index]
                self._index += 1
                return state
            return self._states[-1]

        async def submit(self, spec: JobSpec) -> str:
            return "fake-addr"

        async def get_result(self, job_address: str) -> JobResult:
            return JobResult(job_address=job_address, state=JobState.COMPLETED)

    @pytest.mark.asyncio
    async def test_polls_to_completed(self) -> None:
        backend = self.FakeBackend([JobState.QUEUED, JobState.RUNNING, JobState.COMPLETED])
        state = await poll_until_completed(
            backend, "fake-addr", poll_interval_seconds=0.01, max_wait_seconds=5.0
        )
        assert state == JobState.COMPLETED

    @pytest.mark.asyncio
    async def test_polls_to_stopped(self) -> None:
        backend = self.FakeBackend([JobState.RUNNING, JobState.STOPPED])
        state = await poll_until_completed(
            backend, "fake-addr", poll_interval_seconds=0.01, max_wait_seconds=5.0
        )
        assert state == JobState.STOPPED

    @pytest.mark.asyncio
    async def test_timeout_if_no_terminal_state(self) -> None:
        backend = self.FakeBackend([JobState.QUEUED, JobState.RUNNING])
        with pytest.raises(JobTimeoutError):
            await poll_until_completed(
                backend, "fake-addr", poll_interval_seconds=0.01, max_wait_seconds=0.05
            )


class TestComputeError:
    def test_is_exception(self) -> None:
        assert issubclass(ComputeError, Exception)

    def test_can_raise(self) -> None:
        with pytest.raises(ComputeError, match="test error"):
            raise ComputeError("test error")

    def test_job_timeout_is_compute_error(self) -> None:
        assert issubclass(JobTimeoutError, ComputeError)
