# Inference Container

Docker image that runs on Nosana GPU nodes to produce text embeddings via
`sentence-transformers/all-mpnet-base-v2` and LLM resolution suggestions via
`Qwen/Qwen2.5-3B-Instruct`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/embed` | Generate embeddings for input texts |
| POST | `/resolve` | LLM resolution suggestion |
| GET | `/health` | Health check |
| GET | `/` | Service info |

## Build

```bash
docker build -t your-registry/inference:0.1.0 .
```

The build pre-downloads the `all-mpnet-base-v2` model (~420MB) so cold starts
on Nosana nodes are fast.

## How it works on Nosana

The entrypoint (`entrypoint.sh`) starts the FastAPI server in the background,
waits for `/health`, then runs the command passed by the Nosana job definition
(a `curl` call to `/embed`). The curl output goes to stdout, which Nosana
captures and uploads to IPFS.

```json
{
  "cmd": ["curl", "-s", "-X", "POST", "http://localhost:8000/embed",
          "-H", "Content-Type: application/json",
          "-d", "{\"texts\": [\"...\"], \"model\": \"all-mpnet-base-v2\"}"]
}
```

## Run locally

```bash
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

Test the embed endpoint:

```bash
curl -X POST http://localhost:8000/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Sample transaction text"]}'
```

## Model

- `sentence-transformers/all-mpnet-base-v2` — 768 dimensions
- Downloads from HuggingFace at build time
