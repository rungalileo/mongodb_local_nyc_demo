#!/usr/bin/env bash
# Start OTel Collector for CRM demo (dual fan-out: Splunk O11y + Galileo)
set -euo pipefail

# ── Credentials ──────────────────────────────────────────────────
source ~/.cr/.cr.splunk.playground
export SPLUNK_API_URL="https://api.${SPLUNK_REALM}.signalfx.com"
export SPLUNK_INGEST_URL="https://ingest.${SPLUNK_REALM}.signalfx.com"

source ~/.cr/.cr.galileo.splunk-cluster.crm
export GALILEO_LOG_STREAM="${GALILEO_LOG_STREAM:-crm-agent}"

# SSL
source ~/.corporate-certs/env.sh

# Collector defaults
export SPLUNK_LISTEN_INTERFACE="${SPLUNK_LISTEN_INTERFACE:-0.0.0.0}"
export SPLUNK_BUNDLE_DIR="${SPLUNK_BUNDLE_DIR:-/usr/lib/splunk-otel-collector/agent-bundle}"
export SPLUNK_COLLECTD_DIR="${SPLUNK_COLLECTD_DIR:-/usr/lib/splunk-otel-collector/agent-bundle/run/collectd}"

CONFIG="/Users/sesergee/etc/agent_config_splunk-galileo-crm.yaml"

echo "=== OTel Collector ==="
echo "Config:  $CONFIG"
echo "Galileo: $GALILEO_PROJECT / $GALILEO_LOG_STREAM"
echo "Splunk:  $SPLUNK_REALM"
echo "======================"

exec otelcol --config "$CONFIG"
