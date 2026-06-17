#!/usr/bin/env python3
"""
Code Agent - Proposes and applies patches

Operations:
- propose_patch: Generate a code patch based on spec
- apply_patch: Apply a validated patch
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python"))

from concord import Agent, Intent, Event, get_cas_bus
import time
import json


class CodeAgent(Agent):
    """Generates and applies code patches"""
    
    def __init__(self, name: str = "code", base_path: str = "/tmp/concord"):
        super().__init__(name, base_path)
        self.cas = get_cas_bus()
        print(f"Code Agent initialized with CAS bus")
    
    def handle_intent(self, intent: Intent) -> None:
        """Handle code-related intents"""
        t1 = time.time()
        step_id = intent.args.get("step_id")
        
        print(f"  [{intent.op}] Processing... (step: {step_id})")
        
        if intent.op == "propose_patch":
            self._propose_patch(intent, t1, step_id)
        elif intent.op == "apply_patch":
            self._apply_patch(intent, t1, step_id)
        else:
            self.emit_event(Event(
                id=intent.id,
                event="error",
                t=time.time(),
                t1=t1,
                step_id=step_id,
                artifact=f"Unknown operation: {intent.op}",
            ))
    
    def _propose_patch(self, intent: Intent, t1: float, step_id: str):
        """Generate a patch (stub - would call SLM in real version)"""
        spec_ref = intent.args.get("spec")
        
        # In real version: call SLM to generate patch
        # For now, create a simple patch
        patch_content = f"""
--- a/foo.py
+++ b/foo.py
@@ -10,6 +10,9 @@
 def main(args):
+    if args.dry_run:
+        print("DRY RUN MODE")
+        return
     process(args)
"""
        
        # Store patch in CAS
        patch_hash = self.cas.put(patch_content, "text/x-patch")
        patch_ref = self.cas.ref(patch_hash)
        
        print(f"    Generated patch: {patch_hash[:16]}...")
        
        # Emit completion event
        self.emit_event(Event(
            id=intent.id,
            event="completed",
            t=time.time(),
            t1=t1,
            step_id=step_id,
            artifact=patch_ref,
            engine="stub-codegen",
            tokens=0,
        ))
    
    def _apply_patch(self, intent: Intent, t1: float, step_id: str):
        """Apply a validated patch"""
        patch_ref = intent.args.get("patch")
        patch_hash = self.cas.parse_ref(patch_ref)
        
        if not patch_hash:
            self.emit_event(Event(
                id=intent.id,
                event="error",
                t=time.time(),
                t1=t1,
                step_id=step_id,
                artifact="Invalid patch reference",
            ))
            return
        
        # Retrieve patch
        patch_content = self.cas.get_text(patch_hash)
        
        if not patch_content:
            self.emit_event(Event(
                id=intent.id,
                event="error",
                t=time.time(),
                t1=t1,
                step_id=step_id,
                artifact="Patch not found in CAS",
            ))
            return
        
        # In real version: apply patch to actual files
        print(f"    Applied patch: {patch_hash[:16]}...")
        
        self.emit_event(Event(
            id=intent.id,
            event="completed",
            t=time.time(),
            t1=t1,
            step_id=step_id,
            artifact=patch_ref,
        ))


def main():
    agent = CodeAgent()
    agent.run()


if __name__ == "__main__":
    main()

