#!/bin/bash
# Run SLM latency experiment with FUSE mount
# Completes the 2x2 matrix: (Plain/FUSE) x (Stub/SLM)

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Concord FUSE + SLM Latency Experiment                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

BACKEND_DIR="/tmp/concord-fuse-backend-slm"
MOUNT_DIR="/tmp/concord-fuse-mount-slm"
MODEL_PATH="../../models/qwen2.5-coder-3b-instruct-q4_k_m.gguf"

# Check model
if [ ! -f "$MODEL_PATH" ]; then
    echo "❌ Model not found at $MODEL_PATH"
    echo "Please download Qwen2.5-Coder-3B-Instruct Q4_K_M"
    exit 1
fi

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
    mount_agent('demo', '/tmp/concord-fuse-backend-slm', '/tmp/concord-fuse-mount-slm', foreground=True)
except KeyboardInterrupt:
    pass
MOUNT_EOF

FUSE_PID=$!
echo "FUSE process: PID $FUSE_PID"
sleep 3

# Verify
if [ ! -d "$MOUNT_DIR/inbox" ]; then
    echo "❌ FUSE mount failed - inbox not found"
    kill $FUSE_PID 2>/dev/null || true
    exit 1
fi
echo "✓ FUSE mounted"
echo ""

# Start SLM agent
echo "Starting SLM agent (Qwen2.5-Coder-3B)..."
echo "This will take a moment to load the model..."
python3 << 'AGENT_EOF' > /tmp/fuse-slm-agent.log 2>&1 &
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))
from concord import Agent, Intent, Event
import time
import subprocess
import json

class SLMAgent(Agent):
    def __init__(self, name: str, model_path: str, base_path: str = "/tmp/concord"):
        super().__init__(name, base_path)
        self.model_path = model_path
        self.llama_bin = "/opt/homebrew/bin/llama-cli"
        
        print(f"SLM Agent initialized with FUSE")
        print(f"  Model: {Path(model_path).name}")
        print(f"  Base: {base_path}")
    
    def call_llm(self, prompt: str, max_tokens: int = 64) -> dict:
        t_start = time.time()
        try:
            result = subprocess.run([
                self.llama_bin,
                "-m", self.model_path,
                "-p", prompt,
                "-n", str(max_tokens),
                "--temp", "0.7",
                "--no-warmup",
                "--no-cnv",
                "--log-disable",
            ], capture_output=True, text=True, timeout=30)
            
            t_end = time.time()
            latency_ms = (t_end - t_start) * 1000
            output = result.stdout.strip()
            tokens_generated = len(output.split())
            
            return {
                "output": output[:200],
                "latency_ms": latency_ms,
                "tokens": tokens_generated,
                "engine": "qwen2.5-coder-3b",
                "success": result.returncode == 0,
            }
        except Exception as e:
            return {
                "output": f"ERROR: {str(e)}",
                "latency_ms": 0,
                "tokens": 0,
                "engine": "qwen2.5-coder-3b",
                "success": False,
            }
    
    def handle_intent(self, intent: Intent) -> None:
        t1 = time.time()
        print(f"  Intent {intent.id[:8]}: op={intent.op}")
        
        prompt = f"Task: {intent.op}\nResponse:"
        llm_result = self.call_llm(prompt, max_tokens=64)
        
        self.emit_event(Event(
            id=intent.id,
            event="completed",
            t=time.time(),
            t1=t1,
            artifact=llm_result["output"],
            engine=llm_result["engine"],
            tokens=llm_result["tokens"],
        ))
        
        print(f"    -> LLM: {llm_result['latency_ms']:.1f}ms, {llm_result['tokens']} tokens")

model_path = "../../models/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
# Note: Agent class adds agent name to path, but FUSE mount already includes it
# So we need to pass the parent of where we want the agent to operate
# FUSE creates: /mount/inbox/, /mount/outbox/, etc
# Agent expects: base_path/agent_name/inbox/, base_path/agent_name/outbox/
# Solution: Create a symlink or adjust the path
import os
os.makedirs("/tmp/concord-fuse-mount-slm-parent/demo", exist_ok=True)
os.system("rm -rf /tmp/concord-fuse-mount-slm-parent/demo")
os.symlink("/tmp/concord-fuse-mount-slm", "/tmp/concord-fuse-mount-slm-parent/demo")
agent = SLMAgent(name="demo", model_path=model_path, base_path="/tmp/concord-fuse-mount-slm-parent")
agent.run()
AGENT_EOF

AGENT_PID=$!
echo "Agent process: PID $AGENT_PID"
echo "Warming up model (first inference is slower)..."
sleep 5
echo ""

# Set up symlink for orchestrator too
mkdir -p /tmp/concord-fuse-mount-slm-parent
rm -rf /tmp/concord-fuse-mount-slm-parent/demo
ln -s /tmp/concord-fuse-mount-slm /tmp/concord-fuse-mount-slm-parent/demo

# Run orchestrator
echo "Running measurement (20 intents)..."
echo "This will take 2-3 minutes with the model..."
python3 << 'ORCH_EOF' 2>&1 | tee /tmp/fuse-slm-results.txt
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))

import json
import os
import time
import uuid
import statistics

class FUSEOrchestrator:
    def __init__(self, base_path: str = "/tmp/concord-fuse-mount-slm-parent/demo"):
        self.base = Path(base_path)
        self.inbox = self.base / "inbox"
        self.outbox = self.base / "outbox"
        self.events_log = self.outbox / "events.jsonl"
        
        # Don't create dirs - FUSE mount already has them
        # self.inbox.mkdir(parents=True, exist_ok=True)
        # self.outbox.mkdir(parents=True, exist_ok=True)
        
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
    
    def wait_for_event(self, prev_size: int, timeout: float = 30.0):
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
        print("Concord FUSE + SLM Latency Experiment")
        print(f"Model: Qwen2.5-Coder-3B-Instruct (Q4_K_M)")
        print(f"Mount: {self.base.parent}")
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
                if (i + 1) % 5 == 0:
                    print(f"  {i + 1}/{n} intents processed")
            except TimeoutError:
                print(f"Timeout on intent {i + 1}")
                continue
        
        if not latencies:
            print("ERROR: No successful measurements")
            return
        
        print()
        print("=" * 60)
        print("RESULTS (SLM + FUSE)")
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
        print_stats("t1→t2 (model inference)", t1_t2)
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
echo "Results saved to: /tmp/fuse-slm-results.txt"
echo "Agent log: /tmp/fuse-slm-agent.log"
echo ""

# Cleanup temp dirs
rm -rf "$BACKEND_DIR" "$MOUNT_DIR"

