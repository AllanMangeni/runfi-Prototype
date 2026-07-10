# Nosana Integration

This document covers how the prototype integrates with Nosana for decentralised
GPU compute workloads. All routes and facts below were verified against the
published `@nosana/api@2.6.1` npm package source (the generated OpenAPI schema
and route modules) in June 2026. The Nosana TypeScript SDK is the reference;
this client uses the REST HTTP API directly from Python.

## Two compute models

Two Nosana integration paths are supported behind one `ComputeBackend` interface.

| | REST (credits) | On-chain (NOS tokens) |
|---|---|---|
| Auth | API key (`nos_xxx`) | Solana wallet |
| Payment | Dashboard credits | NOS tokens per second |
| Python-native | Yes | No (needs Solana signing lib) |
| Status | Built (`src/compute/nosana_client.py`) | Stubbed, deferred (`src/compute/nosana_onchain.py`) |

The REST path is the default (`compute_backend: "nosana-rest"`).

## REST API base URL and auth

- Base URL: `https://dashboard.k8s.prd.nos.ci`
- Auth header: `Authorization: Bearer nos_xxx` (your API key from https://deploy.nosana.com)
- Idempotency: `Idempotency-Key` header (optional for single operations, required for batch)

## IPFS pinning

Job definitions are pinned to IPFS via Pinata before posting.

- Pinata endpoint: `POST https://api.pinata.cloud/pinning/pinJSONToIPFS`
- Pinata auth: `Authorization: Bearer <jwt>` (your Pinata JWT)

## Verified routes

All relative to the base URL.

| Operation | Method | Path | Body |
|---|---|---|---|
| Post a job | POST | `/api/jobs/list` | `{ ipfsHash, market, timeout?, node? }` |
| Get job | GET | `/api/jobs/{address}` | none |
| Extend job | POST | `/api/jobs/{address}/extend` | `{ seconds }` |
| Stop job | POST | `/api/jobs/{address}/stop` | none |
| Batch post | POST | `/api/jobs/list/batch` | `{ jobs: [...] }` (Idempotency-Key required) |
| Credits balance | GET | `/api/credits/balance` | none |
| List markets | GET | `/api/markets/` | none (trailing slash) |

Source: `@nosana/api@2.6.1` route modules and `schema.d.ts`. The docs at
docs.nosana.io show TypeScript SDK calls, not raw HTTP routes. The Swagger UI
at `/api/swagger` returns 404. Routes were extracted from the published npm
package.

## Job states

The GET job response includes a `state` integer field:

| Value | State | Terminal |
|---|---|---|
| 0 | QUEUED | No |
| 1 | RUNNING | No |
| 2 | COMPLETED | Yes |
| 3 | STOPPED | Yes |

Failure is signalled by the string `jobStatus` field on the job object.

## Polling, not webhooks

Nosana offers no webhook for job completion. The client polls
`GET /api/jobs/{address}` until the job reaches a terminal state (COMPLETED or
STOPPED). The poller (`src/compute/base.py`, `poll_until_completed`) uses a
configurable interval (default 2 seconds) and max wait (default 30 seconds).

## Docs vs schema discrepancies

The docs.nosana.io markdown diverges from the actual API in several places.
The client follows the schema, not the docs:

| Topic | Docs say | Actual API |
|---|---|---|
| Extend body | `{ timeout: 120 }` (minutes) | `{ seconds }` (seconds) |
| Get-job field | `job.job_definition` | `jobDefinition` (camelCase) |
| IPFS method | `client.ipfs.add(...)` | `client.ipfs.pin(...)` (Pinata) |
| Credits method | `client.api.credits.get()` | `client.api.credits.balance()` |

## Configuration

| Variable | Purpose | Required for |
|---|---|---|
| `api_key` | Nosana dashboard API key | nosana-rest |
| `ipfs_jwt` | Pinata JWT for IPFS pinning | nosana-rest |
| `base_url` | API base URL (default: `https://dashboard.k8s.prd.nos.ci`) | nosana-rest (optional) |
| `market_address` | GPU market address | Both |

## Job definition

The job definition JSON follows the Nosana schema (`version: "0.1"`,
`type: "container"`, `ops[]`). The `nosana/job.json` file is a deployment job
spec template used by the pipeline orchestrator.

## Compute architecture

```
Client code
    |
    v
ComputeOrchestrator  -- selects backend per config --
    |                      |
    v                      v
NosanaRestBackend    NosanaOnchainBackend
(credits, live)      (NOS tokens, stubbed)
    |
    v
Nosana GPU node  -- runs container, serves POST /embed
    |
    v
IPFS result
```
