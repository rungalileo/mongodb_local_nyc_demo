#!/usr/bin/env bash
# Run CRM demo app with SDOT (Splunk Distribution of OpenTelemetry) instrumentation
# Sends traces to local OTel Collector via gRPC
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Credentials ──────────────────────────────────────────────────
# MongoDB Atlas credentials
source ~/.cr/.cr.mongo.crm-demo

# SSL — corporate proxy CA bundle
source ~/.corporate-certs/env.sh

# ── OTel / SDOT configuration ───────────────────────────────────
export OTEL_SERVICE_NAME="crm-app"
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
export OTEL_EXPORTER_OTLP_PROTOCOL="grpc"
export OTEL_EXPORTER_OTLP_METRICS_PROTOCOL="grpc"
export OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE="DELTA"
export OTEL_LOGS_EXPORTER="otlp"
export OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED="true"
export OTEL_RESOURCE_ATTRIBUTES="deployment.environment=galileo-crm-demo"
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="true"
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT_MODE="SPAN_AND_EVENT"
export OTEL_INSTRUMENTATION_GENAI_EMITTERS="span_metric_event,splunk"

# ── App .env (MongoDB, OpenAI) ──────────────────────────────────
set -a
source .env
set +a

# ── Run ──────────────────────────────────────────────────────────
echo "=== SDOT-instrumented CRM Demo ==="
echo "Service:    $OTEL_SERVICE_NAME"
echo "Collector:  $OTEL_EXPORTER_OTLP_ENDPOINT"
echo "==================================="

# Activate venv
source .venv/bin/activate

# Run with opentelemetry-instrument to auto-discover SDOT instrumentors
# (langchain, openai-v2, etc.) via their entry points
exec opentelemetry-instrument python main.py "$@"
