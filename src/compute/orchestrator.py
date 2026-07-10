"""Compute backend orchestrator: select between Nosana backends.

Selects between the Nosana REST (credits) and Nosana on-chain (NOS tokens)
backends per configuration, with automatic fallback on failure.
"""

from __future__ import annotations

import structlog

from src.compute.base import (
    ComputeBackend,
    ComputeError,
    JobResult,
    JobSpec,
    JobState,
    JobTimeoutError,
    poll_until_completed,
)
from src.compute.nosana_client import NosanaConfig, NosanaRestBackend

logger = structlog.get_logger(__name__)


class ComputeOrchestrator:
    """Selects a Nosana compute backend and manages fallback on failure."""

    def __init__(
        self,
        config: NosanaConfig,
        compute_backend: str = "nosana-rest",
        *,
        fallback: ComputeBackend | None = None,
    ) -> None:
        self._config = config
        self._compute_backend = compute_backend
        self._primary = self._select_primary(config, compute_backend)
        self._fallback = fallback

    def _select_primary(self, config: NosanaConfig, compute_backend: str) -> ComputeBackend:
        if compute_backend == "nosana-rest":
            return NosanaRestBackend(config)
        if compute_backend == "nosana-onchain":
            from src.compute.nosana_onchain import NosanaOnchainBackend

            return NosanaOnchainBackend(config)
        raise ComputeError(f"Unknown compute_backend: {compute_backend!r}")

    async def run(self, spec: JobSpec) -> JobResult:
        """Submit a job to the primary backend, poll to completion, fall back on failure.

        Raises:
            ComputeError: if both primary and fallback fail (or no fallback).
        """
        try:
            job_address = await self._primary.submit(spec)
            await poll_until_completed(
                self._primary,
                job_address,
                poll_interval_seconds=2.0,
                max_wait_seconds=float(spec.timeout_seconds) + 5.0,
            )
            return await self._primary.get_result(job_address)
        except (JobTimeoutError, ComputeError) as exc:
            logger.warning(
                "compute.primary_failed",
                backend=self._compute_backend,
                error=str(exc),
            )
            if self._fallback is None:
                raise
            return await self._engage_fallback(spec, exc)

    async def _engage_fallback(self, spec: JobSpec, primary_error: Exception) -> JobResult:
        """Run the job on the fallback backend."""
        logger.info("compute.fallback_engaged", reason=str(primary_error))
        try:
            job_address = await self._fallback.submit(spec)
            await poll_until_completed(
                self._fallback,
                job_address,
                poll_interval_seconds=2.0,
                max_wait_seconds=30.0,
            )
            return await self._fallback.get_result(job_address)
        except (JobTimeoutError, ComputeError) as exc:
            raise ComputeError(
                f"Both primary and fallback compute failed. "
                f"Primary: {primary_error}. Fallback: {exc}."
            ) from exc

    async def close(self) -> None:
        """Release backend resources (e.g. HTTP clients)."""
        if hasattr(self._primary, "close"):
            await self._primary.close()
        if self._fallback is not None and hasattr(self._fallback, "close"):
            await self._fallback.close()
