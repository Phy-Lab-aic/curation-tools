#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Set up Python virtual environment if missing
if [ ! -d ".venv" ]; then
    echo "Setting up Python environment..."
    if ! command -v uv &>/dev/null; then
        echo "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    fi
    uv venv .venv
    source .venv/bin/activate
    uv pip install -e .
    echo "Python environment ready."
else
    source .venv/bin/activate
fi

# Install frontend dependencies if missing
if [ ! -d "frontend/node_modules" ]; then
    echo "Installing frontend dependencies..."
    (cd frontend && npm install)
    echo "Frontend dependencies ready."
fi

# Ensure dataset mount point exists
DATASET_ROOT="${CURATION_DATASET_PATH:-/mnt/synology/data/data_div/2026_1/lerobot}"
export CURATION_DATASET_PATH="$DATASET_ROOT"

# Ports (override via env to run multiple instances)
BACKEND_PORT="${BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export VITE_PORT="$FRONTEND_PORT"
export VITE_BACKEND_URL="${VITE_BACKEND_URL:-http://localhost:${BACKEND_PORT}}"

echo "Starting robodata-studio..."
echo "  Dataset:  $DATASET_ROOT"
echo "  Backend:  http://localhost:${BACKEND_PORT}"
echo "  Frontend: http://localhost:${FRONTEND_PORT}"
echo ""

# Start backend
uvicorn backend.main:app --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!

# Start frontend dev server
cd frontend && npm run dev &
FRONTEND_PID=$!
cd ..

# Trap to clean up on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    wait
}
trap cleanup EXIT INT TERM

echo "All services started. Press Ctrl+C to stop."
wait
