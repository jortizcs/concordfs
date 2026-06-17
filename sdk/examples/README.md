# Minimal Concord Experiment

**Goal**: Validate filesystem-native coordination semantics and measure latency.

## What This Measures

- **t0→t1**: Substrate cost (orchestrator writes intent → agent sees it)
- **t1→t2**: Agent processing cost (currently stub, will be SLM later)
- **t0→t2**: End-to-end latency

## Semantics Validated

✅ **Exactly-once**: `.done` tombstones prevent reprocessing  
✅ **Atomic commits**: `rename` ensures no partial intents  
✅ **Ordered events**: `O_APPEND` on `events.jsonl`  
✅ **Crash recovery**: Agent restart skips `.done` files

## Quick Start

### 1. Run the agent (Terminal 1)

```bash
cd sdk/examples
python3 minimal_agent.py
```

You should see:
```
Starting Concord agent 'demo'
Agent 'demo' watching /tmp/concord/demo/inbox
Event log: /tmp/concord/demo/outbox/events.jsonl
```

### 2. Run the orchestrator (Terminal 2)

```bash
cd sdk/examples
python3 orchestrator.py
```

You should see latency measurements:
```
Concord Latency Experiment
Agent: demo
Warmup: 10 intents...
Measuring: 200 intents...

============================================================
RESULTS
============================================================
t0→t1 (substrate)              min=  0.123 ms  p50=  0.456 ms  p95=  1.234 ms  max=  2.345 ms
t1→t2 (agent work)             min=  0.012 ms  p50=  0.023 ms  p95=  0.045 ms  max=  0.089 ms
t0→t2 (end-to-end)             min=  0.145 ms  p50=  0.489 ms  p95=  1.289 ms  max=  2.456 ms

Total intents: 200
Throughput: 2048.3 intents/s
```

## Expected Results (Sanity Check)

On a modern laptop:
- **t0→t1 p50**: ~0.5-2 ms (filesystem + polling)
- **t1→t2 p50**: ~0.02-0.1 ms (stub processing)
- **t0→t2 p50**: ~0.5-2 ms

**Good enough?** If t0→t1 median is < 5ms, the substrate is viable. Once you add SLM, t1→t2 will grow to 50-500ms depending on model size.

## Filesystem Structure Created

```
/tmp/concord/demo/
├── inbox/
│   ├── <uuid>.json         # active intents
│   └── <uuid>.json.done    # processed (tombstones)
├── outbox/
│   └── events.jsonl        # append-only event log
└── fs/                     # (unused in minimal example)
```

## Next Steps

### A/B Test: With vs Without SLM

Edit `minimal_agent.py`, uncomment the SLM block, and run:

```python
# In handle_intent():
result = subprocess.run([
    "llama-cli",
    "-m", "models/phi3-mini-q4.gguf",
    "-p", f"Task: {intent.op}",
    "-n", "64"
], capture_output=True)
engine = "phi3-mini-q4"
tokens = 64
```

Compare the new t1→t2 median. The delta = model cost.

### Upgrade to inotify (better t0→t1)

Replace the `poll_inbox()` loop with `watchdog`:

```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class InboxHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        self.agent.process_intent_file(Path(event.src_path))
```

This should cut t0→t1 by ~50%.

### Add a Second Agent (Multi-Agent Handoff)

Create `test_agent.py` that reads artifacts from the first agent's events and validates them. Pass artifact paths via `events.jsonl`.

## Troubleshooting

**Agent not seeing intents?**
- Check `/tmp/concord/demo/inbox/` exists
- Look for `.tmp-*` files (means rename failed)

**No events.jsonl?**
- Agent creates it on first event
- Check agent console for errors

**High latency?**
- Reduce poll interval in `agent.py` (default 0.01s = 10ms)
- Later: switch to inotify/fsevents

## FUSE Mount Layer Testing

ConcordFS provides an optional FUSE-based virtual filesystem layer. Three test suites are available:

### Test Files

1. **`test_fusemount.py`** - Basic functionality test
   - Mount/unmount operations
   - Standard directory structure
   - Atomic file operations
   - Event log appending
   - Tombstone mechanism
   
   ```bash
   python3 test_fusemount.py
   ```

2. **`test_fuse_backend.py`** - Backend operations test
   - Direct filesystem API validation
   - File handle management
   - Atomic operations
   - Read/write/rename/delete operations
   
   ```bash
   python3 test_fuse_backend.py
   ```

3. **`test_fusemount_comprehensive.py`** - Comprehensive integration test
   - 10 concurrent intents
   - 15 event log entries
   - Artifact storage (15KB)
   - Lock/lease mechanism
   - Policy enforcement
   - Large file I/O (100KB)
   
   ```bash
   python3 test_fusemount_comprehensive.py
   ```

### Requirements

- **macOS**: Requires macFUSE (`brew install macfuse`) and kernel extension approval
- **Linux**: Requires FUSE3 (`apt install fuse3` or similar)
- **Python**: `fusepy` package (installed via `pip install -r ../requirements.txt`)

### Test Results

See `../../FUSE_TEST_REPORT.md` for complete test documentation.

**Status:** ✅ All 29 tests passing on macOS Darwin 24.6.0

## What's Next in v0.2.0

- [x] FUSE mount layer with full test coverage
- [ ] Replace polling with inotify/fsevents
- [ ] Add model router daemon
- [ ] llama.cpp integration
- [ ] Prompt caching
- [ ] Token budget enforcement

