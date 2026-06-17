# Concord v0.1.0 - Experiments Completed (2025-10-21)

## ✅ Completed Experiments

### 1. Single-Agent Minimal Prototype (DONE ✓)
- **File**: `sdk/examples/minimal_agent.py`, `orchestrator.py`
- **Results**: `RESULTS.md`
- **Key Metrics**:
  - t0→t1: ~10 ms (polling)
  - t0→t2: ~12 ms (end-to-end)
  - Exactly-once semantics verified (tombstones work)

### 2. SLM Integration (DONE ✓)
- **File**: `sdk/examples/agent_with_slm.py`
- **Results**: `SLM_INTEGRATION.md`, `experiments/concord_v0.1.0_results.pdf`
- **Model**: Qwen2.5-Coder-7B-Instruct-Q4_K_M (llama.cpp)
- **Key Metrics**:
  - SLM initialization: 2.8s
  - SLM inference (50 tokens): 1.2s
  - Substrate overhead: <10 ms

### 3. File Notifications Upgrade (DONE ✓)
- **File**: `sdk/python/concord/agent.py` (refactored)
- **Change**: Replaced polling with `watchdog` (inotify/fsevents)
- **Key Metrics**:
  - t0→t1: ~1-2 ms (10x improvement)
  - Handles both `on_created` and `on_moved` events
  - macOS symlink resolution fixed

### 4. CAS Bus (DONE ✓)
- **File**: `sdk/python/concord/cas.py`
- **Location**: `/tmp/bus/sha256/<hash>`
- **Features**:
  - Content-addressable storage with metadata
  - Agents pass hash refs instead of blobs
  - Atomic writes with `.tmp` prefix

### 5. Multi-Agent Orchestration (DONE ✓)
- **File**: `sdk/python/concord/orchestrator.py`
- **Features**:
  - Plan graph with dependencies
  - Template resolution (`{{step_id.artifact}}`)
  - Event-driven step advancement
  - Multiple success/failure event types

### 6. Multi-Agent "Add Feature Flag and Ship" Pipeline (DONE ✓)
- **Files**: 
  - `sdk/examples/multiagent/code_agent.py`
  - `sdk/examples/multiagent/test_agent.py`
  - `sdk/examples/multiagent/release_agent.py`
  - `sdk/examples/multiagent/demo_feature_flag.py`
- **Results**: `MULTIAGENT_RESULTS.md`
- **Key Metrics**:
  - **End-to-end**: 0.32s (4 steps, 3 agents)
  - **Handoffs**: 3 (code→test→code→release)
  - **Policy violations**: 0
  - **Steps completed**: 4/4 (100%)
  - **Glue code**: ~40 LOC per agent

---

## 📊 Summary Metrics

| Metric | Value | Comparison |
|--------|-------|------------|
| **Latency (intent→event)** | 1-2 ms | 10x better than polling (10 ms) |
| **End-to-end pipeline** | 0.32s | N/A (need baseline) |
| **Glue code per agent** | ~40 LOC | vs. ~60-80 LOC (AutoGen/Crew est.) |
| **Policy violations** | 0 | Filesystem-enforced |
| **Exactly-once** | ✓ | Atomic rename + tombstones |
| **Observable** | ✓ | All coordination via files |

---

## 🔧 Critical Fixes Applied

1. **macOS path resolution**: `/tmp` → `/private/tmp` symlink handling
2. **Event type handling**: Accept multiple success events (`tests_passed`, `release_published`, etc.)
3. **`step_id` propagation**: Extract from `intent.args` in all agents
4. **Template resolution**: Regex-based substitution for `{{step_id.field}}`
5. **Watchdog event handling**: Handle both `on_created` and `on_moved` (atomic rename)
6. **Intent dataclass**: Filter extra fields in `Intent.from_file()`

---

## 📂 Key Files

### Core SDK
- `sdk/python/concord/agent.py` (172 LOC) - Base agent with file notifications
- `sdk/python/concord/orchestrator.py` (289 LOC) - Plan executor
- `sdk/python/concord/cas.py` (151 LOC) - Content-addressable storage

### Examples
- `sdk/examples/minimal_agent.py` - Single-agent demo
- `sdk/examples/agent_with_slm.py` - SLM integration demo
- `sdk/examples/multiagent/` - 3-agent pipeline demo

### Results
- `RESULTS.md` - Single-agent results
- `SLM_INTEGRATION.md` - SLM integration results
- `MULTIAGENT_RESULTS.md` - Multi-agent pipeline results
- `experiments/concord_v0.1.0_results.pdf` - Formal results (LaTeX)

---

## 🚀 Next Steps

### Immediate (< 1 hour)
- [ ] Add `doc` and `review` agents (→ 5-agent pipeline)
- [ ] Structured event schema with validation
- [ ] Failure injection (test MTTR < 1s)

### Short-term (1-4 hours)
- [ ] **Baseline comparison**: Run same task with AutoGen/CrewAI
- [ ] Real SLM integration in multi-agent pipeline
- [ ] Gantt chart visualization from `events.jsonl`

### Longer-term
- [ ] Remote agents via SSH/WireGuard
- [ ] TLA+ spec for invariants
- [ ] Model router (`models/`, `router/`)
- [ ] Distributed sensing workload (edge + fog)

---

## ✅ Go/No-Go Checklist (All Green!)

✅ inotify/fsevents wired; t0→t1 ≈ 1–2 ms locally  
✅ CAS bus mount works; agents pass hash refs, not blobs  
✅ Two agents can hand off via events→intent→events  
✅ Orchestrator writes plan files and advances steps deterministically  
✅ SLM wired and tested (Qwen2.5-Coder-7B)  
✅ 3-agent pipeline completes successfully in <1s

**Status**: ✅ **READY FOR BASELINE COMPARISON**

---

## 🎯 Hypothesis Validation (So Far)

| Hypothesis | Status | Evidence |
|------------|--------|----------|
| **H1: Performance** (10x latency improvement) | ✅ VALIDATED | 1-2 ms (inotify) vs. 10 ms (polling) |
| **H2: Reliability** (MTTR ≤1s, zero cascades) | ⏳ PARTIAL | Tombstones work; need failure injection |
| **H3: Usability** (40% less glue code) | ⏳ PENDING | Need AutoGen/Crew baseline |
| **H4: Reasoning** (better plan success) | ⏳ PENDING | Need SLM in multi-agent + baseline |

**Next**: Run baseline comparisons to validate H3 and H4.

