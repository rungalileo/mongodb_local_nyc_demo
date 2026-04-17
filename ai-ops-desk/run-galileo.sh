#!/usr/bin/env bash
# Run CRM Ops Desk demo with Galileo SDK instrumentation
# Sends traces to Galileo console via GalileoAsyncCallback
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Credentials ──────────────────────────────────────────────────
# MongoDB Atlas credentials
#   Required variables:
#     MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority"
source ~/.cr/.cr.mongo.crm-demo

# Galileo credentials
#   Required variables:
#     GALILEO_API_KEY="A1Cch..."
#     GALILEO_PROJECT="my-project"
#     GALILEO_LOG_STREAM="default"
#     GALILEO_CONSOLE_URL="https://console.galileo.ai"
source ~/.cr/.cr.galileo

# OpenAI (if not in .env)
#   Required variables:
#     OPENAI_API_KEY="sk-..."

# SSL — corporate proxy CA bundle (optional)
[[ -f ~/.corporate-certs/env.sh ]] && source ~/.corporate-certs/env.sh

# ── App .env (MongoDB, OpenAI) ──────────────────────────────────
if [[ -f .env ]]; then
    set -a; source .env; set +a
fi

# ── Run ──────────────────────────────────────────────────────────
echo "=== Galileo-instrumented CRM Ops Desk (LangGraph) ==="
echo "Project:    ${GALILEO_PROJECT:-not set}"
echo "Log Stream: ${GALILEO_LOG_STREAM:-default}"
echo "Console:    ${GALILEO_CONSOLE_URL:-not set}"
echo "=================================================="

# Activate venv if present
if [[ -f .venv/bin/activate ]]; then
    source .venv/bin/activate
fi

exec python main.py "$@"
