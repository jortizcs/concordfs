"""
Concord orchestrator with plan graph support

Coordinates multiple agents via filesystem:
- Writes plan/graph.json with dependency DAG
- Signals agents via plan/steps/<id>.ready
- Tracks completion via plan/steps/<id>.done
- Passes artifacts via CAS references
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, asdict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .cas import get_cas_bus
from .fsops import atomic_write_json, atomic_write_text


@dataclass
class Step:
    """A step in the execution plan"""
    id: str
    agent: str
    operation: str
    args: Dict
    depends_on: List[str]
    status: str = "pending"  # pending, ready, running, done, error


class PlanExecutor:
    """Executes a multi-agent plan by coordinating via filesystem"""
    
    def __init__(self, plan_name: str, base_path: str = "/tmp/concord",
                 allow_weak_durability: bool = False):
        self.plan_name = plan_name
        self.base = Path(base_path)
        self.base.mkdir(parents=True, exist_ok=True)

        # ---- Storage contract probe (fail-closed by default) ----
        from .contract_probe import probe_storage_contract
        probe = probe_storage_contract(self.base, verbose=True)
        if not probe.ok:
            if allow_weak_durability:
                import logging
                logging.getLogger("concordfs").warning(
                    "Storage contract violation detected (%s). "
                    "Proceeding with degraded durability guarantees "
                    "(--allow-weak-durability).",
                    probe.summary(),
                )
            else:
                raise RuntimeError(
                    f"ConcordFS storage contract violation: {probe.summary()}. "
                    "ConcordFS requires C1–C3 for its safety properties. "
                    "Pass allow_weak_durability=True to proceed with "
                    "degraded guarantees."
                )

        self.cas = get_cas_bus()
        
        # Plan directory
        self.plan_dir = self.base / "_orchestrator" / "plan"
        self.plan_dir.mkdir(parents=True, exist_ok=True)
        self.steps_dir = self.plan_dir / "steps"
        self.steps_dir.mkdir(exist_ok=True)
        
        # Plan state
        self.steps: Dict[str, Step] = {}
        self.completed: Set[str] = set()
        self.running: Set[str] = set()
        self.step_results: Dict[str, Dict] = {}  # Store results for template resolution
        
        # Event watchers for all agents
        self.agent_dirs: Dict[str, Path] = {}
        self.observers: Dict[str, Observer] = {}
        
    def add_agent(self, agent_name: str):
        """Register an agent for event watching"""
        agent_dir = self.base / agent_name
        self.agent_dirs[agent_name] = agent_dir
        
        # Ensure agent directories exist
        (agent_dir / "inbox").mkdir(parents=True, exist_ok=True)
        (agent_dir / "outbox").mkdir(parents=True, exist_ok=True)
        (agent_dir / "fs" / "work").mkdir(parents=True, exist_ok=True)
        
        # Create events.jsonl if it doesn't exist
        events_log = agent_dir / "outbox" / "events.jsonl"
        if not events_log.exists():
            atomic_write_text(events_log, "")
    
    def write_plan(self, steps: List[Step]):
        """Write execution plan to filesystem"""
        self.steps = {step.id: step for step in steps}
        
        # Write graph.json
        plan_data = {
            "plan": self.plan_name,
            "steps": [asdict(step) for step in steps],
        }
        
        atomic_write_json(self.plan_dir / "graph.json", plan_data, indent=2)
        
        print(f"Plan written: {len(steps)} steps")
        for step in steps:
            print(f"  {step.id}: {step.agent}.{step.operation} (depends: {step.depends_on or 'none'})")
    
    def resolve_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve template strings like {{step_id.artifact}} in args"""
        import re
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str) and "{{" in value:
                # Extract template: {{step_id.field}}
                match = re.match(r'{{(\w+)\.(\w+)}}', value)
                if match:
                    step_id, field = match.groups()
                    if step_id in self.step_results:
                        resolved[key] = self.step_results[step_id].get(field, value)
                    else:
                        resolved[key] = value  # Keep template if step not complete
                else:
                    resolved[key] = value
            else:
                resolved[key] = value
        return resolved
    
    def submit_intent(self, agent: str, step: Step):
        """Submit an intent to an agent's inbox"""
        agent_inbox = self.agent_dirs[agent] / "inbox"
        
        intent_id = str(uuid.uuid4())
        
        # Resolve templates in args (like {{propose_patch.artifact}})
        resolved_args = self.resolve_args(step.args)
        
        # Merge step_id into args so agents can access it easily
        args_with_step = {**resolved_args, "step_id": step.id}
        
        intent = {
            "id": intent_id,
            "step_id": step.id,
            "op": step.operation,
            "args": args_with_step,
            "t0": time.time(),
        }
        
        # Durable atomic commit (write + fsync + rename + dir fsync)
        final_path = agent_inbox / f"{intent_id}.json"
        atomic_write_json(final_path, intent, indent=2)
        
        print(f"[{step.id}] Intent submitted to {agent}: {step.operation}")
        
        # Mark step as running
        self.running.add(step.id)
        self.steps[step.id].status = "running"
        
        # Write ready file
        ready_file = self.steps_dir / f"{step.id}.ready"
        atomic_write_json(ready_file, {
            "step_id": step.id,
            "agent": agent,
            "operation": step.operation,
            "started_at": time.time(),
        }, indent=2)
    
    def mark_step_done(self, step_id: str, result: Dict):
        """Mark a step as completed"""
        if step_id not in self.steps:
            return
        
        self.completed.add(step_id)
        self.running.discard(step_id)
        self.steps[step_id].status = "done"
        
        # Store result for template resolution
        self.step_results[step_id] = result
        
        # Write done file
        done_file = self.steps_dir / f"{step_id}.done"
        atomic_write_json(done_file, {
            "step_id": step_id,
            "completed_at": time.time(),
            "result": result,
        }, indent=2)
        
        print(f"[{step_id}] ✓ Completed")
    
    def can_run_step(self, step: Step) -> bool:
        """Check if a step's dependencies are met"""
        if step.status != "pending":
            return False
        
        for dep_id in step.depends_on:
            if dep_id not in self.completed:
                return False
        
        return True
    
    def advance_plan(self):
        """Check for steps that are ready to run"""
        for step in self.steps.values():
            if self.can_run_step(step):
                step.status = "ready"
                self.submit_intent(step.agent, step)
    
    def watch_events(self, agent: str, event_callback):
        """Watch an agent's event log for new events"""
        events_log = self.agent_dirs[agent] / "outbox" / "events.jsonl"
        
        class EventHandler(FileSystemEventHandler):
            def __init__(self, callback):
                self.callback = callback
                self.last_size = events_log.stat().st_size if events_log.exists() else 0
                super().__init__()
            
            def on_modified(self, event):
                if not event.src_path.endswith("events.jsonl"):
                    return
                
                # Read new events
                try:
                    with open(events_log, "rb") as f:
                        f.seek(self.last_size)
                        new_data = f.read()
                        self.last_size = f.tell()
                    
                    # Parse new events
                    for line in new_data.decode().strip().split('\n'):
                        if line:
                            event_data = json.loads(line)
                            self.callback(agent, event_data)
                except Exception as e:
                    print(f"Error reading events: {e}")
        
        handler = EventHandler(event_callback)
        observer = Observer()
        observer.schedule(handler, str(self.agent_dirs[agent] / "outbox"), recursive=False)
        observer.start()
        
        self.observers[agent] = observer
    
    def stop_watchers(self):
        """Stop all event watchers"""
        for observer in self.observers.values():
            observer.stop()
        for observer in self.observers.values():
            observer.join()
    
    def run(self, timeout: float = 300):
        """Execute the plan"""
        print(f"\n=== Executing plan: {self.plan_name} ===\n")
        
        # Start watching all agents
        def on_event(agent: str, event: Dict):
            step_id = event.get("step_id")
            event_type = event.get("event")
            
            # Accept various success events (completed, tests_passed, release_published, etc.)
            # Reject failure events (error, tests_failed, etc.)
            success_events = {"completed", "tests_passed", "release_published", "applied", "generated"}
            failure_events = {"error", "tests_failed", "failed"}
            
            if step_id and event_type in success_events:
                self.mark_step_done(step_id, event)
                self.advance_plan()
            elif step_id and event_type in failure_events:
                print(f"[{step_id}] ❌ Failed: {event_type}")
                # Mark as failed but don't advance
                self.steps[step_id].status = "failed"
        
        for agent in self.agent_dirs.keys():
            self.watch_events(agent, on_event)
        
        # Initial advance
        self.advance_plan()
        
        # Wait for completion
        start_time = time.time()
        try:
            while len(self.completed) < len(self.steps):
                if time.time() - start_time > timeout:
                    print(f"\n❌ Timeout after {timeout}s")
                    break
                
                time.sleep(0.1)
            
            if len(self.completed) == len(self.steps):
                elapsed = time.time() - start_time
                print(f"\n✅ Plan completed in {elapsed:.2f}s")
                print(f"   Steps: {len(self.completed)}/{len(self.steps)}")
                return True
            else:
                print(f"\n⚠️  Incomplete: {len(self.completed)}/{len(self.steps)} steps done")
                return False
                
        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted")
            return False
        finally:
            self.stop_watchers()

