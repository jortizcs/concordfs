# ConcordFS v0.3.0

**Filesystem-Native Coordination for Multi-Agent LLM Systems**

ConcordFS uses POSIX filesystem operations (atomic rename, `fsync`, `O_APPEND`, `flock`) to coordinate distributed AI agents. All coordination state is visible as ordinary files, providing forensic independence and crash-consistent recovery without framework-coupled decoding.

## Quick Start

```bash
# Install the SDK
cd sdk/python && pip install -e .

# Verify installation
python -c "import concord; print(concord.__version__)"
# 0.3.0

# Validate your filesystem's storage contract
python -m concord.contract_probe /tmp/concord

# Run the multi-agent demo
cd sdk/examples/multiagent
./start_agents.sh
python3 demo_feature_flag.py
```

## What's In v0.3.0

**Python SDK** (`sdk/python/concord/`)
- `Agent` base class with file notifications (inotify/fsevents)
- `MountManager` for agent filesystem management
- `CASBus` for content-addressable artifact storage (atomic writes)
- `PlanExecutor` for multi-agent orchestration with storage contract enforcement
- `fsops` module implementing the durable commit protocol (write-fsync-rename-dir_fsync)
- `contract_probe` for validating C1-C3 storage contract properties
- `langgraph_saver` for LangGraph checkpoint integration via ConcordFS
- Exactly-once processing (rename + tombstones)
- Append-only event logs (`O_APPEND`)
- Optional FUSE layer (requires fusepy + macFUSE/FUSE)

**Examples** (`sdk/examples/`)
- Minimal agent implementation
- Multi-agent 4-stage pipeline (code, test, doc, release)
- Transport benchmarks (file, FIFO, Unix domain sockets)

**Experiments** (`experiments/`)
- v0.3.0 results and manifest
- ConcordFS evaluation benchmarks (3,700+ runs across two application domains)
- SLM reasoning experiments

## Project Structure

```
concord/
├── README.md                       This file
├── VERSION                         Version info and history
├── LICENSE                         MIT
├── CHANGELOG.md                    Change log
├── Makefile                        Build automation
├── requirements.txt                Python dependencies
│
├── sdk/
│   ├── python/
│   │   ├── concord/
│   │   │   ├── __init__.py         Public API, version
│   │   │   ├── agent.py            Agent base class
│   │   │   ├── cas.py              Content-addressable storage
│   │   │   ├── orchestrator.py     PlanExecutor
│   │   │   ├── mount.py            Mount abstraction layer
│   │   │   ├── fusemount.py        Optional FUSE layer
│   │   │   ├── router.py           Router stub
│   │   │   ├── fsops.py            Atomic commit primitives
│   │   │   ├── contract_probe.py   Storage contract probe (C1-C3)
│   │   │   └── langgraph_saver.py  LangGraph checkpoint saver
│   │   ├── tests/
│   │   └── setup.py
│   │
│   └── examples/
│       ├── minimal_agent.py
│       ├── orchestrator.py
│       ├── benchmark_transport_*.py
│       └── multiagent/
│
└── experiments/
    ├── concord_v0.3.0_manifest.md
    ├── concord_v0.3.0_results.tex
    └── benchmarks_concordfs_eval.csv
```

## Storage Contract

ConcordFS requires three filesystem properties for its safety guarantees:

| Contract | Property | POSIX Mechanism |
|----------|----------|-----------------|
| C1 | Atomic rename | `rename(2)` provides atomic visibility |
| C2 | Durable publish | `fsync` on file + `fsync` on directory |
| C3 | Read visibility | Close-to-open consistency |

Run the contract probe to validate your filesystem:

```bash
python -m concord.contract_probe /path/to/mount
```

## Agent Filesystem Layout

```
/tmp/concord/<agent>/
├── inbox/                   Intents arrive here
│   ├── <uuid>.json          Active intent
│   └── <uuid>.json.done     Tombstone (processed)
├── outbox/
│   └── events.jsonl         Append-only event log
├── fs/                      Shared workspace
├── locks/                   Leases
├── caps/                    Capabilities
├── policy/                  Policies
└── stats/                   Runtime statistics
```

## Coordination Semantics

| Semantic | POSIX Operation |
|----------|-----------------|
| Exactly-once queue | `rename` + `.done` tombstone |
| Atomic commits | write-fsync-rename-dir_fsync |
| Ordered events | `O_APPEND` on `events.jsonl` |
| Observability | All state is files (`ls`, `cat`, `tail -f`) |

## Build Your Own Agent

```python
from concord import Agent, Intent, Event
import time

class MyAgent(Agent):
    def handle_intent(self, intent: Intent):
        result = f"Processed: {intent.op}"
        self.emit_event(Event(
            id=intent.id,
            event="completed",
            t=time.time(),
            artifact=result,
        ))

agent = MyAgent("myagent")
agent.run()
```

## LangGraph Integration

```python
from concord.langgraph_saver import ConcordFSCheckpointSaver

with ConcordFSCheckpointSaver("/mnt/concord/checkpoints") as saver:
    graph = workflow.compile(checkpointer=saver)
```

All checkpoint state is stored as individual JSON files using the durable commit protocol, providing inspectability via standard POSIX tools.

## Experimental Results (v0.3.0)

### Single-Agent Performance

| Configuration | Plain Directories | FUSE Mount |
|---------------|-------------------|------------|
| Stub Agent | 11.9ms | 21.2ms |
| SLM Agent (Qwen2.5-3B) | 113.1ms | 132.2ms |

FUSE adds 19.1ms overhead (17%), but model inference dominates by 9x.

### Transport Comparison

| Transport | p50 Latency | Throughput | Durability |
|-----------|-------------|------------|------------|
| File | 5.6ms | 13,751 eps | Durable |
| FIFO | 1.3ms | 939 eps | Ephemeral |
| UDS | 0.13ms | 47,869 eps | Ephemeral |

File-based latency (5.6ms) is less than 5% of typical agent inference time (100-1000ms), while providing durability, debuggability, and network transparency.

### Multi-Agent Pipeline

4-agent pipeline (code, test, doc, release) with 50ms time-to-green, 100% reliability, and 709 LOC total implementation.

## Development

```bash
make install         # Install Python SDK (editable)
make test            # Run pytest suite
make run-experiment  # Run latency experiment
make clean           # Clean build artifacts
make inspect         # Show filesystem state
```

## Requirements

- Python 3.11+
- macOS or Linux
- watchdog >= 3.0.0
- (Optional) fusepy >= 3.0.1 for FUSE layer
- (Optional) langgraph for checkpoint saver

## License

MIT License. Copyright (c) 2025 Jorge Ortiz, Rutgers University.

## Citation

```bibtex
@software{concordfs2025,
  author = {Jorge Ortiz},
  title = {ConcordFS: Filesystem-Native Coordination for Multi-Agent LLM Systems},
  year = {2025},
  version = {0.3.0},
  url = {https://github.com/jortizcs/concord}
}
```

## Links

- **Repository:** https://github.com/jortizcs/concord
- **Issues:** https://github.com/jortizcs/concord/issues
- **Paper:** [ConcordFS: Filesystem-based Coordination for Reliable Multi-Agent Systems](https://arxiv.org/abs/XXXX.XXXXX)
