#!/usr/bin/env python3
"""
Minimal Concord agent example

This agent:
1. Watches /tmp/concord/demo/inbox/ for intent files
2. Processes each intent (with optional SLM call)
3. Appends an event to outbox/events.jsonl
4. Tombstones the intent with .done to prevent reprocessing

Semantics:
- Exactly-once: rename to .done ensures no reprocessing
- Append-only log: O_APPEND on events.jsonl ensures ordered, durable events
- Atomic commits: intents are only visible after rename (orchestrator writes to .tmp first)
"""

import sys
from pathlib import Path

# Add SDK to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from concord import Agent, Intent, Event
import time


class DemoAgent(Agent):
    """Demo agent that echoes intents with optional SLM processing"""
    
    def handle_intent(self, intent: Intent) -> None:
        """Handle an intent: measure time, optionally call SLM, emit event"""
        t1 = time.time()
        
        print(f"  Intent {intent.id[:8]}: op={intent.op}")
        
        # --- Optional: Call SLM here ---
        # For v0.1.0, just a stub. Later:
        # result = self.call_llm(intent)
        # engine = result["engine"]
        # tokens = result["tokens"]
        
        result_text = f"Processed {intent.op}"
        engine = "stub"
        tokens = 0
        
        # Emit acknowledgment event
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


def main():
    agent = DemoAgent(name="demo")
    agent.run()


if __name__ == "__main__":
    main()

