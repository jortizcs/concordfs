#!/bin/bash
# Compare stub agent vs SLM agent latencies WITH FUSE MOUNT
# This version uses ConcordFS FUSE layer instead of plain directories

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Concord Latency Comparison: Stub vs SLM (WITH FUSE)        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check if FUSE is available
if ! command -v /sbin/umount &> /dev/null; then
    echo "ERROR: umount not found. FUSE may not be available."
    exit 1
fi

# Setup directories
BACKEND_DIR="/tmp/concord-fuse-backend"
MOUNT_DIR="/tmp/concord-fuse-mount"
rm -rf "$BACKEND_DIR" "$MOUNT_DIR"
mkdir -p "$BACKEND_DIR" "$MOUNT_DIR"

echo "Backend directory: $BACKEND_DIR"
echo "Mount point: $MOUNT_DIR"
echo ""

# ==========================================
# Mount FUSE filesystem
# ==========================================

echo "Mounting ConcordFS via FUSE..."
python3 << 'PYTHON_EOF' &
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))

from concord.fusemount import mount_agent

backend = "/tmp/concord-fuse-backend"
mount = "/tmp/concord-fuse-mount"

try:
    mount_agent('demo', backend, mount, foreground=True)
except KeyboardInterrupt:
    pass
PYTHON_EOF

FUSE_PID=$!
echo "FUSE process started (PID: $FUSE_PID)"
sleep 3  # Give FUSE time to mount

# Verify mount
if [ ! -d "$MOUNT_DIR/inbox" ]; then
    echo "ERROR: FUSE mount failed - inbox directory not found"
    kill $FUSE_PID 2>/dev/null || true
    exit 1
fi

echo "✓ FUSE mounted successfully"
echo ""

# ==========================================
# Run 1: Stub Agent (No LLM) with FUSE
# ==========================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Experiment 1: STUB Agent (No LLM) with FUSE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create agent that uses FUSE mount
python3 << 'AGENT_EOF' > /tmp/concord-fuse-stub.log 2>&1 &
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))

from concord import Agent, Intent, Event
import time

class DemoAgent(Agent):
    def handle_intent(self, intent: Intent) -> None:
        t1 = time.time()
        print(f"  Intent {intent.id[:8]}: op={intent.op}")
        
        result_text = f"Processed {intent.op}"
        engine = "stub"
        tokens = 0
        
        self.emit_event(Event(
            id=intent.id,
            event="completed",
            t=time.time(),
            t1=t1,
            artifact=result_text,
            engine=engine,
            tokens=tokens,
        ))
        
        print(f"    -> Event emitted (t1={t1:.6f})")

agent = DemoAgent(name="demo", base_path="/tmp/concord-fuse-mount")
agent.run()
AGENT_EOF

STUB_PID=$!
echo "Started stub agent (PID: $STUB_PID)"
sleep 1

echo "Running 20 intents through FUSE mount..."

# Run orchestrator using FUSE mount
python3 orchestrator.py 20 2>&1 | sed 's|/tmp/concord|/tmp/concord-fuse-mount|g' | tee /tmp/concord-fuse-stub-results.txt

kill $STUB_PID 2>/dev/null || true
sleep 1

# Save results
STUB_P50=$(grep "t0→t2" /tmp/concord-fuse-stub-results.txt | grep -oE "p50=[0-9. ]+ms" | grep -oE "[0-9.]+")

echo ""
echo "✓ Stub agent complete (with FUSE)"
echo ""

# Cleanup for next run
rm -rf "$MOUNT_DIR/inbox/"*.json "$MOUNT_DIR/inbox/"*.done
rm -rf "$MOUNT_DIR/outbox/"*.jsonl

# ==========================================
# Run 2: SLM Agent with FUSE
# ==========================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Experiment 2: SLM Agent (Qwen2.5-Coder-3B) with FUSE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if model exists
MODEL_PATH="../../models/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
if [ ! -f "$MODEL_PATH" ]; then
    echo "⚠️  Model not found at $MODEL_PATH"
    echo "⚠️  Skipping SLM test"
    SLM_SKIPPED=1
else
    # Create SLM agent that uses FUSE mount
    python3 << 'SLM_AGENT_EOF' > /tmp/concord-fuse-slm.log 2>&1 &
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
agent = SLMAgent(name="demo", model_path=model_path, base_path="/tmp/concord-fuse-mount")
agent.run()
SLM_AGENT_EOF

    SLM_PID=$!
    echo "Started SLM agent (PID: $SLM_PID)"
    echo "Warming up model..."
    sleep 5

    echo "Running 20 intents through FUSE mount..."

    # Same orchestrator as above but for SLM
    python3 << 'ORCH_EOF' 2>&1 | tee /tmp/concord-fuse-slm-results.txt
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent / "python"))

