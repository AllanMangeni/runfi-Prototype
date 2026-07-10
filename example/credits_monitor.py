#!/usr/bin/env python3
"""Monitor: check remaining Nosana dashboard credits.

Simple utility that calls GET /api/credits/balance and displays
assigned, reserved, and settled credits.

Usage:
    export NOSANA_API_KEY="nos_..."

    # One-shot check
    python example/credits_monitor.py

    # Continuous monitoring (poll every 60 seconds)
    python example/credits_monitor.py --watch --interval 60
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time

from src.compute.nosana_client import NosanaConfig, NosanaRestBackend


async def check_balance(config: NosanaConfig) -> None:
    backend = NosanaRestBackend(config)
    try:
        balance = await backend.get_credits_balance()
        assigned = balance.get("assignedCredits", "N/A")
        reserved = balance.get("reservedCredits", "N/A")
        settled = balance.get("settledCredits", "N/A")
        available = assigned - reserved if isinstance(assigned, (int, float)) and isinstance(reserved, (int, float)) else "N/A"

        print(f"  Assigned:  ${assigned}")
        print(f"  Reserved:  ${reserved}")
        print(f"  Settled:   ${settled}")
        print(f"  Available: ${available}")
    finally:
        await backend.close()


async def monitor(config: NosanaConfig, interval: int) -> None:
    print("Monitoring Nosana credits balance (Ctrl+C to stop)")
    print(f"  Polling every {interval}s")
    print("-" * 40)
    while True:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}]")
        await check_balance(config)
        print("-" * 40)
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Nosana credits balance")
    parser.add_argument("--watch", action="store_true", help="Continuously monitor")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    args = parser.parse_args()

    api_key = os.environ.get("NOSANA_API_KEY")
    if not api_key:
        print("Error: NOSANA_API_KEY environment variable is required.")
        print("  export NOSANA_API_KEY=\"nos_...\"")
        return

    config = NosanaConfig(api_key=api_key, ipfs_jwt="")

    if args.watch:
        asyncio.run(monitor(config, args.interval))
    else:
        print("Credits balance:")
        asyncio.run(check_balance(config))


if __name__ == "__main__":
    main()
