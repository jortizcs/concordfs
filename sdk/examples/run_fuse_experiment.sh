#!/bin/bash
# Run latency experiment with FUSE mount
# Simpler version that reuses existing orchestrator

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Concord FUSE Latency Experiment                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

BACKEND_DIR="/tmp/concord-fuse-backend"
MOUNT_DIR="/tmp/concord-fuse-mount"

# Cleanup
echo "Cleaning up previous runs..."
/sbin/umount "$MOUNT_DIR" 2>/dev/null || true
rm -rf "$BACKEND_DIR" "$MOUNT_DIR"
mkdir -p "$BACKEND_DIR" "$MOUNT_DIR"

# Mount FUSE
echo "Mounting ConcordFS..."
python3 << 'MOUNT_EOF' &
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))
from concord.fusemount import mount_agent

try:
    mount_agent('demo', '/tmp/concord-fuse-backend', '/tmp/concord-fuse-mount', foreground=True)
except KeyboardInterrupt:
    pass
MOUNT_EOF

FUSE_PID=$!
echo "FUSE process: PID $FUSE_PID"
sleep 3

# Verify
if [ ! -d "$MOUNT_DIR/inbox" ]; then
    echo "ERROR: FUSE mount failed"
    kill $FUSE_PID 2>/dev/null || true
    exit 1
fi
echo "✓ FUSE mounted"
echo ""

# Start agent
echo "Starting agent..."
python3 << 'AGENT_EOF' > /tmp/fuse-agent.log 2>&1 &
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))
from concord import Agent, Intent, Event
import time

class DemoAgent(Agent):
    def handle_intent(self, intent: Intent) -> None:
        t1 = time.time()
        print(f"  Intent {intent.id[:8]}: op={intent.op}")
        
        self.emit_event(Event(
            id=intent.id,
            event="completed",
            t=time.time(),
            t1=t1,
            artifact=f"Processed {intent.op}",
            engine="stub-fuse",
            tokens=0,
        ))

agent = DemoAgent(name="demo", base_path="/tmp/concord-fuse-mount")
agent.run()
AGENT_EOF

AGENT_PID=$!
echo "Agent process: PID $AGENT_PID"
sleep 1
echo ""

# Run orchestrator
echo "Running measurement (20 intents)..."
python3 << 'ORCH_EOF' 2>&1 | tee /tmp/fuse-results.txt
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))

import json
import os
import time
import uuid
import statistics

class FUSEOrchestrator:
    def __init__(self, base_path: str = "/tmp/concord-fuse-mount"):
        self.base = Path(base_path) / "demo"
        self.inbox = self.base / "inbox"
        self.outbox = self.base / "outbox"
        self.events_log = self.outbox / "events.jsonl"
        
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)
        
    def write_intent(self, op: str = "test", args: dict = None):
        intent_id = str(uuid.uuid4())
        t0 = time.time()
        
        tmp_path = self.inbox / f".tmp-{intent_id}.json"
        final_path = self.inbox / f"{intent_id}.json"
        
        intent = {
            "id": intent_id,
            "op": op,
            "args": args or {},
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
                    time.sleep(0.001)
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
            
            time.sleep(0.001)
        
        raise TimeoutError(f"No event received within {timeout}s")
    
    def measure_single_intent(self):
        prev_size = self.events_log.stat().st_size if self.events_log.exists() else 0
        intent_id, t0 = self.write_intent()
        new_size, event = self.wait_for_event(prev_size)
        t2 = time.time()
        t1 = event.get("t1", t2)
        return (t1 - t0, t2 - t1, t2 - t0)
    
    def run_experiment(self, n: int = 20, warmup: int = 10):
        print("Concord FUSE Latency Experiment")
        print(f"Mount point: {self.base.parent}")
        print(f"Inbox: {self.inbox}")
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
                if (i + 1) % 10 == 0:
                    print(f"  {i + 1}/{n} intents processed")
            except TimeoutError:
                print(f"Timeout on intent {i + 1}")
                continue
        
        if not latencies:
            print("ERROR: No successful measurements")
            return
        
        print()
        print("=" * 60)
        print("RESULTS (WITH FUSE)")
        print("=" * 60)
        
        t0_t1 = [x[0] * 1000 for x in latencies]
        t1_t2 = [x[1] * 1000 for x in latencies]
        t0_t2 = [x[2] * 1000 for x in latencies]
        
        def print_stats(label: str, data: list):
            print(f"{label:30} min={min(data):7.3f} ms  "
                  f"p50={statistics.median(data):7.3f} ms  "
                  f"p95={statistics.quantiles(data, n=20)[18]:7.3f} ms  "
                  f"max={max(data):7.3f} ms")
        
        print_stats("t0→t1 (substrate+FUSE)", t0_t1)
        print_stats("t1→t2 (agent work)", t1_t2)
        print_stats("t0→t2 (end-to-end)", t0_t2)
        print()
        print(f"Total intents: {len(latencies)}")
        print(f"Throughput: {len(latencies) / sum(t0_t2) * 1000:.1f} intents/s")

orch = FUSEOrchestrator()
orch.run_experiment(n=20, warmup=10)
ORCH_EOF

echo ""

# Cleanup
echo "Cleaning up..."
kill $AGENT_PID 2>/dev/null || true
sleep 1

echo "Unmounting FUSE..."
/sbin/umount "$MOUNT_DIR" 2>/dev/null || true
kill $FUSE_PID 2>/dev/null || true
sleep 1

echo "✓ Complete"
echo ""
echo "Results saved to: /tmp/fuse-results.txt"
echo "Agent log: /tmp/fuse-agent.log"
echo ""

# Cleanup temp dirs
rm -rf "$BACKEND_DIR" "$MOUNT_DIR"

