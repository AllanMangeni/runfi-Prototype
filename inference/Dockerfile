# Inference Container for Nosana GPU Nodes
# Builds the Docker image that runs on Nosana GPU nodes.
# Exposes POST /embed and POST /resolve via a FastAPI server.
#
# Build:
#   docker build -t your-registry/inference:0.1.0 ./inference
# Push:
#   docker push your-registry/inference:0.1.0
# Then reference the image in your Nosana job definition.

FROM docker.io/pytorch/pytorch:2.2.1-cuda12.1-cudnn8-runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --quiet -r requirements.txt

# Pre-download the model at build time so cold starts are fast.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-mpnet-base-v2')"

COPY server.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000

RUN useradd --create-home --shell /bin/bash appuser
USER appuser

# Entrypoint starts server, waits for health, then runs the Nosana cmd.
ENTRYPOINT ["./entrypoint.sh"]
