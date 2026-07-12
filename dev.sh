#!/bin/bash
# Kill existing processes on dev ports
echo "Stopping existing processes..."
lsof -ti :3000 | xargs kill -9 2>/dev/null
lsof -ti :8000 | xargs kill -9 2>/dev/null
pkill -f "next dev" 2>/dev/null
pkill -f "uvicorn" 2>/dev/null
rm -f apps/web/.next/dev/lock
sleep 1

# Set local env overrides
export DATABASE_URL=postgresql+asyncpg://kps:kps@localhost:5432/knowledge_product_studio
export REDIS_URL=redis://localhost:6379/0
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SDK_DISABLED=true
# Source remaining vars from .env (skip lines with special chars that break xargs)
set -a
source <(grep -v '^#' .env | grep -v '^\s*$' | sed 's/ = /=/g' | sed 's/= "/=/g' | sed 's/"$//g')
set +a

echo "Starting API on :8000..."
cd apps/api
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000 &
API_PID=$!
cd ../..

echo "Starting Web on :3000..."
cd apps/web
npm run dev &
WEB_PID=$!
cd ../..

echo ""
echo "API PID: $API_PID  →  http://localhost:8000"
echo "Web PID: $WEB_PID  →  http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both."

trap "kill $API_PID $WEB_PID 2>/dev/null; exit" INT
wait
