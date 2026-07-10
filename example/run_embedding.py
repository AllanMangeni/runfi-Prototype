#!/usr/bin/env python3
"""Example: submit an embedding job to Nosana and retrieve the result.

Prerequisites:
    - Set NOSANA_API_KEY, PINATA_JWT, and optionally NOSANA_MARKET_ADDRESS
      in your environment or edit the values below.
    - Build and push the inference container (see inference/README.md).
    - Set WORKER_IMAGE to the pushed image reference.

Usage:
    python example/run_embedding.py
"""

from __future__ import annotations

import asyncio
import json
import os

from src.compute.base import JobSpec
from src.compute.nosana_client import NosanaConfig, NosanaRestBackend
from src.compute.orchestrator import ComputeOrchestrator


async def main() -> None:
    config = NosanaConfig(
        api_key=os.environ["NOSANA_API_KEY"],
        ipfs_jwt=os.environ["PINATA_JWT"],
        market_address=os.environ.get("NOSANA_MARKET_ADDRESS"),
    )

    orchestrator = ComputeOrchestrator(config, compute_backend="nosana-rest")

    # Build a job definition for the inference container
    job_def = {
        "version": "0.1",
        "type": "container",
        "ops": [
            {
                "type": "container/run",
                "id": "inference-job",
                "args": {
                    "image": os.environ["WORKER_IMAGE"],
                    "cmd": [
                        "curl", "-s", "-X", "POST",
                        "http://localhost:8000/embed",
                        "-H", "Content-Type: application/json",
                        "-d", json.dumps({
                            "texts": [
                                "INBOUND 100.00 USDC 2026-06-24 | Payment received",
                                "OUTBOUND 50.00 USDC 2026-06-24 | Transfer sent",
                            ],
                            "model": "all-mpnet-base-v2",
                        }),
                    ],
                    "gpu": True,
                    "timeout": 120,
                    "env": {
                        "EMBEDDING_MODEL": "sentence-transformers/all-mpnet-base-v2",
                        "LLM_MODEL": "Qwen/Qwen2.5-3B-Instruct",
                    },
                },
            }
        ],
    }

    spec = JobSpec(
        job_definition=job_def,
        timeout_seconds=120,
    )

    print(f"Submitting job to Nosana (market: {config.market_address or 'default'})...")
    result = await orchestrator.run(spec)
    print(f"Job completed. State: {result.state.name}")
    print(f"Result: {result.result}")
    if result.credits_used_usd is not None:
        print(f"Credits used: ${result.credits_used_usd}")

    await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
