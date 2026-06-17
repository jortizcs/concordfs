# Figures Added to Concord v0.1.0 Results Document

**Date**: October 21, 2025  
**Document**: `concord_v0.1.0_results.pdf`  
**Total Figures Added**: 6 new figures

---

## Summary

The updated results document now contains **6 new TikZ/PGFPlots figures** that visualize the multi-agent coordination experiment results. The document grew from 10 pages to 14 pages, with the new figures distributed throughout Section 7 (Multi-Agent Coordination Experiment).

---

## Figures Added

### Figure 3: Filesystem Layout
**Location**: Section 7.1 (System Architecture)  
**Type**: TikZ diagram  
**Purpose**: Shows the directory structure for multi-agent coordination

**What it shows:**
- `/tmp/concord/` with subdirectories for each agent (code, test, release)
- Each agent has `inbox/*.json` and `outbox/events.jsonl`
- Policy files (`policy/no_network`)
- Orchestrator plan directory (`_orchestrator/plan/`)
- CAS bus (`/tmp/bus/sha256/`)

**Significance**: Demonstrates that all coordination state is filesystem-visible and inspectable with standard POSIX tools.

---

### Figure 4: Multi-Agent Pipeline Flow
**Location**: Section 7.2 (Experimental Workload)  
**Type**: TikZ flow diagram  
**Purpose**: Illustrates the coordination flow between orchestrator and agents

**What it shows:**
- Orchestrator submitting intents to agents
- Agents processing intents (steps 1-4)
- Agents emitting events back to orchestrator
- Artifact passing via CAS (Step 1)

**Significance**: Visualizes how the declarative plan is executed through filesystem operations (intent writes, event appends).

---

### Figure 5: Latency Comparison Bar Chart
**Location**: Section 7.3 (Results)  
**Type**: PGFPlots bar chart  
**Purpose**: Compares intent→event latency between polling and file notifications

**What it shows:**
- **Polling**: 12.0 ms (p50)
- **inotify/fsevents**: 1.2 ms (p50)
- **Improvement**: 10× reduction

**Significance**: Validates the Section 4 projection that file notifications would eliminate the polling bottleneck.

---

### Figure 6: Pipeline Execution Timeline
**Location**: Section 7.3 (Results)  
**Type**: TikZ timeline  
**Purpose**: Shows temporal execution of the 4-step pipeline

**What it shows:**
- Step 1 (propose_patch): 0-80 ms
- Step 2 (run_tests): 80-150 ms
- Step 3 (apply_patch): 150-240 ms
- Step 4 (publish_release): 240-320 ms
- Handoff points (dashed red lines)

**Significance**: Demonstrates that the pipeline completes in 320 ms with clearly visible handoff latencies.

---

### Figure 7: Substrate vs Agent Work (Percentage)
**Location**: Section 7.6 (Comparison to Single-Agent Results)  
**Type**: PGFPlots grouped bar chart  
**Purpose**: Shows substrate overhead as percentage of total time across experiments

**What it shows:**
- **Single-Agent (polling, no model)**: 100% substrate, 0% agent work
- **Single-Agent (SLM)**: 9% substrate, 91% agent work
- **Multi-Agent (inotify)**: 2% substrate, 98% agent work

**Significance**: Illustrates the dramatic reduction in substrate overhead achieved by file notifications, validating the core hypothesis that coordination is negligible compared to agent work.

---

### Figure 8: Atomic Rename and Tombstone Mechanism
**Location**: Section 7.5.2 (Atomic Rename Semantics)  
**Type**: TikZ state diagram  
**Purpose**: Explains the exactly-once processing mechanism

**What it shows:**
- **State 1**: `.tmp-<id>.json` (invisible to agents)
- **State 2**: `<id>.json` (visible after atomic rename)
- **State 3**: `<id>.json.done` (tombstone prevents reprocessing)

**Significance**: Visualizes the key semantic guarantee (exactly-once processing) that Concord provides through POSIX rename atomicity.

---

## Technical Details

### Tools Used
- **TikZ**: For diagrams, state machines, timelines
- **PGFPlots**: For bar charts
- **TikZ Libraries**: shapes, arrows, positioning, fit, backgrounds

### Challenges Resolved

1. **Style Name Conflict**: TikZ has a built-in `step` key, so renamed pipeline step style to `pstep`
2. **Filesystem Tree Complexity**: Simplified from hierarchical tree to flat layout for clarity
3. **Legend with Math Symbols**: Removed `$\to$` from legend to avoid pgfplots parse errors
4. **macOS Path Issues**: Used `\textless` and `\textgreater` for angle brackets in file names

---

## Impact on Document

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| **Total Pages** | 10 | 14 | +4 pages |
| **File Size** | 228 KB | 258 KB | +30 KB |
| **Figures** | 1 (timeline) | 7 | +6 figures |
| **Visual Explanations** | Text-only | Diagrams + charts | Significantly improved |

---

## Figure References in Text

All figures are properly referenced in the text:
- `\ref{fig:filesystem}` - Filesystem layout
- `\ref{fig:pipeline}` - Pipeline flow
- `\ref{fig:latency-comparison}` - Latency improvement
- `\ref{fig:timeline}` - Execution timeline
- `\ref{fig:substrate-overhead}` - Substrate percentage
- `\ref{fig:tombstone}` - Atomicity mechanism

---

## Readability Improvements

The figures significantly improve the document's readability by:

1. **Visual Architecture**: Readers can see the filesystem layout at a glance
2. **Quantitative Comparisons**: Bar charts make latency improvements immediately obvious
3. **Process Flow**: Diagrams clarify how intents and events flow through the system
4. **Temporal Understanding**: Timeline shows concurrent vs sequential execution
5. **Semantic Clarity**: State diagram explains exactly-once processing visually

---

## Next Steps (Optional)

Potential additional figures for future versions:
1. **Multi-step dependency graph** showing which steps can run in parallel
2. **CAS reference resolution** diagram showing template substitution
3. **Policy enforcement** flowchart showing decision points
4. **Comparison with AutoGen/CrewAI** side-by-side architecture diagrams
5. **Scale testing results** showing throughput vs number of agents

---

**Document Version**: v0.1.0 (October 21, 2025)  
**Compilation**: Successful (pdflatex, 2 passes)  
**Output**: 14 pages, 258 KB

