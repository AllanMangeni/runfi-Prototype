"""Nosana on-chain compute backend (NOS tokens / Solana) — STUB.

This is the DeFi-native alternative to ``NosanaRestBackend``. It posts jobs
directly on-chain via the Nosana Solana program, paying in NOS tokens.
Both backends implement ``ComputeBackend`` so the orchestrator selects
between ``nosana-rest`` (credits) and ``nosana-onchain`` (NOS tokens).

NOT IMPLEMENTED. Deferred in favour of the REST/credits backend. The on-chain
path remains a strategic option for organisations that prefer NOS tokens
over dashboard credits.

Integration references (verified, not recalled):
- solders (Rust-backed Solana SDK): https://mango.markets/solders/latest/
- Nosana program IDL: https://github.com/nosana-ci/nosana-idl
- Nosana does not ship a Python SDK (verified against npm registry).

When the on-chain path is commissioned, use solders==0.31 and anchorpy
for IDL bindings.
"""

from __future__ import annotations

from src.compute.base import ComputeBackendABC, ComputeError, JobResult, JobSpec, JobState


class NosanaOnchainBackend(ComputeBackendABC):
    """Nosana on-chain compute backend (NOS tokens). STUB — not implemented.

    Raises:
        ComputeError: on any call, until implemented.
    """

    def __init__(self, config: object) -> None:
        self._config = config

    async def submit(self, spec: JobSpec) -> str:
        raise ComputeError("NosanaOnchainBackend is not implemented (deferred).")

    async def get_state(self, job_address: str) -> JobState:
        raise ComputeError("NosanaOnchainBackend is not implemented (deferred).")

    async def get_result(self, job_address: str) -> JobResult:
        raise ComputeError("NosanaOnchainBackend is not implemented (deferred).")
