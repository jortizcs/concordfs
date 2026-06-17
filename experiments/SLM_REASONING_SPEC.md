# MASTER PROMPT — Concord Reasoning A/B over Building Simulators

## 0) Objective (what we must prove)

We aim to demonstrate **specific reasoning wins** for small LLMs (SLMs) coordinating multi-agent tasks when the agent interface is a **mounted, typed filesystem** (ConcordFS) versus **ad-hoc APIs/docs**. We assume the systems result is settled (ConcordFS coordination overhead ≈ gRPC; low tail latency). The experiments isolate **LLM reasoning benefits**: fewer schema/policy mistakes, fewer tokens, faster first valid actions, better zero-shot discovery.

## 1) Hypotheses (explicit, testable)

* **H-R1 (Correctness):** Over identical tasks and models, **FS condition** (mounted `caps/`, `policy/`, `inbox/`, `outbox/`) yields **higher plan success** and **fewer schema/policy errors** than **API condition** (OpenAPI docs; no mounts).
* **H-R2 (Efficiency):** FS condition yields **lower time-to-first-valid-intent** and **fewer prompt tokens** than API condition.
* **H-R3 (Generalization):** On zero-shot addition of a new room/building mount, the FS condition achieves **faster discovery and first valid use** without prompt edits; API needs doc updates.
* **H-S (Sanity, adjunct):** Intent→event p95 latency and MTTR under injected adapter crash are comparable across FS/API (systems non-issue).

## 2) Simulation environments (choose now)

* **BOPTEST** (Docker) for **T1–T3**: zone-level HVAC/comfort + (if needed) synthetic CO₂.

  * Select test case: `<<CASE_BOPTEST>>` (e.g., multi-zone residential/office).
* **CityLearn** (pip/conda) for **T4**: multi-building electricity and DR.

## 3) Mount contract (LLM-legible)

For each zone/building mount:

```
/house|/campus/<node>/
  caps/manifest.json      # sensors/actions schema (types, units, file paths)
  policy/*                # constraints (e.g., no_window, max_tokens, latency_ms, quiet_hours)
  fs/                     # time series (co2.csv, rh.csv, temp.csv, occ.jsonl, load.csv, ...)
  inbox/                  # write intents as JSON files (atomic rename commit)
  outbox/events.jsonl     # NDJSON event log (append-only)
```

### `caps/manifest.json` template

```json
{
  "agent": "<node-id>",
  "sensors": [
    {"name":"co2","unit":"ppm","read":"fs/co2.csv","agg":"mean_10m"},
    {"name":"rh","unit":"%","read":"fs/rh.csv","agg":"max_10m"},
    {"name":"temp","unit":"C","read":"fs/temp.csv"},
    {"name":"occ","unit":"bool","read":"fs/occ.jsonl"}
  ],
  "actions": [
    {"name":"set_hvac","args":{"sp_c":"number"}},
    {"name":"fan_on","args":{"duration_s":"integer"}},
    {"name":"open_window","args":{"duration_s":"integer"}}
  ]
}
```

### Intent file schema (FS condition)

Filename: `/.../inbox/<id>.json` (created via write→fsync→atomic rename)
Body (example):

```json
{"op":"set_hvac","sp_c":22.0,"id":"<uuid>","deadline_ms":1500}
```

### Event line schema

File: `/.../outbox/events.jsonl` (append-only; one JSON per line)

```json
{"ts":"<iso>","event":"ack","id":"<uuid>","op":"set_hvac","ok":true,"engine":"phi3-mini-q4","tokens":128}
```

## 4) Baseline (API/docs condition)

Provide only **OpenAPI** specs (or equivalent text) for each node; no mounts. The coordinator must choose endpoints/args and produce **HTTP payloads** that a local stub executes. The stubs apply the same simulator transitions as FS adapters.

## 5) Adapters (build two per simulator)

