#!/bin/bash
# Compare polling vs file notifications (fsevents/inotify)
# Measures substrate latency improvement

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Polling vs Notifications Latency Comparison                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Test with plain directories (to isolate notification overhead)
PLAIN_BASE="/tmp/concord-notifications-test"

rm -rf "$PLAIN_BASE"
mkdir -p "$PLAIN_BASE"

echo "═══════════════════════════════════════════════════════════════"
echo "Test 1: Notification-based Agent (fsevents/inotify)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Start notification-based agent
python3 << 'AGENT_EOF' > /tmp/notification-agent.log 2>&1 &
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))
from concord import Agent, Intent, Event
import time

class StubAgent(Agent):
    """Minimal agent to isolate substrate overhead"""
    
    def handle_intent(self, intent: Intent) -> None:
        t1 = time.time()
        # Minimal processing
        self.emit_event(Event(
            id=intent.id,
            event="completed",
            t=time.time(),
            t1=t1,
        ))

agent = StubAgent(name="test", base_path="/tmp/concord-notifications-test")
agent.run()
AGENT_EOF

AGENT_PID=$!
echo "Agent PID: $AGENT_PID (notification-based)"
sleep 2

# Run orchestrator
echo "Running measurement (20 intents)..."
python3 << 'ORCH_EOF' 2>&1 | tee /tmp/notification-results.txt
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))

import json
import os
import time
import uuid
import statistics

class Orchestrator:
    def __init__(self, base_path: str = "/tmp/concord-notifications-test"):
        self.base = Path(base_path) / "test"
        self.inbox = self.base / "inbox"
        self.outbox = self.base / "outbox"
        self.events_log = self.outbox / "events.jsonl"
        
    def write_intent(self, op: str = "test"):
        intent_id = str(uuid.uuid4())
        t0 = time.time()
        
        tmp_path = self.inbox / f".tmp-{intent_id}.json"
        final_path = self.inbox / f"{intent_id}.json"
        
        intent = {
            "id": intent_id,
            "op": op,
            "args": {},
            "t0": t0,
        }
        
        with open(tmp_path, "w") as f:
            json.dump(intent, f)
            f.flush()
            os.fsync(f.fileno())
        
        os.rename(tmp_path, final_path)
        return intent_id, t0
    
    def wait_for_event(self, prev_size: int, timeout: float = 5.0):
        start = time.time()
        
        while time.time() - start < timeout:
            try:
                if not self.events_log.exists():
                    time.sleep(0.0001)
                    continue
                    
                size = self.events_log.stat().st_size
                if size > prev_size:
                    with open(self.events_log, "rb") as f:
                        f.seek(prev_size)
                        line = f.readline().decode().strip()
                    
                    if line:
                        return size, json.loads(line)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            
            time.sleep(0.0001)
        
        raise TimeoutError(f"No event within {timeout}s")
    
    def measure_single_intent(self):
        prev_size = self.events_log.stat().st_size if self.events_log.exists() else 0
        intent_id, t0 = self.write_intent()
        new_size, event = self.wait_for_event(prev_size)
        t2 = time.time()
        t1 = event.get("t1", t2)
        return (t1 - t0, t2 - t1, t2 - t0)
    
    def run_experiment(self, n: int = 20, warmup: int = 5):
        print("Notification-based Agent Latency Test")
        print(f"Base: {self.base}")
        print()
        
        print(f"Warmup: {warmup} intents...")
        for _ in range(warmup):
            try:
                self.measure_single_intent()
            except TimeoutError:
                print("ERROR: Agent not responding")
                return
        
        print(f"Measuring: {n} intents...")
        latencies = []
        
        for i in range(n):
            try:
                lat = self.measure_single_intent()
                latencies.append(lat)
            except TimeoutError:
                print(f"Timeout on intent {i + 1}")
                continue
        
        if not latencies:
            print("ERROR: No measurements")
            return
        
        print()
        print("=" * 60)
        print("RESULTS (Notification-based)")
        print("=" * 60)
        
        t0_t1 = [x[0] * 1000 for x in latencies]
        t1_t2 = [x[1] * 1000 for x in latencies]
        t0_t2 = [x[2] * 1000 for x in latencies]
        
        def print_stats(label: str, data: list):
            print(f"{label:30} min={min(data):7.3f} ms  "
                  f"p50={statistics.median(data):7.3f} ms  "
                  f"p95={statistics.quantiles(data, n=20)[18]:7.3f} ms  "
                  f"max={max(data):7.3f} ms")
        
        print_stats("t0→t1 (substrate)", t0_t1)
        print_stats("t1→t2 (agent work)", t1_t2)
        print_stats("t0→t2 (end-to-end)", t0_t2)
        print()
        print(f"Intents: {len(latencies)}")
        print(f"Throughput: {len(latencies) / sum(t0_t2) * 1000:.1f} intents/s")

orch = Orchestrator()
orch.run_experiment(n=20, warmup=5)
ORCH_EOF

echo ""
echo "Stopping agent..."
kill $AGENT_PID 2>/dev/null || true
wait $AGENT_PID 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "Comparison Summary"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Previous results (with 10ms polling):"
echo "  t0→t1 (substrate): ~11.1 ms p50"
echo ""
echo "New results (with fsevents/inotify):"
cat /tmp/notification-results.txt | grep "t0→t1"
echo ""
echo "Expected improvement: 5-10ms reduction in substrate latency"
echo "The difference isolates the polling overhead removed by notifications"
echo ""
echo "Results saved to: /tmp/notification-results.txt"
echo "Agent log: /tmp/notification-agent.log"

# Cleanup
rm -rf "$PLAIN_BASE"


