# Concord v0.3.0 Experimental Results - Manifest

**Date:** October 24, 2025  
**Version:** 0.3.0  
**Focus:** Multi-Agent Coordination, Complete Performance Matrix & Transport Analysis

---

## Files Included

### Primary Documentation

- **`concord_v0.3.0_results.pdf`** (218 KB, 21 pages)
  - Formal experimental report in LaTeX/PDF format
  - Complete 2×2 performance matrix
  - Multi-agent pipeline results and analysis
  - Transport mechanism comparison (file/FIFO/UDS)
  - Comparison to traditional approaches

- **`concord_v0.3.0_results.tex`** (LaTeX source)
  - Source document for reproducibility

- **`concord_v0.3.0_manifest.md`** (this file)
  - Traceability and file listing

### Supporting Documentation

- **`multi_agent_results.md`** 
  - Detailed multi-agent pipeline analysis
  - Architecture, performance, code metrics
  - Key insights and conclusions

- **`../examples/transport_comparison_summary.md`**
  - Transport mechanism comparison summary
  - Performance analysis and recommendations
  - When to use file vs FIFO vs UDS

- **`../examples/TRANSPORT_BENCHMARKS_COMPLETE.md`**
  - Complete transport benchmark implementation summary
  - Results, documentation, and next steps

### Experimental Data

- **`fuse_slm_results.txt`**
  - Raw output from SLM+FUSE benchmark (missing quadrant completion)
  - Median latencies: substrate=13.6ms, model=118.5ms, total=132.2ms

- **`/tmp/multiagent_results.txt`** (saved during experiments)
  - Raw output from 5 multi-agent pipeline runs
  - 100% success rate, 50ms time-to-green

- **`../examples/transport_file_results.txt`**
  - File transport benchmark: 5.6ms p50 latency, 13,751 eps

- **`../examples/transport_fifo_results.txt`**
  - FIFO transport benchmark: 1.3ms p50 latency, 939 eps

- **`../examples/transport_uds_results.txt`**
  - UDS transport benchmark: 0.13ms p50 latency, 47,869 eps

### Source Code

- **`../sdk/examples/multiagent_pipeline.py`** (382 LOC)
  - 4 agent implementations: Code, Test, Doc, Release
  - Uses CAS bus for artifact sharing
  - Demonstrates exactly-once semantics

- **`../sdk/examples/multiagent_orchestrator.py`** (327 LOC)
  - Pipeline coordination logic
  - Measures time-to-green, handoff latency, success rate

- **`../sdk/examples/run_multiagent_pipeline.sh`**
  - Automated test harness
  - Starts all 4 agents, runs orchestrator, collects results

- **`../sdk/examples/run_fuse_slm_experiment.sh`**
  - SLM+FUSE benchmark script (completed missing quadrant)

- **`../sdk/examples/compare_polling_vs_notifications.sh`**
  - Verification that system uses fsevents, not polling

- **`../sdk/examples/benchmark_transport_file.py`** (8.4 KB, ~250 LOC)
  - File transport benchmark (baseline)
  - Append-only file with fsync() and fsevents

- **`../sdk/examples/benchmark_transport_fifo.py`** (9.5 KB, ~270 LOC)
  - FIFO transport benchmark
  - Named pipe with dual write (file + pipe)

- **`../sdk/examples/benchmark_transport_uds.py`** (9.7 KB, ~280 LOC)
  - Unix domain socket transport benchmark
  - SOCK_STREAM with NDJSON protocol

### Lab Notebook

- **`../../concord_bench/LAB_LOG.pdf`** (235 KB, 23 pages)
  - Complete lab notebook with Phase 1, Phase 2 (τ-bench), and Phase 3 (transport experiments)
  - Detailed methodology, raw results, and analysis
  - Includes problem-solving and lessons learned

### Previous Versions

- **`concord_v0.2.0_results.pdf`** (215 KB, 20 pages)
  - Single-agent FUSE evaluation
  - Incomplete 2×2 matrix (missing SLM+FUSE)
  - Serves as baseline for v0.3.0 comparison

---

## Key Results Summary

### Complete 2×2 Performance Matrix

