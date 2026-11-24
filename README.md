# vpp-rts

NCKU Real-Time Systems homework — a Virtual Power Plant (VPP) real-time scheduling system that generates a periodic task set, solves a day-ahead MILP schedule, runs an acceptance test for sporadic/aperiodic jobs, and evaluates the result.

## Environment

| Item | Requirement |
|---|---|
| Language | Python 3 (pure Python — no compilation step) |
| Python version | 3.11+ (tested on **3.11.4**, Windows 11). `pyproject.toml` declares `^3.12` for Poetry; with Python 3.11 install via pip instead |
| Runtime packages | `pulp` (tested 3.3.1; `poetry.lock` pins 2.9.0), `pydantic` (tested 2.13.4) |
| Test package | `pytest` (tested 9.0.3) |
| Optional | `matplotlib` — only for the Gantt chart written by the TA checker in `test2/` |
| MILP solver | CBC, bundled with PuLP — nothing extra to install |

## Quick start

Install with pip (or `poetry install` on Python 3.12+):

```bash
pip install "pulp>=2.9" "pydantic>=2.13" pytest
```

All pipeline commands, in the order you'd typically run them:

```bash
python -m src.main                                   # Level 1: generate -> schedule -> evaluate
python -m src.validator                              # Level 1 self-check
python -m src.advanced_scheduler                     # Level 2: dynamic scheduler (reuses existing output/task_set.json)
python -m src.validator --level 2                    # Level 2 self-check
python -c "from src.main import run_level2; run_level2()"  # Level 1 + Level 2 + comparison report, in one go
python -m pytest                                     # tests
python test2/main.py --submission .                  # TA checker (report in test2/reports/)
```

