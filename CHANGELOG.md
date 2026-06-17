# Changelog

All notable changes to ConcordFS are documented in this file.

## [0.3.0] - 2025-10-24

### Added

- **Transport benchmark suite**: file, FIFO, and Unix domain socket benchmarks with latency, throughput, CPU, and context-switch metrics (`benchmark_transport_file.py`, `benchmark_transport_fifo.py`, `benchmark_transport_uds.py`)
- **Multi-agent pipeline**: 4-agent pipeline (code, test, doc, release) with CAS bus artifact sharing, exactly-once semantics, and policy-gated release stage (`multiagent_pipeline.py`, `multiagent_orchestrator.py`)
- **Complete 2x2 performance matrix**: SLM+FUSE benchmark completing the missing quadrant from v0.2.0 (132.2ms total, FUSE overhead negligible vs model inference)
- **Atomic commit protocol** (`fsops.py`): `atomic_write_bytes`, `atomic_write_text`, `atomic_write_json`, and `_fsync_dir` implementing the write-fsync-rename-dir_fsync protocol
- **Storage contract probe** (`contract_probe.py`): runtime validation of C1 (atomic rename), C2 (durable publish), and C3 (close-to-open visibility) properties with multi-process concurrency tests
- **LangGraph checkpoint saver** (`langgraph_saver.py`): drop-in `BaseCheckpointSaver` implementation backed by ConcordFS's durable commit protocol, replacing `SqliteSaver` or `InMemorySaver`
- **PlanExecutor storage contract enforcement**: `PlanExecutor.__init__` now runs the storage contract probe and refuses to proceed unless all three contract items pass (or `allow_weak_durability=True` is set)
- Experiment data: `benchmarks_concordfs_eval.csv` with 3,700+ evaluation runs across two application domains

### Changed

- `CASBus.store()` now uses atomic writes via `fsops.atomic_write_bytes` and `fsops.atomic_write_json` instead of raw `Path.write_bytes`/`Path.write_text`, preventing torn reads on concurrent access
- `PlanExecutor` uses `atomic_write_json` and `atomic_write_text` for all filesystem writes (plan graphs, intents, step markers), replacing the previous non-durable write-then-rename pattern
- Updated `VERSION`, `README.md`, `Makefile`, and `requirements.txt` to reflect v0.3.0

### Fixed

- CAS content store could produce torn reads if two agents stored the same hash concurrently. The store now checks for existence before writing and uses atomic commits.
- PlanExecutor intent writes previously used a two-step tmp-write + rename without `fsync`, which could lose data on crash. All writes now use the full durable commit protocol.

## [0.2.0] - 2025-10-21

### Added

- Mount abstraction layer (`mount.py`) with `AgentMount` and `MountManager`
- Optional FUSE filesystem layer (`fusemount.py`) with `ConcordFS`
- File notifications via `watchdog` (inotify/fsevents), eliminating polling
- Multi-agent coordination validated at 320ms for 4-step pipeline
- CAS bus for zero-copy artifact passing
- 17 comprehensive tests for mount operations
- `MOUNT_LAYER_V0.2.0.md` documentation

## [0.1.0] - 2025-10-20

### Added

- Initial Python SDK with `Agent`, `Intent`, `Event`, `Router`
- `CASBus` for content-addressable storage
- `PlanExecutor` and `Step` for multi-agent orchestration
- Polling-based inbox watching (10ms latency)
- Experimental validation with Qwen2.5-Coder-3B SLM
