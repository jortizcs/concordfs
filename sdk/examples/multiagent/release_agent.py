#!/usr/bin/env python3
"""
Release Agent - Publishes releases (with policy enforcement)

Operations:
- publish_release: Create and publish a release

Policy: no_network enforced (would be enforced by cgroups/namespaces in full version)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "python"))

from concord import Agent, Intent, Event, get_cas_bus
import time
import json


class ReleaseAgent(Agent):
    """Publishes releases with policy enforcement"""
    
    def __init__(self, name: str = "release", base_path: str = "/tmp/concord"):
        super().__init__(name, base_path)
        self.cas = get_cas_bus()
        
        # Check policy
        self.policy_dir = self.base / "policy"
        self.policy_dir.mkdir(exist_ok=True)
        
        # Read policies
        self.no_network = (self.policy_dir / "no_network").exists()
        
        print(f"Release Agent initialized")
        if self.no_network:
            print(f"  Policy: no_network=true")
    
    def handle_intent(self, intent: Intent) -> None:
        """Handle release-related intents"""
        t1 = time.time()
        
        print(f"  [{intent.op}] Processing...")
        
        if intent.op == "publish_release":
            self._publish_release(intent, t1)
        else:
            self.emit_event(Event(
                id=intent.id,
                event="error",
                t=time.time(),
                t1=t1,
                artifact=f"Unknown operation: {intent.op}",
            ))
    
    def _publish_release(self, intent: Intent, t1: float):
        """Publish a release"""
        patch_ref = intent.args.get("patch")
        version = intent.args.get("version", "0.2.0")
        step_id = intent.args.get("step_id")
        
        # In real version: check if network is needed and respect policy
        if self.no_network:
            print(f"    ⚠️  Policy: no_network enforced (dry-run only)")
        
        # Create release notes
        release_notes = f"""
# Release {version}

## Changes
- Added --dry-run flag to foo command

## Testing
All 42 tests passed

## Artifacts
Patch: {patch_ref}
"""
        
        # Store release in CAS
        release_hash = self.cas.put(release_notes, "text/markdown")
        release_ref = self.cas.ref(release_hash)
        
        print(f"    Created release {version}: {release_hash[:16]}...")
        
        self.emit_event(Event(
            id=intent.id,
            event="release_published",
            t=time.time(),
            t1=t1,
            step_id=step_id,
            artifact=release_ref,
        ))


def main():
    agent = ReleaseAgent()
    agent.run()


if __name__ == "__main__":
    main()