Typical run time on one CPU core: Level 1 ≈ 10–120 s (capped, see [Solver settings](#solver-settings)), Level 2 ≈ 5–20 s.

## Reproducing the submitted output

The periodic task set is random unless a seed is fixed, so to regenerate exactly the submitted `output/*.json`:

1. In `src/config.py`, set `task_seed` to the seed used for the submission (`None` draws a new task set every run).
2. Put the same demo job file at `input/aperiodic_n_sporadic.json` (the file name is set by `demo_jobs_filename` in `src/config.py`).
3. Keep `runtime_config.json` unchanged — its `dynamic.seed` fixes the Level 2 renewable realization.
4. Run:

   ```bash
   python -m src.main                  # task_set / schedule_result / acceptance_test_log / evaluation_results
   python -m src.advanced_scheduler    # *_dynamic.json + dynamic_run_log.json
   ```

CBC runs serially (no `threads` option), so a given model gives the same result on every run. **Caveat:** if a Level 1 solve stops on its 120 s time limit instead of on the gap, the returned solution depends on machine speed. For a bit-exact reproduction on a slower machine, set `l1_time_limit = None` in `src/config.py` (solve to proven optimality; can take 5+ minutes on hard task sets).

## Self-check (Level 1)

`python -m src.validator` validates the generated artifacts against the Level 1 grading rubric (items 1–3). Standard-library only — no Poetry environment required.

Reads `output/task_set.json`, `output/schedule_result.json` and `input/processor_settings.json`, prints a per-item pass/fail report with a self-grade, and exits non-zero on any covered violation.

**Level 2 self-check:** `python -m src.validator --level 2`

Grades the **dynamic** schedule against the full Level 2 rubric: it re-checks every Level 1 item using the *relaxed* storage/renewable constraints, scores item 3 (each relaxed constraint R1–R10, 1 pt, cap 10 — verified by the dynamic schedule actually satisfying it), and item 8-2 (dynamic schedule correctness). It reads `output/schedule_result_dynamic.json`, `output/evaluation_results_dynamic.json`, `runtime_config.json`, and `output/dynamic_run_log.json` (for the realized PV availability and precedence pairs), and prints the static-vs-dynamic comparison for report item 8-3. Report-only sub-items (4-1/4-2, 7-1/7-2 reserve analysis, 8-1, 8-3, and the item-3 modelling write-up) are `SKIP`.

## Pipeline

The full pipeline runs four phases in sequence:

```
Phase 1 — Task Generation
  → output/task_set.json   (periodic tasks + empty sporadic/aperiodic sections)

Phase 2 — Day-Ahead Scheduling (MILP)
  ← input/processor_settings.json
  ← input/price_72hr.json
  ← output/task_set.json          (merged with input/aperiodic_n_sporadic.json)
  → output/schedule_result.json

Phase 3 — Acceptance Test  (integrated into RTScheduler.run())
  ← reserve computed by Phase 2 solver
  ← input/aperiodic_n_sporadic.json  (sporadic / aperiodic demo jobs)
  → output/schedule_result.json  (annotated with rejected_sporadic / missed_aperiodic)
  → output/acceptance_test_log.json  (per-job accept/reject decisions + rationale)

Phase 4 — Evaluation
  ← input/processor_settings.json
  ← input/price_72hr.json
  ← output/task_set.json
  ← output/schedule_result.json
  → output/evaluation_results.json
```

### Phase 1 — Task Generation

Randomly generates 6–10 periodic tasks satisfying all assignment constraints for a 72-unit hyperperiod:

| Constraint | Rule |
|---|---|
| Frame size `f` | `f ≥ max(e)`, `72 % f == 0`, `2f − gcd(f, p) ≤ d` for every task |
| Utilisation | `Σ(e/p) ≥ 0.7` |
| Job count | Instances with release `r + (k−1)·p ≤ 72` (same expansion as the TA checker) `> 30` |
| Tail jobs fit | Every instance released at or before 72 must fit `e` ticks in `[release, min(release + d − 1, 72)]` |
| Energy demand | At least 2 tasks with `w ≥ 14` |

Any candidate that fails a rule is discarded and redrawn (`TaskSetValidator`). The
**tail-jobs** rule follows from Assumption 3 (every job must finish before its deadline
and within t = 72) and from the grader, which counts every instance with release ≤ 72:
an instance released at, e.g., t = 71 with `e = 4` can never be completed by any
scheduler, so such task sets are rejected up front. About two thirds of raw random
draws fail this rule; redrawing takes milliseconds.

Each task has the following fields:

| Field | Meaning |
|---|---|
| `r` | Release time |
| `p` | Period |
| `e` | Execution time (WCET) |
| `d` | Relative deadline |
| `w` | Energy demand (MWh/h) |
| `preempt` | `1` = preemptible, `0` = non-preemptive |

The output `task_set.json` also includes empty `sporadic` and `aperiodic` sections. At runtime, `src/main.py` merges in the demo jobs from `input/aperiodic_n_sporadic.json` (sporadic and aperiodic tasks) before solving Phase 2. To use a different demo job file, change `demo_jobs_filename` in `src/config.py`.

### Phase 2 — Day-Ahead Scheduling

Expands periodic tasks into concrete jobs over the 72-hour horizon and solves a PuLP MILP problem with 23 constraints covering:

- Job execution completeness and ordering
- Generator ramp-up/down, min up/down time, output limits
- Renewable forecast limits
- Storage SOC, charge/discharge limits, no simultaneous charge+discharge
- Energy balance per time step
- Market sell quantity

**Objective:** minimise `α·f1 + f2 + f3`
- `f1` = aperiodic deadline miss count (α = 10,000 $/miss)
- `f2` = Σ (cost\_fixed · min(1, P) + cost\_variable · P) for generators
- `f3` = −Σ (λ_t · Sell_t) (market revenue, negated for minimisation)

### Phase 3 — Acceptance Test

Processes sporadic (hard-deadline) and aperiodic (soft-deadline) jobs using the reserve left by the MILP solver. **Implemented in `AcceptanceTester` and automatically called inside `RTScheduler.run()`.**

| Task type | Rule |
|---|---|
| Sporadic | Hard deadline. Accepted only if it can finish between `r` and `r + d - 1`; otherwise recorded in `rejected_sporadic`. |
| Aperiodic | Soft deadline. Scheduled when enough reserve exists; otherwise recorded in `missed_aperiodic`. |
| `preempt = 1` | May use non-contiguous slots. |
| `preempt = 0` | Must use one contiguous execution window. |

Accepted/scheduled jobs consume reserve by `w` for each of their `e` execution ticks. The demo jobs are loaded from `input/aperiodic_n_sporadic.json` — replace this file with the TA-provided task file before running.

Every decision is written to `output/acceptance_test_log.json`: a `summary` block (accept/reject and scheduled/missed counts, sporadic value rate, leftover reserve per tick) plus per-job records carrying the chosen slots, completion tick, and a human-readable accept/reject rationale — directly supporting rubric items 4-1 (method) and 4-2 (decision rationality).

### Phase 4 — Evaluation

Reads the solved schedule and computes all required performance metrics:

| Metric | Formula |
|---|---|
| `hard_deadline_miss_rate` | missed (periodic + accepted sporadic) / (periodic + accepted sporadic); rejected sporadic jobs are excluded from both |
| `soft_deadline_miss_rate` | missed aperiodic jobs / total |
| `average_tardiness` | avg max(0, C_j − d_j) |
| `max_tardiness` | max max(0, C_j − d_j) |
| `average_response_time` | avg (C_j − r_j) |
| `max_response_time` | max (C_j − r_j) |
| `completion_time_jitter` | mean over periodic tasks of the population std-dev of instance completion times C |

Conventions (same as the TA checker): `C_j` = last executed tick, absolute deadline
`d_j = r_j + d − 1`, a job counts as completed only when it has `e` executed ticks, and
response time is `C_j − r_j` (no `+1`) everywhere, including the validator.
| `sporadic_value_rate` | exec time completed before deadline / total exec time |
| `generator_cost` | f2 from objective |
| `market_revenue` | Σ (λ_t · Sell_t) |
| `objective_value` | α·f1 + f2 − market\_revenue |

## Solver settings

### Level 1: time limit + gap (`src/config.py`)

| Setting | Default | Effect |
|---|---|---|
| `l1_time_limit` | 120 | Max seconds for the Level 1 CBC solve; `None` = prove optimality |
| `l1_gap_rel` | 0.01 | Stop once the relative MIP gap ≤ 1 % |

**Trade-off.** Proving optimality is sometimes very slow even though a near-optimal
schedule is found early. Measured on seeds 1–20 (Python 3.11.4, single core): 17 task
sets were solved to proven optimality in 9–50 s; 3 (seeds 3, 11, 12) still had a 3–4 %
gap after 60 s. Seed 11 needs **290 s** to prove optimality:

| Elapsed | Best objective | Distance to proven optimum (−85,643.6) |
|---|---|---|
| 60 s | −83,897 | 2.0 % |
| 120 s | −85,416 | 0.27 % |
| 217 s | −85,639.6 | 0.005 % |
| 290 s | −85,643.6 | proven optimal |

With the 120 s cap, seed 11 stops at −85,416.2 (0.27 % from the optimum). The cap
only affects **objective quality**: periodic deadlines, energy balance and every other
constraint are hard constraints of the MILP, so any returned solution satisfies them
(rubric 2-x, 3-2, 3-3). When CBC stops on the limit, PuLP still reports status
`Optimal` (a feasible incumbent exists), so the pipeline continues normally. Results
reported for such runs are "best solution within the gap / time limit", not a proven
optimum.

### Level 2: no `threads` option

`AdvancedScheduler` calls CBC without the `threads` option. Passing `-threads N`
(even `N = 1`) switches CBC into its parallel branch-and-bound mode, which deadlocks on
some re-optimization models with PuLP's bundled Windows CBC: the solver stops using
CPU, ignores its time limit and never returns. Without the option CBC solves serially,
which is also deterministic. (The `threads` key in `runtime_config.json` is unused.)

## Level 2 — Relaxed assumptions + advanced dynamic scheduling

Level 2 relaxes three Level 1 assumptions and adds a rolling-horizon dynamic
scheduler. See **`report_level2.md`** for the full write-up (rubric items 3, 8).
The relevant commands are listed in [Quick start](#quick-start) above
(`python -m src.advanced_scheduler` for the dynamic scheduler alone, or the
`run_level2()` one-liner for the full L1 → L2 → comparison pipeline).

> **Demo tip:** for a TA demo with a new `aperiodic_n_sporadic.json`, place the file in
> `input/`, then run `python -m src.main` followed by `python -m src.advanced_scheduler`.
> This avoids re-generating the task set between the two runs.

- **Relaxed assumptions (`src/rt_scheduler/relaxation.py`, `formulator.py`):** renewable
  forecast uncertainty (derated cap), realistic storage (charge/discharge efficiency,
  self-discharge, cycle/throughput limit, SOC-dependent power, aging cost), and job
  precedence. All are expressed with the Level 1 decision variables — **no new
  decision variable is added** — and default to no-ops so the Level 1 schedule is
  unchanged. Parameters live in **`runtime_config.json`**.
- **Advanced dynamic scheduler (`src/advanced_scheduler.py`):** receding-horizon
  re-optimization. It walks the 72-tick horizon, re-solving the remaining horizon at a
  periodic cadence and on events (sporadic arrivals, large renewable deviations). Each
  re-solve pins the executed prefix, reveals realized PV (vs the derated forecast tail)
  and newly arrived sporadic/aperiodic jobs, and admits them by reservation
  feasibility. A MIP gap / time limit keeps each solve tractable.

**Key `runtime_config.json` parameters:**

| Parameter | Default | Effect |
|---|---|---|
| `time_limit` | 10 | Max seconds per CBC solve (lower = faster demo) |
| `gap_rel` | 0.20 | MIP optimality gap tolerance (higher = faster) |
| `max_solves` | 80 | Maximum solve calls across all rounds |
| `reopt_interval` | 24 | Ticks between periodic re-optimizations |
| `renewable_noise_std` | 0.2 | Std dev of PV Gaussian noise |
| `renewable_deviation_threshold` | 0.25 | PV deviation that triggers an extra re-solve |

Level 2 writes `*_dynamic` artifacts alongside the Level 1 outputs:
`output/schedule_result_dynamic.json`, `output/evaluation_results_dynamic.json`,
`output/acceptance_test_log_dynamic.json`, `output/dynamic_run_log.json`.

## Submission

The repository already follows the required `Submission_{GroupID}/` layout
(`README.md`, `report.pdf`, `src/task_generator.py`, `src/scheduler.py`,
`src/evaluator.py`, `src/advanced_scheduler.py`, `input/`, `runtime_config.json`,
`crontab.txt`). **`output/` is git-ignored**, so a fresh clone has no output files:
run the pipeline (see [Reproducing the submitted output](#reproducing-the-submitted-output))
and copy `output/task_set.json`, `schedule_result.json`, `evaluation_results.json` and
`acceptance_test_log.json` (plus the `*_dynamic.json` files for Level 2) into the
submission folder.

Before submitting, run the TA checker from the repository root. The checker is provided by
the TA and is **not included in this repository** (`test2/` is gitignored); place it at
`test2/` locally first:

```bash
python test2/main.py --submission .
```

It re-parses every JSON file, recomputes the metrics, re-checks feasibility, and writes
`test2/reports/{folder}_report.txt` / `.json` (plus charts if `matplotlib` is installed).
`overall_status` is a checker state, not a grade; `manual_review_required` with
"錯誤/違規：0" means no automatic violation was found and only the Level 2 extensions
need a human look.

## Project structure

```
src/
├── main.py                      # Pipeline entry point (run_level2 = L1 + L2 + compare)
├── config.py                    # Centralised paths and constants (task_seed, demo_jobs_filename, l1_time_limit, l1_gap_rel)
├── validator.py                 # Level 1/2 self-check (stdlib only)
├── advanced_scheduler.py        # Level 2: rolling-horizon dynamic scheduler
├── task_generator.py            # Phase 1 entry point (re-exports src/generator; TA-required layout)
├── scheduler.py                 # Phase 2+3 entry point (re-exports src/rt_scheduler; TA-required layout)
├── evaluator.py                 # Phase 4 entry point: Evaluator (performance metrics)
├── generator/                   # Phase 1: task set generation
│   ├── task_set_generator.py
│   ├── frame_size_calculator.py
│   └── task_set_validator.py
├── rt_scheduler/                # Phase 2 + 3: MILP scheduler + acceptance test
│   ├── rt_scheduler.py          # Orchestrator (calls AcceptanceTester at end)
│   ├── acceptance_tester.py     # Sporadic/aperiodic scheduling on reserve
│   ├── relaxation.py            # Level 2: RelaxationConfig (relaxed-assumption params)
│   ├── expander.py              # Expands tasks → concrete jobs
│   ├── formulator.py            # Builds PuLP problem (23 constraints + L2 relaxations)
│   └── extractor.py             # Parses solved variables → JSON + reserve
├── model/                       # Pydantic data models
│   ├── base/base_model.py
│   ├── asset/                   # ProcessorSettingsSystem, Generator, Storage, Renewable, ChargingJob
│   ├── task/                    # rt_task.py (PeriodicTask, SporadicTask, AperiodicTask), ExpandedJob, TaskSystem
│   └── market/                  # price.py (PriceSystem, PriceRecord)
└── utils/
    └── file_io.py               # JsonIO.load() / JsonIO.save()

input/
├── processor_settings.json      # VPP asset configuration (generators, storage, renewables)
├── price_72hr.json              # 72-hour market price forecast
├── aperiodic_n_sporadic.json    # Demo sporadic/aperiodic jobs (replace with TA-provided file)
├── aperiodic_n_sporadic_5s9a.json  # Larger demo set: 5 sporadic + 9 aperiodic (set demo_jobs_filename to use it)
└── demo_jobs.json               # Alternative demo job set (set demo_jobs_filename in config.py)

test/                            # pytest suite (generator/, model/, rt_scheduler/, evaluator/, Level 2)
test2/                           # TA-provided checker (not in repo, gitignored): python test2/main.py --submission .

references/
├── hw_illustration.md           # Assignment description (Markdown)
└── hw_illustration.pdf          # Assignment description (PDF)

runtime_config.json              # Level 2 relaxation + dynamic-cadence parameters

output/                          # git-ignored, generated at runtime
├── task_set.json
├── schedule_result.json                 # Level 1 static schedule
├── acceptance_test_log.json
├── evaluation_results.json
├── schedule_result_dynamic.json         # Level 2 dynamic schedule
├── acceptance_test_log_dynamic.json
├── dynamic_run_log.json                 # per-round re-optimization log
└── evaluation_results_dynamic.json
```
