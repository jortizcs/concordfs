#!/usr/bin/env python3
"""
Test Agent - Runs tests and reports results

Operations:
- run_tests: Execute tests for a patch
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python"))

from concord import Agent, Intent, Event, get_cas_bus
import time
import json
import random


class TestAgent(Agent):
    """Runs tests and validates patches"""
    
    def __init__(self, name: str = "test", base_path: str = "/tmp/concord"):
        super().__init__(name, base_path)
        self.cas = get_cas_bus()
        print(f"Test Agent initialized with CAS bus")
    
    def handle_intent(self, intent: Intent) -> None:
        """Handle test-related intents"""
        t1 = time.time()
        
        print(f"  [{intent.op}] Processing...")
        
        if intent.op == "run_tests":
            self._run_tests(intent, t1)
        else:
            self.emit_event(Event(
                id=intent.id,
                event="error",
                t=time.time(),
                t1=t1,
                artifact=f"Unknown operation: {intent.op}",
            ))
    
    def _run_tests(self, intent: Intent, t1: float):
        """Run tests for a patch"""
        patch_ref = intent.args.get("patch")
        step_id = intent.args.get("step_id")
        
        # Simulate running tests
        print(f"    Running tests for patch...")
        time.sleep(0.1)  # Simulate test execution
        
        # In real version: actually run tests
        # For demo: randomly pass/fail
        passed = random.random() > 0.2  # 80% pass rate
        
        if passed:
            print(f"    ✓ Tests passed")
            
            test_results = {
                "status": "pass",
                "tests_run": 42,
                "passed": 42,
                "failed": 0,
            }
            
            # Store test results in CAS
            results_hash = self.cas.put(json.dumps(test_results, indent=2), "application/json")
            results_ref = self.cas.ref(results_hash)
            
            self.emit_event(Event(
                id=intent.id,
                event="tests_passed",
                t=time.time(),
                t1=t1,
                step_id=step_id,
                artifact=results_ref,
            ))
        else:
            print(f"    ✗ Tests failed")
            
            test_results = {
                "status": "fail",
                "tests_run": 42,
                "passed": 38,
                "failed": 4,
                "failures": [
                    {"test": "test_dry_run", "error": "AssertionError: expected True, got False"},
                ],
            }
            
            # Store failure log in CAS
            results_hash = self.cas.put(json.dumps(test_results, indent=2), "application/json")
            results_ref = self.cas.ref(results_hash)
            
            self.emit_event(Event(
                id=intent.id,
                event="tests_failed",
                t=time.time(),
                t1=t1,
                step_id=step_id,
                artifact=results_ref,
            ))


def main():
    agent = TestAgent()
    agent.run()


if __name__ == "__main__":
    main()

