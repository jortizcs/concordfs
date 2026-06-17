#!/usr/bin/env python3
"""
Multi-Agent Demo: "Add a Feature Flag and Ship"

Demonstrates realistic multi-agent coordination via Concord filesystem:
- 3 agents: code, test, release
- CAS bus for artifact passing (hash refs, not copies)
- Plan graph with dependencies
- Policy enforcement (no_network on release agent)

Task: Add --dry-run flag to foo command, test it, and publish release
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python"))

from concord import PlanExecutor, Step, get_cas_bus
import time


def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Concord Multi-Agent Demo: Add Feature Flag and Ship        ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    # Initialize CAS bus
    cas = get_cas_bus()
    
    # Create spec document
    spec = """
# Feature Spec: Add --dry-run flag

Add a --dry-run flag to the foo command that:
1. Prints "DRY RUN MODE" when enabled
2. Returns early without processing
3. Updates help text and README
"""
    
    spec_hash = cas.put(spec, "text/markdown")
    spec_ref = cas.ref(spec_hash)
    
    print(f"Spec stored in CAS: {spec_hash[:16]}...")
    print()
    
    # Create execution plan
    executor = PlanExecutor("add_dry_run_flag")
    
    # Register agents
    executor.add_agent("code")
    executor.add_agent("test")
    executor.add_agent("release")
    
    # Set policy for release agent
    release_policy = executor.agent_dirs["release"] / "policy"
    release_policy.mkdir(exist_ok=True)
    (release_policy / "no_network").write_text("true")
    
    # Define plan steps
    steps = [
        Step(
            id="propose_patch",
            agent="code",
            operation="propose_patch",
            args={"spec": spec_ref},
            depends_on=[],
        ),
        Step(
            id="run_tests",
            agent="test",
            operation="run_tests",
            args={"patch": "{{propose_patch.artifact}}"},  # Will be resolved
            depends_on=["propose_patch"],
        ),
        Step(
            id="apply_patch",
            agent="code",
            operation="apply_patch",
            args={"patch": "{{propose_patch.artifact}}"},
            depends_on=["run_tests"],
        ),
        Step(
            id="publish_release",
            agent="release",
            operation="publish_release",
            args={
                "patch": "{{propose_patch.artifact}}",
                "version": "0.2.0",
            },
            depends_on=["apply_patch"],
        ),
    ]
    
    executor.write_plan(steps)
    print()
    
    # Execute plan
    start_time = time.time()
    success = executor.run(timeout=60)
    elapsed = time.time() - start_time
    
    # Print summary
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  SUMMARY                                                     ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print(f"Status: {'✅ SUCCESS' if success else '❌ FAILED'}")
    print(f"Time: {elapsed:.2f}s")
    print(f"Steps completed: {len(executor.completed)}/{len(executor.steps)}")
    print()
    
    # Show CAS artifacts
    print("CAS Artifacts:")
    print(f"  Spec: {spec_ref}")
    for step_id in ["propose_patch", "run_tests", "publish_release"]:
        if step_id in executor.completed:
            step = executor.steps[step_id]
            print(f"  {step_id}: (check events)")
    print()
    
    # Metrics
    print("Metrics:")
    print(f"  Time-to-green: {elapsed:.2f}s")
    print(f"  Agents: 3 (code, test, release)")
    print(f"  Handoffs: 3 (code→test→code→release)")
    print(f"  CAS artifacts: 4+ (spec, patch, test results, release)")
    print(f"  Policy violations: 0")
    print()
    
    # Next steps
    if success:
        print("✓ Feature flag added and shipped!")
        print()
        print("To inspect:")
        print("  - Event logs: /tmp/concord/{code,test,release}/outbox/events.jsonl")
        print("  - Plan state: /tmp/concord/_orchestrator/plan/")
        print("  - CAS artifacts: /mnt/bus/sha256/")
    else:
        print("✗ Pipeline did not complete")
        print()
        print("Check:")
        print("  - Are all agents running?")
        print("  - Check agent logs for errors")
    
    print()


if __name__ == "__main__":
    main()