from concord import PlanExecutor, Step
import time

executor = PlanExecutor(
    agent_name="demo",
    base_path="/tmp/concord-fuse-mount"
)

print("Warmup: 10 intents...")
for i in range(10):
    step = Step(op=f"warmup_{i}", args={})
    executor.execute_step(step)
    time.sleep(0.02)

print("\nMeasuring: 20 intents...")
times = []

for i in range(20):
    t0 = time.time()
    step = Step(op=f"task_{i}", args={})
    result = executor.execute_step(step)
    t2 = time.time()
    
    if result and 't1' in result:
        t1 = result['t1']
        times.append({
            't0_t1': (t1 - t0) * 1000,
            't1_t2': (t2 - t1) * 1000,
            't0_t2': (t2 - t0) * 1000
        })
    
    time.sleep(0.01)

def percentile(data, p):
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] + c * (sorted_data[f+1] - sorted_data[f])
    else:
        return sorted_data[f]

t0_t1 = [t['t0_t1'] for t in times]
t1_t2 = [t['t1_t2'] for t in times]
t0_t2 = [t['t0_t2'] for t in times]

print("\n" + "="*60)
print("RESULTS (with FUSE)")
print("="*60)
print(f"t0→t1 (substrate)    min={min(t0_t1):6.1f} ms  p50={percentile(t0_t1, 0.5):6.1f} ms  p95={percentile(t0_t1, 0.95):6.1f} ms  max={max(t0_t1):6.1f} ms")
print(f"t1→t2 (agent work)   min={min(t1_t2):6.1f} ms  p50={percentile(t1_t2, 0.5):6.1f} ms  p95={percentile(t1_t2, 0.95):6.1f} ms  max={max(t1_t2):6.1f} ms")
print(f"t0→t2 (end-to-end)   min={min(t0_t2):6.1f} ms  p50={percentile(t0_t2, 0.5):6.1f} ms  p95={percentile(t0_t2, 0.95):6.1f} ms  max={max(t0_t2):6.1f} ms")
print()
print(f"Total intents: {len(times)}")
throughput = len(times) / sum([t['t0_t2'] for t in times]) * 1000
print(f"Throughput: {throughput:.1f} intents/s")
print("="*60)
ORCH_EOF

    kill $SLM_PID 2>/dev/null || true
    SLM_P50=$(grep "t0→t2" /tmp/concord-fuse-slm-results.txt | grep -oE "p50=[0-9. ]+ms" | grep -oE "[0-9.]+")
    
    echo ""
    echo "✓ SLM agent complete (with FUSE)"
    echo ""
fi

# ==========================================
# Cleanup
# ==========================================

echo "Unmounting FUSE..."
/sbin/umount "$MOUNT_DIR" 2>/dev/null || true
kill $FUSE_PID 2>/dev/null || true
sleep 1
echo "✓ FUSE unmounted"
echo ""

# ==========================================
# Comparison
# ==========================================

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  COMPARISON RESULTS (WITH FUSE)                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Stub Agent (no LLM) with FUSE:"
grep "t0→t1\|t1→t2\|t0→t2\|Throughput" /tmp/concord-fuse-stub-results.txt | grep -v "^--"
echo ""

if [ -z "$SLM_SKIPPED" ]; then
    echo "SLM Agent (Qwen2.5-Coder-3B Q4_K_M) with FUSE:"
    grep "t0→t1\|t1→t2\|t0→t2\|Throughput" /tmp/concord-fuse-slm-results.txt | grep -v "^--"
    echo ""
    
    if [ ! -z "$STUB_P50" ] && [ ! -z "$SLM_P50" ]; then
        OVERHEAD=$(echo "$SLM_P50 - $STUB_P50" | bc)
        RATIO=$(echo "scale=2; $SLM_P50 / $STUB_P50" | bc)
        echo "═══════════════════════════════════════════════════════════════"
        echo "Model overhead: ${OVERHEAD} ms"
        echo "Slowdown factor: ${RATIO}x"
        echo "═══════════════════════════════════════════════════════════════"
    fi
else
    echo "⚠️  SLM test skipped (model not found)"
fi

echo ""
echo "💡 Key insight: Now measuring with FUSE virtual filesystem!"
echo "   Compare these results to the non-FUSE version to see FUSE overhead."
echo ""
echo "Logs saved to:"
echo "  Stub: /tmp/concord-fuse-stub-results.txt"
echo "  SLM:  /tmp/concord-fuse-slm-results.txt"
echo ""

# Cleanup
rm -rf "$BACKEND_DIR" "$MOUNT_DIR"