* **Sim→FS**: poll/step the simulator; append CSV/JSONL time series to `/fs/*` per node; write optional labels to `/fs/labels/events.jsonl`.
* **FS→Sim**: watch `/inbox/*.json` (inotify/fsevents); validate against `policy/*`; call simulator actuator API; append `ack` to `outbox/events.jsonl`. Enforce rename+tombstone and exactly-once semantics.

(For API condition: a **Sim↔API stub** that maps the same intents/results to HTTP endpoints.)

## 6) Tasks (run 20–30 randomized episodes per task)

**T1 — CO₂ mitigation (zone-local; BOPTEST)**
If `mean_10m(co2) > 1000 ppm` and `occ==1`, choose `set_hvac` or (if allowed) `open_window` to bring CO₂ < 900 ppm within 10 minutes. Respect `policy/no_window`.

**T2 — Humidity response (bath/kitchen; BOPTEST)**
If `rh > 70%` and "shower|cooking plausible", `fan_on(600)`; reduce `rh` below 60% within 10 minutes; do not act in other zones.

**T3 — Night mode (cross-room; BOPTEST)**
After 22:00, if `family` unoccupied for 15 minutes, enforce `set_hvac(sp_c ≤ 20)` and `lights("off")`.

**T4 — Energy spike triage (building-level; CityLearn)**
Identify 5–7 pm load spike; propose 2 actions (e.g., HVAC setpoint + storage dispatch) that reduce load ≥ `<<X%>>` while maintaining comfort/policy.

**T5 — Zero-shot expansion**
Mid-episode, mount `/house/bedroom/` (or `/campus/new_bldg/`) with its own `caps/`/`policy/`; measure time to first valid action **without prompt edits** (FS), compared to API where docs must be injected.

## 7) Coordinator SLM (controller) — prompt scaffolds

### FS condition — **read→plan→write→tail**

**System prompt (fixed):**
"You are a planning agent coordinating room/building agents exposed as mounted directories. **Only** interact by: (1) listing directories; (2) reading JSON under `caps/` and `policy/`; (3) proposing a **JSON plan** of file writes to `*/inbox/*.json`; (4) waiting for acks by tailing `*/outbox/events.jsonl`. Do not invent paths or actions not listed in `caps/manifest.json`. Respect `policy/*`."

**Required output shape:**

```json
{"plan":[
  {"write":"/house/kitchen/inbox/001.json","body":{"op":"read_sensors","window_min":10}},
  {"write":"/house/kitchen/inbox/002.json","body":{"op":"set_hvac","sp_c":22.0}}
], "rationale":"<1-2 lines respecting policies>"}
```

### API condition — **docs→calls**

**System prompt (fixed):**
"You coordinate via HTTP endpoints described by the provided OpenAPI specs. **Output only** a JSON plan of HTTP calls; do not write files."

**Required output shape:**

```json
{"plan":[
  {"POST":"http://kitchen.local/act/set_hvac","json":{"sp_c":22.0}},
  {"POST":"http://kitchen.local/act/fan_on","json":{"duration_s":600}}
]}
```

(Implement a tiny executor that performs either file writes (FS) or HTTP calls (API) and streams acks.)

## 8) Runs & seeds

* For each task T1–T4: **N=20–30** episodes per condition (FS/API) with distinct random seeds for the simulator.
* T5: N=10 zero-shot episodes.
* Fix model, temperature, and budgets across conditions (`controller` SLM 3–4B; optional `doer` 7–8B off for this A/B).
* Log everything to `runs/<task>/<condition>/<seed>/*`.

## 9) Metrics (log exactly these; compute per task & overall)

**Reasoning (primary)**

