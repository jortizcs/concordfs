#!/usr/bin/env python3
"""
Multi-Agent Orchestrator

Coordinates code → test → doc → release pipeline.
Measures:
- Time-to-green (end-to-end latency)
- Per-agent handoff latency
- Success rate
- Failure recovery

Uses filesystem coordination:
- Intents in inbox/
- Events in outbox/events.jsonl
- Artifacts in CAS bus (hash references)
"""

import sys
import json
import os
import time
import uuid
import statistics
from pathlib import Path
from typing import Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from concord.cas import get_cas_bus


class MultiAgentOrchestrator:
    """Coordinates multi-agent pipeline"""
    
    def __init__(self, base_path: str = "/tmp/concord"):
        self.base = Path(base_path)
        self.cas = get_cas_bus()
        
        # Agent directories
        self.agents = {
            "code": self.base / "code",
            "test": self.base / "test",
            "doc": self.base / "doc",
            "release": self.base / "release",
        }
        
        # Ensure all agent directories exist
        for agent_dir in self.agents.values():
            (agent_dir / "inbox").mkdir(parents=True, exist_ok=True)
            (agent_dir / "outbox").mkdir(parents=True, exist_ok=True)
    
    def write_intent(self, agent: str, op: str, args: dict) -> tuple[str, float]:
        """Write an intent to an agent's inbox"""
        agent_dir = self.agents[agent]
        inbox = agent_dir / "inbox"
        
        intent_id = str(uuid.uuid4())
        t0 = time.time()
        
        tmp_path = inbox / f".tmp-{intent_id}.json"
        final_path = inbox / f"{intent_id}.json"
        
        intent = {
            "id": intent_id,
            "op": op,
            "args": args,
            "t0": t0,
        }
        
        with open(tmp_path, "w") as f:
            json.dump(intent, f)
            f.flush()
            os.fsync(f.fileno())
        
        os.rename(tmp_path, final_path)
        
        return intent_id, t0
    
    def wait_for_event(self, agent: str, intent_id: str, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
        """Wait for an event from an agent"""
        agent_dir = self.agents[agent]
        events_log = agent_dir / "outbox" / "events.jsonl"
        
        start = time.time()
        last_size = 0
        
        while time.time() - start < timeout:
            try:
                if not events_log.exists():
                    time.sleep(0.001)
                    continue
                
                size = events_log.stat().st_size
                if size > last_size:
                    # Read all new events
                    with open(events_log, "r") as f:
                        f.seek(last_size)
                        for line in f:
                            event = json.loads(line.strip())
                            if event.get("id") == intent_id:
                                return event
                    
                    last_size = size
                    
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            
            time.sleep(0.001)
        
        return None
    
    def run_pipeline(self, function_name: str, function_desc: str) -> Dict[str, Any]:
        """
        Run the complete pipeline: code → test → doc → release
        
        Returns: metrics dict with latencies and results
        """
        t_start = time.time()
        metrics = {
            "success": False,
            "stages": {},
            "handoffs": {},
            "total_time": 0,
        }
        
        print(f"\n{'='*60}")
        print(f"Pipeline: Generate '{function_name}' function")
        print(f"{'='*60}\n")
        
        # Stage 1: Code Generation
        print("Stage 1: Code Generation")
        stage_start = time.time()
        intent_id, t0 = self.write_intent("code", "generate_function", {
            "name": function_name,
            "description": function_desc,
        })
        
        event = self.wait_for_event("code", intent_id, timeout=60.0)
        if not event or event["event"] != "code_generated":
            print(f"  ✗ Code generation failed")
            return metrics
        
        code_ref = event["artifact"]
        code_hash = self.cas.parse_ref(code_ref)
        stage_time = time.time() - stage_start
        
        metrics["stages"]["code"] = {
            "time": stage_time,
            "hash": code_hash,
        }
        
        print(f"  ✓ Code generated (hash: {code_hash[:8]}...) in {stage_time:.2f}s")
        
        # Stage 2: Testing
        print("\nStage 2: Testing")
        handoff_start = time.time()
        stage_start = time.time()
        intent_id, t0 = self.write_intent("test", "test_code", {
            "code_ref": code_ref,
        })
        
        event = self.wait_for_event("test", intent_id, timeout=30.0)
        if not event:
            print(f"  ✗ Testing timed out")
            return metrics
        
        test_passed = event["event"] == "tests_completed"
        test_result = json.loads(event["artifact"])
        stage_time = time.time() - stage_start
        handoff_time = stage_start - handoff_start
        
        metrics["stages"]["test"] = {
            "time": stage_time,
            "passed": test_passed,
            "result": test_result,
        }
        metrics["handoffs"]["code_to_test"] = handoff_time
        
        if test_passed:
            print(f"  ✓ Tests passed in {stage_time:.2f}s")
        else:
            print(f"  ✗ Tests failed: {test_result.get('error', 'Unknown')}")
            metrics["total_time"] = time.time() - t_start
            return metrics
        
        # Stage 3: Documentation
        print("\nStage 3: Documentation")
        handoff_start = time.time()
        stage_start = time.time()
        intent_id, t0 = self.write_intent("doc", "generate_docs", {
            "code_ref": code_ref,
        })
        
        event = self.wait_for_event("doc", intent_id, timeout=60.0)
        if not event or event["event"] != "docs_generated":
            print(f"  ✗ Documentation generation failed")
            return metrics
        
        docs_ref = event["artifact"]
        docs_hash = self.cas.parse_ref(docs_ref)
        stage_time = time.time() - stage_start
        handoff_time = stage_start - handoff_start
        
        metrics["stages"]["doc"] = {
            "time": stage_time,
            "hash": docs_hash,
        }
        metrics["handoffs"]["test_to_doc"] = handoff_time
        
        print(f"  ✓ Docs generated (hash: {docs_hash[:8]}...) in {stage_time:.2f}s")
        
        # Stage 4: Release
        print("\nStage 4: Release")
        handoff_start = time.time()
        stage_start = time.time()
        intent_id, t0 = self.write_intent("release", "release", {
            "code_ref": code_ref,
            "docs_ref": docs_ref,
            "test_result": test_result,  # Pass test results dict
        })
        
        event = self.wait_for_event("release", intent_id, timeout=30.0)
        if not event:
            print(f"  ✗ Release timed out")
            return metrics
        
        released = event["event"] == "released"
        stage_time = time.time() - stage_start
        handoff_time = stage_start - handoff_start
        
        metrics["stages"]["release"] = {
            "time": stage_time,
            "released": released,
        }
        metrics["handoffs"]["doc_to_release"] = handoff_time
        
        if released:
            manifest_ref = event["artifact"]
            manifest_hash = self.cas.parse_ref(manifest_ref)
            metrics["stages"]["release"]["manifest"] = manifest_hash
            print(f"  ✓ Released (manifest: {manifest_hash[:8]}...) in {stage_time:.2f}s")
        else:
            reason = event.get("artifact", "Unknown reason")
            print(f"  ✗ Release blocked: {reason}")
            metrics["total_time"] = time.time() - t_start
            return metrics
        
        # Success!
        metrics["success"] = True
        metrics["total_time"] = time.time() - t_start
        
        print(f"\n{'='*60}")
        print(f"✓ Pipeline complete in {metrics['total_time']:.2f}s")
        print(f"{'='*60}")
        
        return metrics
    
    def print_summary(self, runs: list):
        """Print summary statistics"""
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}\n")
        
        successful = [r for r in runs if r["success"]]
        failed = [r for r in runs if not r["success"]]
        
        print(f"Total runs: {len(runs)}")
        print(f"Successful: {len(successful)} ({len(successful)/len(runs)*100:.1f}%)")
        print(f"Failed: {len(failed)} ({len(failed)/len(runs)*100:.1f}%)")
        
        if successful:
            times = [r["total_time"] for r in successful]
            print(f"\nTime-to-green:")
            print(f"  min: {min(times):.2f}s")
            print(f"  p50: {statistics.median(times):.2f}s")
            print(f"  p95: {statistics.quantiles(times, n=20)[18]:.2f}s" if len(times) >= 20 else f"  p95: N/A")
            print(f"  max: {max(times):.2f}s")
            
            # Stage times
            print(f"\nStage latencies (median):")
            for stage in ["code", "test", "doc", "release"]:
                stage_times = [r["stages"][stage]["time"] for r in successful if stage in r["stages"]]
                if stage_times:
                    print(f"  {stage:8s}: {statistics.median(stage_times):.2f}s")
            
            # Handoff times
            print(f"\nHandoff latencies (median):")
            for handoff in ["code_to_test", "test_to_doc", "doc_to_release"]:
                handoff_times = [r["handoffs"][handoff] for r in successful if handoff in r["handoffs"]]
                if handoff_times:
                    print(f"  {handoff:15s}: {statistics.median(handoff_times)*1000:.1f}ms")


def main():
    if len(sys.argv) < 2:
        print("Usage: python multiagent_orchestrator.py <num_runs>")
        sys.exit(1)
    
    num_runs = int(sys.argv[1])
    
    orch = MultiAgentOrchestrator()
    
    # Test cases
    test_cases = [
        ("fibonacci", "calculates the nth Fibonacci number recursively"),
        ("factorial", "calculates the factorial of n"),
        ("is_prime", "checks if a number is prime"),
        ("reverse_string", "reverses a string"),
        ("sum_list", "sums all elements in a list"),
    ]
    
    runs = []
    
    for i in range(num_runs):
        case = test_cases[i % len(test_cases)]
        metrics = orch.run_pipeline(case[0], case[1])
        runs.append(metrics)
        
        # Small delay between runs
        time.sleep(0.5)
    
    orch.print_summary(runs)


if __name__ == "__main__":
    main()