| Configuration | Plain Dirs | FUSE Mount |
|---------------|------------|------------|
| **Stub Agent** | 11.9ms | 21.2ms |
| **SLM Agent** | 113.1ms | **132.2ms (NEW)** |

**Finding:** FUSE+SLM adds 19.1ms overhead (17% increase), but model inference still dominates by 9×.

### Multi-Agent Pipeline (4 agents)

```
Pipeline: Code → Test → Doc → Release

Performance:
  Time-to-green:    50ms (p50, end-to-end)
  Success rate:     100% (5/5 runs)
  Handoff latency:  <1ms between agents
  Per-stage:        ~10ms each

Code:
  Total LOC:        709 lines
  Coordination:     33 primitive calls
  External deps:    0

Correctness:
  Exactly-once:     ✓ Verified (tombstone pattern)
  CAS integrity:    ✓ Verified (hash-based artifacts)
  Policy checks:    ✓ Verified (release gating)
```

### Transport Mechanism Analysis (3 transports)

```
Workload: 10,000 events (~80 bytes each)

Results:
  File (baseline):  5.6ms p50, 13,751 eps, 0.38s CPU
  FIFO (dual):      1.3ms p50, 939 eps, 0.49s CPU
  UDS (stream):     0.13ms p50, 47,869 eps, 0.09s CPU

Key Finding:
  UDS is 43× faster than file-based coordination
  BUT file's 5.6ms latency is acceptable (<5% of agent inference time)
  File-based coordination remains right default for durability & debuggability
```

---

## Changes from v0.2.0

### New Experiments

1. **SLM + FUSE Benchmark** (Experiment 1 extension)
   - Completed missing quadrant of 2×2 matrix
   - Result: 132.2ms total (13.6ms substrate + 118.5ms model)
   - Validates that model still dominates with FUSE overhead

2. **Multi-Agent Pipeline** (Experiment 2, new)
   - 4-agent coordination: Code → Test → Doc → Release
   - 50ms time-to-green with 100% success rate
   - Demonstrates CAS bus, exactly-once semantics, policy enforcement

3. **Transport Mechanism Analysis** (Experiment 3, new)
   - Benchmarked file, FIFO, and Unix domain socket transports
   - 10,000 events per transport with comprehensive metrics
   - Result: UDS is 43× faster, but file's 5.6ms is acceptable
   - Recommendation: File-based coordination is right default

### Clarifications

