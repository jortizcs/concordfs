#!/usr/bin/env python3
"""
Minimal Concord orchestrator for latency measurement

Measures three latencies:
- t0→t1: substrate cost (write intent → agent sees it)
- t1→t2: agent processing cost (including optional SLM)
- t0→t2: end-to-end latency

Uses atomic rename for intent publishing (Concord semantics).
"""

import json
import os
import time
import uuid
import statistics
from pathlib import Path


class Orchestrator:
    """Orchestrator that submits intents and measures latency"""
    
    def __init__(self, agent_name: str, base_path: str = "/tmp/concord"):
        self.agent_name = agent_name
        self.base = Path(base_path) / agent_name
        self.inbox = self.base / "inbox"
        self.outbox = self.base / "outbox"
        self.events_log = self.outbox / "events.jsonl"
        
        # Ensure directories exist
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)
        
    def write_intent(self, op: str = "test", args: dict = None) -> tuple[str, float]:
        """
        Write an intent with atomic rename semantics.
        
        Returns: (intent_id, t0)
        """
        intent_id = str(uuid.uuid4())
        t0 = time.time()
        
        # Write to temporary file first
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
        
        # Atomic publish via rename
        os.rename(tmp_path, final_path)
        
        return intent_id, t0
    
    def wait_for_event(self, prev_size: int, timeout: float = 5.0) -> tuple[int, dict]:
        """
        Wait for event log to grow, then read the new event.
        
        Returns: (new_size, event_dict)
        """
        start = time.time()
        
        while time.time() - start < timeout:
            try:
                if not self.events_log.exists():
                    time.sleep(0.001)
                    continue
                    
                size = self.events_log.stat().st_size
                if size > prev_size:
                    # Read new line
                    with open(self.events_log, "rb") as f:
                        f.seek(prev_size)
                        line = f.readline().decode().strip()
                    
                    if line:
                        return size, json.loads(line)
                        
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            
            time.sleep(0.001)
        
        raise TimeoutError(f"No event received within {timeout}s")
    
    def measure_single_intent(self) -> tuple[float, float, float]:
        """
        Submit one intent and measure latency.
        
        Returns: (t0_to_t1, t1_to_t2, t0_to_t2)
        """
        # Get current log size
        prev_size = self.events_log.stat().st_size if self.events_log.exists() else 0
        
        # Submit intent
        intent_id, t0 = self.write_intent()
        
        # Wait for event
        new_size, event = self.wait_for_event(prev_size)
        t2 = time.time()
        
        # Extract agent's t1 timestamp
        t1 = event.get("t1", t2)
        
        return (t1 - t0, t2 - t1, t2 - t0)
    
    def run_experiment(self, n: int = 100, warmup: int = 10):
        """Run latency measurement experiment"""
        print(f"Concord Latency Experiment")
        print(f"Agent: {self.agent_name}")
        print(f"Inbox: {self.inbox}")
        print(f"Events: {self.events_log}")
        print()
        
        # Warmup
        print(f"Warmup: {warmup} intents...")
        for _ in range(warmup):
            try:
                self.measure_single_intent()
            except TimeoutError:
                print("ERROR: Agent not responding. Is minimal_agent.py running?")
                return
        
        # Actual measurement
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
        
        # Analyze results
        print()
        print("=" * 60)
        print("RESULTS")
        print("=" * 60)
        
        t0_t1 = [x[0] * 1000 for x in latencies]  # Convert to ms
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
        print(f"Total intents: {len(latencies)}")
        print(f"Throughput: {len(latencies) / sum(t0_t2) * 1000:.1f} intents/s")


def main():
    import sys
    # Allow specifying number of intents from command line
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    orch = Orchestrator("demo")
    orch.run_experiment(n=n, warmup=10)


if __name__ == "__main__":
    main()