* **Plan success** (%): achieved goal within SLO and without policy violation.
* **Schema errors** (%): malformed intents (FS) or invalid HTTP body/args (API).
* **Policy violations** (%): attempts blocked by `policy/*`.
* **Time-to-first-valid-intent** (s).
* **Prompt tokens** (per step & total).
* **Retries** (# tool-selection attempts / re-plans).
* **Zero-shot discovery time** (s) to first valid use of new mount (T5).

**Adjunct systems (sanity)**

* **Intent→event latency** p50/p95 (s).
* **Handover latency** p50 (multi-step plans).
* **MTTR** (s) after injected adapter crash (restart adapter and measure recovery to next ack).

**Logging contract**

* Each event line must include: `{"ts","event","id","op","ok","engine","tokens","lat_us"}`.
* Orchestrator logs: per-step tokens; timestamps at publish (t0), pick-up (t1), first event (t2), step done (t3).

## 10) Analysis & statistics

* For proportions (success, errors, violations): Wilson 95% CIs; compare FS vs API with Fisher exact or two-proportion z test; report absolute and relative deltas.
* For times/tokens: median + [p25, p75]; paired Wilcoxon across matched seeds.
* **Report effect sizes**: e.g., "schema errors −47% [−31, −61]; tokens −28% [−18, −36]; time-to-first-intent −41% [−24, −55]".

## 11) Ablations (to show **why** FS helps)

* **A-TypesOff:** remove `args` types from `caps/manifest.json` → expect schema errors to rise, larger FS–API gap.
* **A-Ambiguity:** add confusing actions (`set_hvac_temp` vs `set_temperature`) → FS gap widens.
* **A-NoPolicy:** hide `policy/*` → more violations; FS still faster to first intent via directory discovery.
* **A-MissingData:** randomly drop 10% sensor samples → robustness check.

## 12) Success thresholds (pre-commit)

We consider H-R1/H-R2/H-R3 supported if, over all tasks:

* **FS** improves **schema error rate** by **≥30%** relative and **policy violations** to **near 0** (≤2% attempts).
* **FS** reduces **time-to-first-valid-intent** by **≥25%** and **total tokens** by **≥20%**.
* **Zero-shot**: median discovery time ≤ half the API condition.
* Adjunct: **intent→event p95** within ±20% of API; **MTTR ≤ 1 s** with tombstones/leases.

## 13) Deliverables to produce

* **Raw logs** in `runs/*`.
* **Four figures** (per task and overall):

  1. Success rates (with CIs);
  2. Schema/policy error bars;
  3. Time-to-first-valid-intent & tokens;
  4. Intent→event CDF + MTTR box plot (inset).
* **One-paragraph result** per hypothesis and a 6-line abstract summarizing deltas.

## 14) Build checklist (do not proceed unless ✅)

* ✅ BOPTEST test case `<<CASE_BOPTEST>>` up; CityLearn district `<<CASE_CITYLEARN>>` up.
* ✅ Sim→FS and FS→Sim adapters running; API stubs mirror same side-effects.
* ✅ Mounts created per node with `caps/` and `policy/` present; simulator writing `/fs/*`.
* ✅ Orchestrator harness can run **FS** and **API** conditions with the same SLM and record metrics.
* ✅ Unit tests: rename atomicity (no partials), tombstones (exactly-once), event append ordering, adapter crash/restart resilience.

---

## 15) Quick run commands (example skeleton)

```bash
# (A) BOPTEST
docker compose -f boptest/docker-compose.yml up -d
python adapters/boptest_to_fs.py --zones Z1 Z2 Z3
python adapters/fs_to_boptest.py --zones Z1 Z2 Z3

# (B) CityLearn
python adapters/citylearn_to_fs.py --bldgs B1 B2 B3
python adapters/fs_to_citylearn.py --bldgs B1 B2 B3

# (C) Orchestrator A/B
python coord/run_house_ab.py --task T1 --condition FS  --seeds 20
python coord/run_house_ab.py --task T1 --condition API --seeds 20
# repeat for T2..T4; run T5 zero-shot episodes

# (D) Analysis
python analysis/summarize.py runs/ --out figs/
```

---

## 16) Notes for implementers

* Keep SLM outputs **strict JSON**; use function-calling or constrained decoding.
* Enforce FS semantics: write→fsync→**rename** to publish; append with `O_APPEND`; on consume, rename to `.done`.
* Use **inotify/fsevents** (no polling); record t0–t3 timestamps.
* In API condition, the harness must **not** peek into `caps/`/`policy/`; pass only docs and hostnames to the model.

---

**End of specification.**

