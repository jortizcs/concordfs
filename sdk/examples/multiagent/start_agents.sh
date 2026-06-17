#!/bin/bash
# Start all agents for the multi-agent demo

set -e

echo "Starting Concord multi-agent demo..."
echo ""

# Clean up previous run
rm -rf /tmp/concord/{code,test,release,_orchestrator}
rm -rf /mnt/bus

# Start agents in background
echo "Starting agents..."

python3 -u code_agent.py > /tmp/concord/code_agent.log 2>&1 &
CODE_PID=$!
echo "  code agent (PID: $CODE_PID)"

python3 -u test_agent.py > /tmp/concord/test_agent.log 2>&1 &
TEST_PID=$!
echo "  test agent (PID: $TEST_PID)"

python3 -u release_agent.py > /tmp/concord/release_agent.log 2>&1 &
RELEASE_PID=$!
echo "  release agent (PID: $RELEASE_PID)"

# Give agents time to initialize
sleep 2

echo ""
echo "✓ All agents running"
echo ""
echo "Agent PIDs: $CODE_PID, $TEST_PID, $RELEASE_PID"
echo ""
echo "To run the demo:"
echo "  python3 demo_feature_flag.py"
echo ""
echo "To stop agents:"
echo "  kill $CODE_PID $TEST_PID $RELEASE_PID"
echo ""

