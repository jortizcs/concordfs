#!/bin/bash
# Compare stub agent vs SLM agent latencies

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Concord Latency Comparison: Stub vs SLM                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Cleanup
rm -rf /tmp/concord/demo
mkdir -p /tmp/concord/demo/{inbox,outbox,fs}

# ==========================================
# Run 1: Stub Agent (No LLM)
# ==========================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Experiment 1: STUB Agent (No LLM)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 minimal_agent.py > /tmp/concord/demo/agent.log 2>&1 &
STUB_PID=$!
echo "Started stub agent (PID: $STUB_PID)"
sleep 1

echo "Running 20 intents..."
python3 orchestrator.py 20 2>&1 | tee /tmp/concord/demo/stub_results.txt
kill $STUB_PID 2>/dev/null || true
sleep 1

# Save results
STUB_P50=$(grep "t0→t2" /tmp/concord/demo/stub_results.txt | grep -oE "p50=[0-9. ]+ms" | grep -oE "[0-9.]+")

echo ""
echo "✓ Stub agent complete"
echo ""

# Cleanup for next run
rm -rf /tmp/concord/demo/inbox/* /tmp/concord/demo/outbox/*

# ==========================================
# Run 2: SLM Agent
# ==========================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Experiment 2: SLM Agent (Qwen2.5-Coder-3B)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 agent_with_slm.py > /tmp/concord/demo/agent_slm.log 2>&1 &
SLM_PID=$!
echo "Started SLM agent (PID: $SLM_PID)"
echo "Warming up model (first inference is slower)..."
sleep 3

echo "Running 20 intents..."
python3 orchestrator.py 20 2>&1 | tee /tmp/concord/demo/slm_results.txt
kill $SLM_PID 2>/dev/null || true

# Save results
SLM_P50=$(grep "t0→t2" /tmp/concord/demo/slm_results.txt | grep -oE "p50=[0-9. ]+ms" | grep -oE "[0-9.]+")

echo ""
echo "✓ SLM agent complete"
echo ""

# ==========================================
# Comparison
# ==========================================

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  COMPARISON RESULTS                                          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Stub Agent (no LLM):"
grep "t0→t1\|t1→t2\|t0→t2\|Throughput" /tmp/concord/demo/stub_results.txt | grep -v "^--"
echo ""
echo "SLM Agent (Qwen2.5-Coder-3B Q4_K_M):"
grep "t0→t1\|t1→t2\|t0→t2\|Throughput" /tmp/concord/demo/slm_results.txt | grep -v "^--"
echo ""

# Calculate overhead
if [ ! -z "$STUB_P50" ] && [ ! -z "$SLM_P50" ]; then
    OVERHEAD=$(echo "$SLM_P50 - $STUB_P50" | bc)
    RATIO=$(echo "scale=2; $SLM_P50 / $STUB_P50" | bc)
    echo "═══════════════════════════════════════════════════════════════"
    echo "Model overhead: ${OVERHEAD} ms"
    echo "Slowdown factor: ${RATIO}x"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "💡 Key insight: Substrate latency (t0→t1) stays the same!"
    echo "   The model adds latency to t1→t2 (agent processing)"
    echo "   but filesystem coordination remains fast."
fi

echo ""
echo "Logs saved to:"
echo "  Stub: /tmp/concord/demo/stub_results.txt"
echo "  SLM:  /tmp/concord/demo/slm_results.txt"
echo ""

