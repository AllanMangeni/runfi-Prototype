#!/usr/bin/env python3
"""Example: cosine similarity between two transaction descriptions using Nosana embeddings.

Generates embeddings for two transaction texts via the inference container
(POST /embed), then computes cosine similarity between them. This demonstrates
how Nosana GPU compute powers vector comparison — the foundation of fuzzy
matching — without revealing any proprietary scoring weights or thresholds.

Usage:
    # Run against the local inference container
    python example/similarity_demo.py --local

    # Run against embeddings returned from a Nosana job
    python example/similarity_demo.py --remote
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Any


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns a value in [-1.0, 1.0] where 1.0 means identical direction.
    This is the standard vector similarity metric — no proprietary weighting.
    """
    if len(a) != len(b):
        raise ValueError(f"Vector dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(ai * bi for ai, bi in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(ai * ai for ai in a))
    norm_b = math.sqrt(sum(bi * bi for bi in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def embed_local(texts: list[str], url: str = "http://localhost:8000") -> list[list[float]]:
    """Call the local inference container's /embed endpoint."""
    body = json.dumps({"texts": texts}).encode()
    req = urllib.request.Request(
        f"{url}/embed",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["embeddings"]


def embed_remote(texts: list[str]) -> list[list[float]]:
    """Submit an embedding job to Nosana and retrieve the result.

    Requires NOSANA_API_KEY, PINATA_JWT, and WORKER_IMAGE environment variables.
    """
    from src.compute.nosana_client import NosanaConfig, NosanaRestBackend
    from src.compute.base import JobSpec
    from src.compute.orchestrator import ComputeOrchestrator

    config = NosanaConfig(
        api_key=os.environ["NOSANA_API_KEY"],
        ipfs_jwt=os.environ["PINATA_JWT"],
        market_address=os.environ.get("NOSANA_MARKET_ADDRESS"),
    )
    orchestrator = ComputeOrchestrator(config, compute_backend="nosana-rest")

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
                        "curl",
                        "-s",
                        "-X",
                        "POST",
                        "http://localhost:8000/embed",
                        "-H",
                        "Content-Type: application/json",
                        "-d",
                        json.dumps({"texts": texts, "model": "all-mpnet-base-v2"}),
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

    spec = JobSpec(job_definition=job_def, timeout_seconds=120)
    print("Submitting embedding job to Nosana...")
    result = orchestrator.run(spec)
    print(f"Job {result.job_address} completed (state: {result.state.name})")

    # Parse the result from the job's ipfsResult or jobResult
    raw = result.result or {}
    ipfs_result = raw.get("ipfsResult")
    if ipfs_result:
        output = ipfs_result.get("output", "")
        lines = output.strip().split("\n")
        for line in lines:
            try:
                parsed = json.loads(line)
                if "embeddings" in parsed:
                    return parsed["embeddings"]
            except json.JSONDecodeError:
                continue

    raise RuntimeError("Could not extract embeddings from Nosana job result.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demonstrate embedding similarity via Nosana compute"
    )
    parser.add_argument("--local", action="store_true", help="Use local inference container")
    parser.add_argument("--remote", action="store_true", help="Submit to Nosana")
    args = parser.parse_args()

    # Two transaction descriptions to compare
    texts = [
        "INBOUND 1000.00 USDC 2026-06-24 | Wire transfer from acme corp | REF: INV-2024-001",
        "OUTBOUND 1000.00 USDC 2026-06-24 | Payment to acme corp | REF: INV-2024-001",
    ]

    if args.local:
        print("Generating embeddings via local inference container...")
        embeddings = embed_local(texts)
    elif args.remote:
        embeddings = embed_remote(texts)
    else:
        print("Specify --local (local container) or --remote (Nosana job).")
        sys.exit(1)

    sim = cosine_similarity(embeddings[0], embeddings[1])

    print(f"\nText 1: {texts[0]}")
    print(f"Text 2: {texts[1]}")
    print(f"\nEmbedding dimensions: {len(embeddings[0])}")
    print(f"Cosine similarity:     {sim:.4f}")
    print(f"Distance (1 - sim):    {1 - sim:.4f}")
    print("\nNote: this is raw vector similarity only. Run-Fi's matching engine")
    print("combines this with amount tolerance, date proximity, counterparty")
    print("similarity, and rule-based filters — none of which are in this demo.")


if __name__ == "__main__":
    main()
