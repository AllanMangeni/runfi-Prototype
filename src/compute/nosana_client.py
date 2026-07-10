"""Nosana REST API compute client (credits-based, Python-native).

Uses the Nosana REST HTTP API with API-key authentication and dashboard
credits. This is the primary compute backend, using the REST path that
consumes dashboard credits (as opposed to the on-chain NOS token path).

Integration references (verified, not recalled):
- Routes: extracted from the published @nosana/api@2.6.1 npm package, the
  generated OpenAPI schema (schema.d.ts) and route modules.
- Docs: https://docs.nosana.io/api/jobs.html, /api/credits.html, /api/markets.html
- Base URL: https://dashboard.k8s.prd.nos.ci  (from @nosana/api defaults)
- Auth: `Authorization: Bearer nos_xxx`  (API key; takes precedence over wallet)
- Idempotency: `Idempotency-Key` header (optional for single ops; required for batch)
- IPFS pinning: via Pinata (POST https://api.pinata.cloud/pinning/pinJSONToIPFS),
  not a Nosana dashboard route. Returns ``{IpfsHash}``.

Verified routes (all relative to base URL):
- POST   /api/jobs/list                 body {ipfsHash, market, timeout?, node?}
- GET    /api/jobs/{address}            -> job object with ``state`` (int 0-3),
                                           ``ipfsJob``, ``ipfsResult``, ``jobResult``
- POST   /api/jobs/{address}/extend     body {seconds}
- POST   /api/jobs/{address}/stop
- POST   /api/jobs/list/batch           body {jobs:[...]} (Idempotency-Key required)
- GET    /api/credits/balance           -> {assignedCredits, reservedCredits, settledCredits}
- GET    /api/markets/                  (trailing slash) -> [market]

Job state enum: QUEUED=0, RUNNING=1, COMPLETED=2, STOPPED=3.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx
import structlog

from src.compute.base import ComputeBackendABC, ComputeError, JobResult, JobSpec, JobState

logger = structlog.get_logger(__name__)

_DEFAULT_NOSANA_BASE_URL = "https://dashboard.k8s.prd.nos.ci"
_DEFAULT_PINATA_BASE_URL = "https://api.pinata.cloud"
_JOB_LIST_PATH = "/api/jobs/list"
_JOB_GET_PATH = "/api/jobs/{address}"
_JOB_EXTEND_PATH = "/api/jobs/{address}/extend"
_JOB_STOP_PATH = "/api/jobs/{address}/stop"
_CREDITS_BALANCE_PATH = "/api/credits/balance"
_PINATA_PIN_PATH = "/pinning/pinJSONToIPFS"
_IDEMPOTENCY_HEADER = "Idempotency-Key"


@dataclass
class NosanaConfig:
    """Configuration for the Nosana REST API client.

    Args:
        api_key: Nosana dashboard API key (``nos_xxx``).
        ipfs_jwt: Pinata JWT for IPFS pinning.
        market_address: Optional default GPU market address.
        base_url: Nosana API base URL.
        pinata_base_url: Pinata API base URL.
    """

    api_key: str
    ipfs_jwt: str
    market_address: str | None = None
    base_url: str = _DEFAULT_NOSANA_BASE_URL
    pinata_base_url: str = _DEFAULT_PINATA_BASE_URL


class NosanaRestBackend(ComputeBackendABC):
    """Nosana REST API compute backend (credits, API-key auth)."""

    def __init__(
        self,
        config: NosanaConfig,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._config = config
        self._nosana_base_url = config.base_url.rstrip("/")
        self._pinata_base_url = config.pinata_base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._nosana_base_url,
                headers={"Authorization": f"Bearer {self._config.api_key}"},
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client. Safe to call multiple times."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _pin_job_definition(self, job_definition: dict) -> str:
        """Pin the job definition to IPFS via Pinata and return the CID.

        Raises:
            ComputeError: if the Pinata JWT is unset or the pin fails.
        """
        jwt = self._config.ipfs_jwt
        if not jwt:
            raise ComputeError(
                "ipfs_jwt is required to pin job definitions to IPFS via Pinata."
            )
        async with httpx.AsyncClient(
            base_url=self._pinata_base_url,
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=self._timeout,
        ) as pinata:
            try:
                resp = await pinata.post(_PINATA_PIN_PATH, json=job_definition)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ComputeError(f"IPFS pin via Pinata failed: {exc}") from exc
        data = resp.json()
        ipfs_hash = data.get("IpfsHash")
        if not ipfs_hash:
            raise ComputeError(f"Pinata response missing IpfsHash: {data}")
        logger.info("compute.ipfs_pinned", ipfs_hash=ipfs_hash)
        return ipfs_hash

    async def submit(self, spec: JobSpec) -> str:
        """Pin the job definition and post the job to a Nosana market.

        Raises:
            ComputeError: if pinning or posting fails.
        """
        ipfs_hash = await self._pin_job_definition(spec.job_definition)
        client = await self._ensure_client()
        body: dict[str, object] = {
            "ipfsHash": ipfs_hash,
            "timeout": spec.timeout_seconds,
        }
        market = spec.market or self._config.market_address
        if market:
            body["market"] = market
        headers: dict[str, str] = {}
        if spec.idempotency_key:
            headers[_IDEMPOTENCY_HEADER] = spec.idempotency_key
        try:
            resp = await client.post(_JOB_LIST_PATH, json=body, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComputeError(f"Nosana POST /api/jobs/list failed: {exc}") from exc
        data = resp.json()
        job_address = data.get("job")
        if not job_address:
            raise ComputeError(f"Nosana job post response missing 'job': {data}")
        credits_info = data.get("credits") or {}
        logger.info(
            "compute.job_submitted",
            job=job_address,
            run=data.get("run"),
            credits_used_usd=credits_info.get("creditsUsed"),
            cost_usd=credits_info.get("costUSD"),
        )
        return job_address

    async def get_state(self, job_address: str) -> JobState:
        """Fetch the current state of a job.

        Raises:
            ComputeError: if the GET fails or the state value is unknown.
        """
        client = await self._ensure_client()
        try:
            resp = await client.get(_JOB_GET_PATH.format(address=job_address))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComputeError(f"Nosana GET /api/jobs/{job_address} failed: {exc}") from exc
        data = resp.json()
        raw_state = data.get("state")
        if raw_state is None:
            raise ComputeError(f"Job {job_address} response missing 'state': {data}")
        try:
            return JobState(int(raw_state))
        except ValueError as exc:
            raise ComputeError(f"Job {job_address} has unknown state {raw_state!r}.") from exc

    async def get_result(self, job_address: str) -> JobResult:
        """Fetch the terminal result of a job, including its IPFS payload."""
        client = await self._ensure_client()
        try:
            resp = await client.get(_JOB_GET_PATH.format(address=job_address))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComputeError(f"Nosana GET /api/jobs/{job_address} failed: {exc}") from exc
        data = resp.json()
        state = JobState(int(data["state"]))
        job_status = data.get("jobStatus")
        failed = state is JobState.STOPPED and bool(job_status) and job_status != "ok"
        return JobResult(
            job_address=job_address,
            state=state,
            ipfs_result_hash=data.get("ipfsResult"),
            result=data.get("jobResult"),
            credits_used_usd=_to_decimal_usd(data),
            failed=failed,
            failure_detail=job_status if failed else None,
        )

    async def get_credits_balance(self) -> dict[str, object]:
        """Fetch the current credits balance (USD).

        Raises:
            ComputeError: if the GET fails.
        """
        client = await self._ensure_client()
        try:
            resp = await client.get(_CREDITS_BALANCE_PATH)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComputeError(f"Nosana GET /api/credits/balance failed: {exc}") from exc
        return resp.json()


def _to_decimal_usd(job_get_data: dict) -> Decimal | None:
    """Extract a USD cost Decimal from a GET-job response, if present."""
    cost = (job_get_data.get("credits") or {}).get("costUSD")
    if cost is None:
        return None
    return Decimal(str(cost))
