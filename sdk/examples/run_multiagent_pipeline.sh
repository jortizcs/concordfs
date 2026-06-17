#!/bin/bash
# Run the complete multi-agent pipeline
# Measures time-to-green, handoff latency, and success rate

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Multi-Agent Pipeline: Code → Test → Doc → Release          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Cleanup
BASE_PATH="/tmp/concord"
rm -rf "$BASE_PATH"/{code,test,doc,release}
rm -rf /tmp/bus

# Create directories
for agent in code test doc release; do
    mkdir -p "$BASE_PATH/$agent"/{inbox,outbox}
done

# Check for model
MODEL_PATH="../../models/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
if [ ! -f "$MODEL_PATH" ]; then
    echo "❌ Model not found at $MODEL_PATH"
    exit 1
fi

echo "Starting agents..."
echo ""

# Start Code Agent (SLM)
echo "  • Code Agent (SLM)"
python3 multiagent_pipeline.py code > /tmp/code_agent.log 2>&1 &
CODE_PID=$!

# Start Test Agent
echo "  • Test Agent"
python3 multiagent_pipeline.py test > /tmp/test_agent.log 2>&1 &
TEST_PID=$!

# Start Doc Agent (SLM)
echo "  • Doc Agent (SLM)"
python3 multiagent_pipeline.py doc > /tmp/doc_agent.log 2>&1 &
DOC_PID=$!

# Start Release Agent (Policy)
echo "  • Release Agent (Policy-Gated)"
python3 multiagent_pipeline.py release > /tmp/release_agent.log 2>&1 &
RELEASE_PID=$!

echo ""
echo "Agent PIDs: code=$CODE_PID test=$TEST_PID doc=$DOC_PID release=$RELEASE_PID"
echo ""
echo "Waiting for agents to initialize..."
sleep 3

# Run orchestrator
NUM_RUNS=${1:-5}
echo "Running $NUM_RUNS pipeline executions..."
echo ""

python3 multiagent_orchestrator.py $NUM_RUNS 2>&1 | tee /tmp/multiagent_results.txt

echo ""
echo "Cleaning up..."

# Kill agents
kill $CODE_PID $TEST_PID $DOC_PID $RELEASE_PID 2>/dev/null || true
wait 2>/dev/null || true

echo ""
echo "✓ Complete"
echo ""
echo "Results saved to: /tmp/multiagent_results.txt"
echo "Agent logs:"
echo "  Code:    /tmp/code_agent.log"
echo "  Test:    /tmp/test_agent.log"
echo "  Doc:     /tmp/doc_agent.log"
echo "  Release: /tmp/release_agent.log"

