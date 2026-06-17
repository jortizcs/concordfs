#!/bin/bash
# Run the minimal Concord latency experiment

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Concord v0.1.0 - Minimal Latency Experiment                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Cleanup previous run
echo "Cleaning up previous run..."
rm -rf /tmp/concord/demo
mkdir -p /tmp/concord/demo/{inbox,outbox,fs}

echo ""
echo "Starting agent in background..."
python3 minimal_agent.py > /tmp/concord/demo/agent.log 2>&1 &
AGENT_PID=$!
echo "  Agent PID: $AGENT_PID"

# Give agent time to start
sleep 1

echo ""
echo "Running orchestrator (200 intents)..."
echo ""
python3 orchestrator.py

echo ""
echo "Stopping agent..."
kill $AGENT_PID 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "Experiment complete!"
echo ""
echo "Filesystem state preserved at: /tmp/concord/demo/"
echo "  inbox/      - Processed intents (*.done tombstones)"
echo "  outbox/     - Event log (events.jsonl)"
echo "  agent.log   - Agent output"
echo ""
echo "View event log:"
echo "  cat /tmp/concord/demo/outbox/events.jsonl | jq"
echo ""

