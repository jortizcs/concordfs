# Concord v0.1.0 - Experimental Results

This directory contains the formal experimental validation of Concord v0.1.0.

## 📄 Main Documents

### `concord_v0.1.0_results.pdf` (8 pages, 190 KB)
**Formal experimental report in LaTeX** documenting:
- System under test (software versions, hardware, model config)
- Experimental design and methodology
- Complete results with statistical analysis
- Hypothesis validation
- Comparison to alternative substrates
- Threats to validity
- Reproducibility instructions

### `EXPERIMENT_MANIFEST.md`
**Complete traceability document** with:
- Software version lineage (Concord v0.1.0 → experiments)
- Hardware platform specifications
- Exact dependencies (Python, llama.cpp, model)
- Experimental procedure and timestamps
- SHA256 checksums for verification
- Reproducibility instructions

## 🔬 Key Results

| Metric | Stub Agent | SLM Agent | Finding |
|--------|------------|-----------|---------|
| **Substrate (t0→t1)** | 11.7 ms | 12.0 ms | Constant overhead |
| **Agent work (t1→t2)** | 1.0 ms | 120.7 ms | Model dominates |
| **End-to-end (t0→t2)** | 12.1 ms | 133.2 ms | 9% substrate, 91% model |

**Conclusion**: Filesystem coordination overhead is negligible (9%) compared to AI model inference (91%). Hypothesis validated.

## 🔗 Lineage Tracking

```
Concord v0.1.0 (October 21, 2025)
├── Software Implementation
│   ├── sdk/python/concord/agent.py
│   ├── sdk/examples/minimal_agent.py (stub)
│   ├── sdk/examples/agent_with_slm.py (SLM)
│   └── sdk/examples/orchestrator.py (measurement)
│
├── Experiments Executed
│   ├── compare_stub_vs_slm.sh (automated)
│   ├── Stub agent: 20 intents measured
│   └── SLM agent: 20 intents measured
│
├── Results Documents
│   ├── concord_v0.1.0_results.pdf (this formal report)
│   ├── EXPERIMENT_MANIFEST.md (traceability)
│   ├── ../RESULTS.md (detailed markdown)
│   └── ../SLM_INTEGRATION.md (integration guide)
│
└── Design Document
    └── ../concord-design-v1.0-2025-10-20/
        └── concord_design_document_v2.pdf
```

## 📊 Source Data

### Software Under Test
- **Location**: `/Users/jorgeortiz/SNR/Project Concord/concord-v0.1.0/`
- **Version**: v0.1.0-alpha
- **Date**: October 21, 2025

### Model
- **Name**: Qwen2.5-Coder-3B-Instruct (Q4_K_M)
- **Size**: 2.0 GB
- **Location**: `../models/qwen2.5-coder-3b-instruct-q4_k_m.gguf`
- **Source**: https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF

### Hardware
- **System**: Apple M1 Max, 64 GB RAM
- **OS**: macOS 14.6 (Sequoia)
- **Filesystem**: APFS on NVMe SSD

## 🔄 Reproducibility

```bash
# From this directory
cd ../sdk/examples
./compare_stub_vs_slm.sh
```

**Requirements**:
- Python 3.11+
- llama.cpp v6800
- Qwen2.5-Coder-3B model
- macOS or Linux

## 📦 Files in This Directory

### v0.1.0 - Original Experiments (Plain Directories)

| File | Size | Description |
|------|------|-------------|
| `concord_v0.1.0_results.pdf` | 277 KB | Main experimental report (LaTeX) |
| `concord_v0.1.0_results.tex` | 47 KB | LaTeX source |
| `EXPERIMENT_MANIFEST.md` | 6.9 KB | Traceability document |
| `*.aux, *.log, *.out` | - | LaTeX build artifacts (preserved) |

### v0.2.0 - FUSE Layer Experiments

| File | Size | Description |
|------|------|-------------|
| `concord_v0.2.0_results.pdf` | 160 KB | Main experimental report (LaTeX) ✨ |
| `concord_v0.2.0_results.tex` | 20 KB | LaTeX source ✨ |
| `concord_v0.2.0_results.md` | 15 KB | Markdown version ✨ |
| `concord_v0.2.0_manifest.md` | 11 KB | Traceability document ✨ |
| `FUSE_VS_PLAIN_COMPARISON.md` | 8.9 KB | Performance comparison ✨ |
| `fuse_experiment_results.txt` | 688 B | FUSE benchmark raw data ✨ |
| `plain_stub_results.txt` | 681 B | Plain directories stub data ✨ |
| `plain_slm_results.txt` | 680 B | Plain directories SLM data ✨ |

### General Documentation

| File | Description |
|------|-------------|
| `README.md` | This file - Directory overview |
| `NARRATIVE_ENHANCEMENTS.md` | Writing improvements |
| `FIGURES_ADDED.md` | Figure generation notes |
| `RESULTS_UPDATE.md` | Results update log |

## ✅ Verification

```bash
# Verify PDF integrity
shasum -a 256 concord_v0.1.0_results.pdf
# Expected: a714c57da67a4495ec6277b760ba6b3ab5e83655cde3577da8391ed9c6d77c2d

# Verify LaTeX source
shasum -a 256 concord_v0.1.0_results.tex
# Expected: e5611bcda78a067739d97d9401f783f4cec347a276fc012c78dad88071858d7b
```

## 📚 Related Documents

- `../README.md` - Project overview with result summary
- `../RESULTS.md` - Detailed results with visualizations
- `../SLM_INTEGRATION.md` - SLM integration guide
- `../VERSION` - Software version information
- `../concord-design-v1.0-2025-10-20/` - Design document

## 🆕 FUSE Comparison (October 21, 2025)

The experiments were rerun with **FUSE virtualization enabled** to measure overhead:

| Metric | Plain Directories | FUSE Mount | Overhead |
|--------|------------------|------------|----------|
| Substrate (t0→t1) p50 | 11.122 ms | 19.772 ms | +8.7 ms (+78%) |
| Throughput | 84.4 int/s | 47.0 int/s | -44% |

**Key Finding:** FUSE adds ~8.7ms overhead, but this is still only 8% of model inference time (104ms). The core hypothesis remains validated even with FUSE virtualization.

See `FUSE_VS_PLAIN_COMPARISON.md` for complete analysis.

## 🎯 Next Steps

1. ~~**Rust FUSE layer** (v0.2.0)~~ ✅ **COMPLETED** - Python FUSE layer implemented and tested
2. **FUSE optimization** - Explore async operations and caching
3. **Baseline comparisons** - HTTP, gRPC, Kafka
4. **Multi-agent experiments** - Pipeline coordination
5. **Full evaluation** - Experiments 1-10 from design document

## 📧 Contact

**Jorge Ortiz**  
Rutgers University  
jorge.ortiz@rutgers.edu  

## 📅 Timeline

- **October 21, 2025, 11:34-11:37 AM PDT**: Experiments executed
- **October 21, 2025, 11:45 PM PDT**: LaTeX document compiled
- **October 21, 2025, 11:46 PM PDT**: Manifest finalized with checksums

---

**This directory provides complete documentation and traceability for the Concord v0.1.0 experimental validation.**

