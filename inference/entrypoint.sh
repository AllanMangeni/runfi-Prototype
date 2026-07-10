#!/bin/sh
# Inference container entrypoint.
# Starts the FastAPI server in the background, waits for it to be healthy,
# then runs the command passed as arguments. After the command completes,
# the server is stopped and the container exits.

set -e

uvicorn server:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!

echo "Waiting for inference server to be ready..."
i=0
while ! curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    i=$((i + 1))
    if [ $i -gt 120 ]; then
        echo "Server failed to start within 120 seconds" >&2
        kill $SERVER_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

echo "Server is ready."

# Run the command passed as arguments (e.g. curl -s -X POST ...)
"$@"
EXIT_CODE=$?

kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

exit $EXIT_CODE