1. **Notification Architecture**
   - v0.2.0 incorrectly mentioned "10ms polling"
   - v0.3.0 clarifies: agents use fsevents/inotify (1-2ms latency)
   - Orchestrator polls event log at 1ms (reading only, doesn't affect substrate measurement)

2. **Test Configuration**
   - Updated to show "fsevents/inotify via watchdog"
   - Clarified that polling is for event log reading, not intent detection

### New Features Demonstrated

1. **CAS Bus (Content-Addressable Storage)**
   - SHA256-based artifact storage
   - Efficient reference passing (64-byte hash vs multi-KB content)
   - Automatic deduplication and integrity verification

2. **Multi-Agent Coordination Patterns**
   - Sequential pipeline (agent A → agent B → agent C → agent D)
   - Artifact passing via CAS references
   - Policy-gated final stage (release checks)
   - Event-driven handoffs (<1ms latency)

---

## Reproducibility

### Environment

- **Hardware:** Apple M1 Pro, 16GB RAM, NVMe SSD
- **OS:** macOS Sequoia 15.0.1
- **Python:** 3.13
- **Concord SDK:** v0.3.0
- **macFUSE:** 4.5.0
- **SLM Model:** Qwen2.5-Coder-3B-Instruct (Q4_K_M)
- **Dependencies:** watchdog==6.0.0, psutil==7.1.1

### Running Experiments

```bash
# Complete 2×2 matrix (SLM+FUSE quadrant)
cd concord/sdk/examples
./run_fuse_slm_experiment.sh

# Multi-agent pipeline (5 runs)
./run_multiagent_pipeline.sh 5

# Notification verification
./compare_polling_vs_notifications.sh

# Transport mechanism benchmarks
./benchmark_transport_file.py --events 10000
./benchmark_transport_fifo.py --events 10000
./benchmark_transport_uds.py --events 10000
```

### Expected Results

- **SLM+FUSE:** ~132ms total latency (±10ms variance)
- **Multi-agent:** 40-60ms time-to-green, 100% success
- **Notifications:** ~11-12ms substrate latency (not 20ms+ from polling)
- **Transport:** File=5.6ms, FIFO=1.3ms, UDS=0.13ms p50 latency

---

## Comparison to v0.2.0

| Aspect | v0.2.0 | v0.3.0 |
|--------|--------|--------|
| **Experiments** | Single-agent only | Single + multi-agent |
| **2×2 Matrix** | 3/4 quadrants | 4/4 quadrants complete ✓ |
| **Agent Count** | 1 | 4 (pipeline) |
| **CAS Bus** | Not demonstrated | Fully integrated |
| **Time-to-Green** | N/A (single agent) | 50ms (4 agents) |
| **Code Complexity** | ~200 LOC (examples) | 709 LOC (4-agent system) |
| **Policy Enforcement** | Not demonstrated | Release gating verified |
| **Notification Clarity** | "10ms polling" (incorrect) | fsevents/inotify (correct) |

---

## Validation Checklist

- [x] Complete 2×2 performance matrix
- [x] Multi-agent pipeline working (4 agents)
- [x] 100% success rate (no failures)
- [x] Exactly-once semantics verified
- [x] CAS bus integrity verified
- [x] Policy enforcement verified
- [x] Notification architecture clarified
- [x] Code metrics documented
- [x] Comparison to traditional approaches
- [x] Transport mechanisms benchmarked (file/FIFO/UDS)
- [x] Durability vs latency tradeoff quantified
- [x] PDF report generated (21 pages)
- [x] Lab notebook compiled (23 pages)
- [x] Source code included
- [x] Reproducibility instructions provided

---

## Known Limitations

1. **Single-machine testing:** All experiments on one Mac (network filesystem not tested)
2. **Stub agents:** Multi-agent uses simplified logic (not full SLM in pipeline)
3. **No fault injection:** MTTR not measured, agent crashes not tested
4. **No baseline comparison:** gRPC/Kafka/AutoGen estimated but not benchmarked
5. **macOS only:** Linux (FUSE3, inotify) characteristics may differ

---

## Next Steps (v0.4.0)

- [ ] Fault tolerance: Measure MTTR with agent crashes
- [ ] Baseline comparisons: Implement minimal gRPC/Kafka equivalents
- [ ] Concurrent load: Test 10+ concurrent pipelines
- [ ] Linux testing: Validate on FUSE3 with inotify
- [x] Transport alternatives: Named pipes (FIFO) and Unix domain sockets (UDS) - COMPLETED
- [ ] Network filesystems: NFS, GlusterFS latency impact
- [ ] Multi-agent benchmarks: AgentBench, LangGraph (Phase 2 continuation)

---

## Traceability

**Experiment Date:** October 21-24, 2025  
**Git Commit:** v0.3.0 (to be tagged)  
**Model Checkpoint:** Qwen2.5-Coder-3B-Instruct Q4_K_M  
**Environment Hash:** macOS 15.0.1 + Python 3.13 + macFUSE 4.5.0  

**Raw Data Locations:**
- FUSE+SLM results: `concord/experiments/fuse_slm_results.txt`
- Multi-agent results: `/tmp/multiagent_results.txt` (copied to experiments/)
- Transport results: `concord/sdk/examples/transport_{file,fifo,uds}_results.txt`
- Agent logs: `/tmp/*_agent.log` (temporary, not archived)
- CAS artifacts: `/tmp/bus/sha256/` (temporary, not archived)

**Code Locations:**
- Agents: `concord/sdk/examples/multiagent_pipeline.py`
- Orchestrator: `concord/sdk/examples/multiagent_orchestrator.py`
- Test harness: `concord/sdk/examples/run_multiagent_pipeline.sh`
- FUSE benchmark: `concord/sdk/examples/run_fuse_slm_experiment.sh`
- Transport benchmarks: `concord/sdk/examples/benchmark_transport_{file,fifo,uds}.py`

---

**End of Manifest**


