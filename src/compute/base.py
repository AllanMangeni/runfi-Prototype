"""Compute backend interface and job polling state machine.

Defines the backend-agnostic ``ComputeBackend`` interface plus a polling state
machine (``poll_until_completed``) for retrieving job results without webhooks,
since Nosana's REST API offers no webhook (verified against @nosana/api@2.6.1).

Implementations:
- ``NosanaRestBackend`` — REST API / dashboard credits.
- ``NosanaOnchainBackend`` — NOS tokens / Solana (stubbed).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from decimal import Decimal
from enum import IntEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, JsonValue


class JobState(IntEnum):
    """Nosana job lifecycle states (verified against @nosana/api@2.6.1).

    The REST GET-job endpoint returns ``state`` as an integer matching the
    on-chain ``JobState`` enum: QUEUED=0, RUNNING=1, COMPLETED=2, STOPPED=3.
    Failure is signalled via the separate ``jobStatus`` string field.
    """

    QUEUED = 0
    RUNNING = 1
    COMPLETED = 2
    STOPPED = 3

    @property
    def is_terminal(self) -> bool:
        return self in (JobState.COMPLETED, JobState.STOPPED)


class JobSpec(BaseModel):
    """A request to run a compute job (e.g. an embedding batch).

    The ``job_definition`` is the Nosana job-definition JSON
    (version "0.1", type "container", ops[]). It is pinned to IPFS by the
    backend before the job is posted to a market.
    """

    job_definition: dict[str, JsonValue]
    market: str | None = None
    timeout_seconds: int = Field(default=25, ge=1)
    idempotency_key: str | None = None


class JobResult(BaseModel):
    """The outcome of a completed compute job."""

    job_address: str
    state: JobState
    ipfs_result_hash: str | None = None
    result: dict[str, JsonValue] | None = None
    credits_used_usd: Decimal | None = None
    failed: bool = False
    failure_detail: str | None = None


@runtime_checkable
class ComputeBackend(Protocol):
    """Backend-agnostic compute interface."""

    async def submit(self, spec: JobSpec) -> str: ...

    async def get_state(self, job_address: str) -> JobState: ...

    async def get_result(self, job_address: str) -> JobResult: ...


class ComputeError(Exception):
    """Raised when a compute backend operation fails."""


class JobTimeoutError(ComputeError):
    """Raised when a job does not reach a terminal state within the poll window."""


async def poll_until_completed(
    backend: ComputeBackend,
    job_address: str,
    *,
    poll_interval_seconds: float = 2.0,
    max_wait_seconds: float = 30.0,
) -> JobState:
    """Poll a backend until a job reaches a terminal state or times out.

    Nosana's REST API offers no webhook (verified), so we poll
    ``get_state`` until terminal. The default 30s max window aligns with
    the Nosana job timeout default of 25s plus polling margin.

    Raises:
        JobTimeoutError: if the job does not complete within ``max_wait_seconds``.
        ComputeError: if the backend raises during polling.
    """
    elapsed = 0.0
    while elapsed < max_wait_seconds:
        state = await backend.get_state(job_address)
        if state.is_terminal:
            return state
        await asyncio.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds
    raise JobTimeoutError(
        f"Job {job_address} did not reach a terminal state within "
        f"{max_wait_seconds}s (last state: {state.name})."
    )


class ComputeBackendABC(ABC):
    """Abstract base class form of the ``ComputeBackend`` protocol."""

    @abstractmethod
    async def submit(self, spec: JobSpec) -> str: ...

    @abstractmethod
    async def get_state(self, job_address: str) -> JobState: ...

    @abstractmethod
    async def get_result(self, job_address: str) -> JobResult: ...


FallbackHandler = Callable[[JobSpec, Exception], Awaitable[JobResult]]
