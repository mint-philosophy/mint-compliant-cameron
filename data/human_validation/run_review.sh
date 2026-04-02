#!/usr/bin/env bash
# Launch all review servers + ngrok tunnel.
# Usage: ./run_review.sh
# Stop with Ctrl+C (kills all background processes).

set -e
cd "$(dirname "$0")"

trap 'echo "Shutting down..."; kill 0; exit' INT TERM

echo "Starting review servers..."
python3 serve_review.py &
python3 serve_eval_review.py &
sleep 1
python3 serve_gateway.py &
sleep 1

echo ""
echo "Servers running:"
echo "  Case review:  http://localhost:8000"
echo "  Eval review:  http://localhost:8001"
echo "  Gateway:      http://localhost:8080"
echo ""

# Start ngrok if available
if command -v ngrok &>/dev/null; then
    echo "Starting ngrok tunnel on :8080..."
    ngrok http 8080
else
    echo "ngrok not found — run 'ngrok http 8080' separately for remote access."
    echo "Press Ctrl+C to stop all servers."
    wait
fi
