"""
Concord agent with filesystem notifications (inotify/fsevents)
"""
import json
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent


@dataclass
class Intent:
    """Intent submitted to agent's inbox"""
    id: str
    op: str
    args: Dict[str, Any]
    t0: Optional[float] = None

    @classmethod
    def from_file(cls, path: Path) -> "Intent":
        with open(path, "r") as f:
            data = json.load(f)
        # Filter to only the fields that Intent accepts
        return cls(
            id=data["id"],
            op=data["op"],
            args=data["args"],
            t0=data.get("t0")
        )


@dataclass
class Event:
    """Event emitted to agent's outbox"""
    id: str
    event: str
    t: float
    t1: Optional[float] = None
    step_id: Optional[str] = None
    artifact: Optional[str] = None
    engine: Optional[str] = None
    tokens: Optional[int] = None

    def to_json(self) -> str:
        return json.dumps({k: v for k, v in asdict(self).items() if v is not None})


class InboxHandler(FileSystemEventHandler):
    """Watches inbox/ for new intent files"""
    
    def __init__(self, agent):
        self.agent = agent
        super().__init__()
    
    def on_created(self, event):
        """Handle new file creation in inbox"""
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        
        # Ignore tombstones and temp files
        if path.name.endswith(('.done', '.error')) or path.name.startswith('.tmp'):
            return
        
        # Process the intent immediately
        print(f"  New intent detected (created): {path.name}")
        self.agent.process_intent_file(path)
    
    def on_moved(self, event):
        """Handle file moves (atomic rename creates a moved event on macOS)"""
        if event.is_directory:
            return
        
        dest_path = Path(event.dest_path).resolve()  # Resolve symlinks
        inbox_path = Path(self.agent.inbox).resolve()
        
        # Only process if moved INTO our inbox and not a tombstone/temp
        if (dest_path.parent == inbox_path and
            not dest_path.name.endswith(('.done', '.error')) and
            not dest_path.name.startswith('.tmp')):
            print(f"  New intent detected (moved): {dest_path.name}")
            self.agent.process_intent_file(dest_path)


class Agent:
    """
    Concord agent with filesystem notifications:
    - Watches inbox/ via inotify/fsevents (1-2ms latency)
    - Handles intents via handle_intent() 
    - Appends events to outbox/events.jsonl (O_APPEND)
    - Tombstones processed intents with .done suffix (exactly-once)
    """

    def __init__(self, name: str, base_path: str = "/tmp/concord"):
        self.name = name
        self.base = Path(base_path) / name
        self.inbox = self.base / "inbox"
        self.outbox = self.base / "outbox"
        self.events_log = self.outbox / "events.jsonl"
        
        # Ensure directories exist
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)
        
        # File watcher
        self.observer = Observer()
        self.handler = InboxHandler(self)

    def handle_intent(self, intent: Intent) -> None:
        """
        Override this method in your agent subclass to implement behavior.
        Default: echo acknowledgment.
        """
        t1 = time.time()
        self.emit_event(Event(
            id=intent.id,
            event="ack",
            t=t1,
            t1=t1,
        ))

    def emit_event(self, event: Event) -> None:
        """Append event to outbox/events.jsonl with O_APPEND semantics"""
        with open(self.events_log, "a", buffering=1) as f:
            f.write(event.to_json() + "\n")

    def process_intent_file(self, path: Path) -> None:
        """Process a single intent file with tombstone semantics"""
        try:
            intent = Intent.from_file(path)
            self.handle_intent(intent)
            # Tombstone: rename to .done to prevent reprocessing
            done_path = path.parent / (path.name + ".done")
            os.rename(path, done_path)
        except Exception as e:
            print(f"Error processing {path}: {e}")
            # Still tombstone to avoid infinite retry
            done_path = path.parent / (path.name + ".error")
            os.rename(path, done_path)

    def watch_inbox(self) -> None:
        """Watch inbox/ for new intent files via inotify/fsevents"""
        print(f"Agent '{self.name}' watching {self.inbox}")
        print(f"Event log: {self.events_log}")
        print(f"Using file notifications (inotify/fsevents)")
        
        # Process any existing files first (before watchdog starts)
        existing_files = list(self.inbox.iterdir())
        for path in existing_files:
            if (path.is_file() and 
                not str(path).endswith(('.done', '.error')) and
                not path.name.startswith('.tmp')):
                print(f"  Processing existing intent: {path.name}")
                self.process_intent_file(path)
        
        # Start watching for new files
        self.observer.schedule(self.handler, str(self.inbox), recursive=False)
        self.observer.start()
        
        # Give observer time to fully start
        time.sleep(0.1)
        print("Ready to process intents")
        
        try:
            while True:
                time.sleep(0.1)  # Keep main thread alive
        except KeyboardInterrupt:
            print("\nStopping agent...")
            self.observer.stop()
        
        self.observer.join()
        print("Agent stopped")

    def run(self):
        """Start the agent (blocks until KeyboardInterrupt)"""
        print(f"Starting Concord agent '{self.name}'")
        self.watch_inbox()

