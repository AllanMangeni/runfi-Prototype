# Nosana Decentralised Compute — Integration Prototype

This repository demonstrates a production-grade integration with the **Nosana
decentralised GPU network** for ML inference workloads. It is a focused,
standalone extract of the Nosana integration layer, showing how to submit
embedding and LLM inference jobs to Nosana GPU nodes, poll for results,
handle fallback, and serve models via a Dockerised inference container.

## Architecture

```
Your application
    |
    v
ComputeOrchestrator  -- selects backend --
    |                      |
    v                      v
NosanaRestBackend    NosanaOnchainBackend
(credits, live)      (NOS tokens, stubbed)
    |
    v
[Pinata IPFS pin] --> POST /api/jobs/list --> Nosana GPU node
    |
    v
poll GET /api/jobs/{address} until COMPLETED
    |
    v
IPFS result retrieved
```

## Repository structure

```
src/compute/
  base.py              # ComputeBackend interface, JobState, JobSpec, poller
  nosana_client.py     # Nosana REST API client (credits, API-key auth)
  nosana_onchain.py    # Nosana on-chain client (NOS tokens, stubbed)
  orchestrator.py      # Backend selector with fallback logic
inference/
  Dockerfile           # GPU container for Nosana nodes
  server.py            # FastAPI server (POST /embed, POST /resolve)
  entrypoint.sh        # Container entrypoint
  requirements.txt     # Inference dependencies
nosana/
  job.json             # Nosana deployment job template
example/
  run_embedding.py     # End-to-end example: submit + poll + retrieve
docs/
  nosana-integration.md # Full technical reference
```

## Quick start

### 1. Prerequisites

- Python 3.11+
- A [Nosana dashboard](https://deploy.nosana.com) account with API key
- A [Pinata](https://pinata.cloud) account with JWT for IPFS pinning
- Docker (to build and push the inference container)

### 2. Install client dependencies

```bash
pip install -r requirements.txt
```

### 3. Build and push the inference container

```bash
docker build -t your-registry/inference:0.1.0 ./inference
docker push your-registry/inference:0.1.0
```

### 4. Run the example

```bash
export NOSANA_API_KEY="nos_..."
export PINATA_JWT="..."
export NOSANA_MARKET_ADDRESS="..."  # optional
export WORKER_IMAGE="your-registry/inference:0.1.0"

python example/run_embedding.py
```

## Key design decisions

- **Polling over webhooks** — Nosana's REST API does not offer webhooks; the
  client polls `GET /api/jobs/{address}` every 2s until terminal (Rule Q-1:
  verified against source).
- **IPFS via Pinata** — Job definitions are pinned to IPFS before posting.
  This is a Nosana requirement, not a dashboard route.
- **API schema over docs** — docs.nosana.io diverges from the actual API in
  several places (see `docs/nosana-integration.md`). The client follows the
  published `@nosana/api@2.6.1` OpenAPI schema.
- **Dual compute model** — The `ComputeBackend` interface supports both the
  REST/credits path and the on-chain NOS token path, selectable per config.
- **Idempotency** — Batch operations use the `Idempotency-Key` header so
  retries do not produce duplicate jobs.

## Verified API routes

All routes verified against `@nosana/api@2.6.1` source:

| Operation | Method | Path |
|---|---|---|
| Post job | POST | `/api/jobs/list` |
| Get job | GET | `/api/jobs/{address}` |
| Extend job | POST | `/api/jobs/{address}/extend` |
| Stop job | POST | `/api/jobs/{address}/stop` |
| Batch post | POST | `/api/jobs/list/batch` |
| Credits balance | GET | `/api/credits/balance` |
| List markets | GET | `/api/markets/` |

## Licence

Apache 2.0
