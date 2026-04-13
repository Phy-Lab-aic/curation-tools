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
DATASET_ROOT="${CURATION_DATASET_PATH:-/tmp/hf-mounts/Phy-lab/dataset}"
mkdir -p "$DATASET_ROOT"
export CURATION_DATASET_PATH="$DATASET_ROOT"

echo "Starting LeRobot Curation Tools..."
echo "  Dataset:  $DATASET_ROOT"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo "  Rerun:    http://localhost:9090"
echo ""

# Start backend
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
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
