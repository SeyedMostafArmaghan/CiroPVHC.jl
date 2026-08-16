#!/usr/bin/env python3
"""Deterministically reconcile the bounded runtime benchmark with production timing."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from decimal import Decimal, getcontext
from pathlib import Path


getcontext().prec = 40

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent
PRODUCTION = ROOT / "results/dso_vpp_ac_map_pilot/production_probe"
EXPECTED_HEAD = "29e20ac5115806738c47b587c795c422a1297eee"
EXPECTED_BRANCH = "codex/dso-vpp-ac-map-pilot"
PHASE_B_N = Decimal("3691")
PHASE_B_T = Decimal("15.3498603")
PRODUCTION_LOGICAL_N = Decimal("87229")
PRODUCTION_ACTUAL_N = Decimal("87372")
PRODUCTION_T = Decimal("54.581000089645386")
BENCHMARK_SETUP_SECONDS = Decimal("22.3828378")
BENCHMARK_MEDIAN_SECONDS = Decimal("0.0000659")
BENCHMARK_MEAN_SECONDS = Decimal("0.0000758133333333")
PROJECTION_COUNTS = (1_000, 5_000, 10_000, 50_000, 100_000)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def quantile(sorted_values: list[float], probability: float) -> float:
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] + (position - lower) * (
        sorted_values[upper] - sorted_values[lower]
    )


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def assert_repository_state() -> None:
    if git("branch", "--show-current") != EXPECTED_BRANCH:
        raise RuntimeError("unexpected branch")
    if git("rev-parse", "HEAD") != EXPECTED_HEAD:
        raise RuntimeError("unexpected HEAD")
    if git("rev-list", "--left-right", "--count", f"HEAD...origin/{EXPECTED_BRANCH}") != "0\t0":
        raise RuntimeError("unexpected remote divergence")
    if git("diff", "--cached", "--name-only"):
        raise RuntimeError("staged changes are forbidden")


def reconstruct_production() -> tuple[dict[str, object], list[dict[str, object]]]:
    attempts_path = PRODUCTION / "evaluation_attempts.csv"
    status_counts: Counter[str] = Counter()
    search_kind_counts: Counter[str] = Counter()
    attempt_index_counts: Counter[str] = Counter()
    status_runtime_ms: dict[str, Decimal] = defaultdict(Decimal)
    runtimes: list[float] = []
    runtime_sum_ms = Decimal(0)
    with attempts_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            status_counts[row["solver_status"]] += 1
            search_kind_counts[row["search_kind"]] += 1
            attempt_index_counts[row["attempt_index"]] += 1
            runtime = Decimal(row["runtime_ms"])
            status_runtime_ms[row["solver_status"]] += runtime
            runtime_sum_ms += runtime
            runtimes.append(float(runtime))
    runtimes.sort()

    timestamp_rows = read_csv(PRODUCTION / "timestamp_runtime_evaluation_summary.csv")
    timestamp_runtime_sum = sum(Decimal(row["runtime_seconds"]) for row in timestamp_rows)
    timestamp_logical_sum = sum(Decimal(row["logical_evaluations"]) for row in timestamp_rows)
    timestamp_actual_sum = sum(Decimal(row["actual_evaluations"]) for row in timestamp_rows)

    first_attempts = attempt_index_counts["1"]
    retries = attempt_index_counts["2"]
    converged_accepted = (
        status_counts["CONVERGED_FEASIBLE"] + status_counts["CONVERGED_INFEASIBLE"]
    )
    nonconverged = (
        status_counts["NONCONVERGED_FIRST_ATTEMPT"]
        + status_counts["NONCONVERGED_AFTER_RETRY"]
    )
    if not (
        first_attempts == 87_229
        and retries == 143
        and len(runtimes) == 87_372
        and converged_accepted == 87_086
        and nonconverged == 286
        and timestamp_logical_sum == PRODUCTION_LOGICAL_N
        and timestamp_actual_sum == PRODUCTION_ACTUAL_N
    ):
        raise RuntimeError("authoritative production count reconciliation failed")

    affine_c_seconds = (PRODUCTION_T - PHASE_B_T) / (PRODUCTION_LOGICAL_N - PHASE_B_N)
    affine_fixed_seconds = PHASE_B_T - affine_c_seconds * PHASE_B_N
    production_logical_ms = Decimal(1000) * PRODUCTION_T / PRODUCTION_LOGICAL_N
    production_actual_ms = Decimal(1000) * PRODUCTION_T / PRODUCTION_ACTUAL_N
    timestamp_actual_ms = Decimal(1000) * timestamp_runtime_sum / PRODUCTION_ACTUAL_N
    stage0_mean_ms = runtime_sum_ms / PRODUCTION_ACTUAL_N
    stage0_seconds = runtime_sum_ms / Decimal(1000)
    timestamp_remainder = timestamp_runtime_sum - stage0_seconds
    run_remainder = PRODUCTION_T - timestamp_runtime_sum

    summary: dict[str, object] = {
        "actual_ac_attempts": len(runtimes),
        "logical_evaluations_first_attempts": first_attempts,
        "retry_attempts": retries,
        "stored_evaluation_attempt_rows": len(runtimes),
        "converged_attempts_added_to_accepted_neighbors": converged_accepted,
        "nonconverged_attempt_rows": nonconverged,
        "status_counts": dict(sorted(status_counts.items())),
        "search_kind_attempt_counts": dict(sorted(search_kind_counts.items())),
        "axis_searches": 128,
        "center_search_units": 32,
        "base_ray_searches": 1152,
        "adaptive_ray_searches": 482,
        "all_ray_searches": 1634,
        "boundary_searches_axis_plus_ray": 1762,
        "all_search_units_axis_center_ray": 1794,
        "production_wall_seconds": float(PRODUCTION_T),
        "timestamp_runtime_sum_seconds": float(timestamp_runtime_sum),
        "timestamp_count": len(timestamp_rows),
        "stage0_runtime_sum_seconds": float(stage0_seconds),
        "stage0_runtime_ms": {
            "min": min(runtimes),
            "q1": quantile(runtimes, 0.25),
            "median": quantile(runtimes, 0.50),
            "q3": quantile(runtimes, 0.75),
            "max": max(runtimes),
            "mean": float(stage0_mean_ms),
        },
        "two_point_affine_fit": {
            "equation": "T = F + cN",
            "phase_b": {"N": int(PHASE_B_N), "T_seconds": float(PHASE_B_T)},
            "production": {"N_logical": int(PRODUCTION_LOGICAL_N), "T_seconds": float(PRODUCTION_T)},
            "delta_N": int(PRODUCTION_LOGICAL_N - PHASE_B_N),
            "delta_T_seconds": float(PRODUCTION_T - PHASE_B_T),
            "c_seconds_per_logical_evaluation": float(affine_c_seconds),
            "c_ms_per_logical_evaluation": float(Decimal(1000) * affine_c_seconds),
            "F_seconds": float(affine_fixed_seconds),
            "evidence_limit": "DESCRIPTIVE_TWO_POINT_FIT_WITH_NON_EQUIVALENT_SCOPES_AND_WORKLOADS",
        },
        "aggregate_rates_ms": {
            "production_per_logical_evaluation": float(production_logical_ms),
            "production_per_actual_attempt": float(production_actual_ms),
            "timestamp_sum_per_actual_attempt": float(timestamp_actual_ms),
            "stage0_internal_per_actual_attempt_mean": float(stage0_mean_ms),
        },
        "broad_layer_reconciliation_seconds": {
            "stage0_evaluate_point_internal_sum": float(stage0_seconds),
            "timestamp_scope_minus_stage0_sum": float(timestamp_remainder),
            "run_scope_minus_timestamp_sum": float(run_remainder),
            "sum": float(stage0_seconds + timestamp_remainder + run_remainder),
        },
        "retry_runtime_seconds": {
            "nonconverged_first_attempts": float(status_runtime_ms["NONCONVERGED_FIRST_ATTEMPT"] / Decimal(1000)),
            "retry_attempts": float(status_runtime_ms["NONCONVERGED_AFTER_RETRY"] / Decimal(1000)),
            "all_nonconverged_attempts": float(
                (status_runtime_ms["NONCONVERGED_FIRST_ATTEMPT"]
                 + status_runtime_ms["NONCONVERGED_AFTER_RETRY"]) / Decimal(1000)
            ),
        },
    }

    rows: list[dict[str, object]] = [
        {
            "record_type": "AGGREGATE", "timestamp": "ALL",
            "metric": "PHASE_B_ORCHESTRATION", "count_semantics": "EVALUATIONS",
            "count": int(PHASE_B_N), "wall_seconds": decimal_text(PHASE_B_T),
            "ms_per_count": decimal_text(Decimal(1000) * PHASE_B_T / PHASE_B_N),
            "evidence": "MEASURED", "notes": "Different positive-axis workload; includes row construction; excludes artifact I/O",
        },
        {
            "record_type": "AFFINE_MODEL", "timestamp": "ALL",
            "metric": "T_EQUALS_F_PLUS_C_N_SLOPE", "count_semantics": "LOGICAL_EVALUATIONS",
            "count": int(PRODUCTION_LOGICAL_N - PHASE_B_N),
            "wall_seconds": decimal_text(PRODUCTION_T - PHASE_B_T),
            "ms_per_count": decimal_text(Decimal(1000) * affine_c_seconds),
            "evidence": "DERIVED_TWO_POINT", "notes": f"F={decimal_text(affine_fixed_seconds)} s; descriptive, underdetermined, non-equivalent scopes",
        },
        {
            "record_type": "AGGREGATE", "timestamp": "ALL",
            "metric": "PRODUCTION_FULL_RUN_LOGICAL", "count_semantics": "LOGICAL_FIRST_ATTEMPTS",
            "count": int(PRODUCTION_LOGICAL_N), "wall_seconds": decimal_text(PRODUCTION_T),
            "ms_per_count": decimal_text(production_logical_ms),
            "evidence": "MEASURED_WALL_DERIVED_RATE", "notes": "Includes production preflight, search orchestration, retries, and checkpoints; excludes final write_outputs",
        },
        {
            "record_type": "AGGREGATE", "timestamp": "ALL",
            "metric": "PRODUCTION_FULL_RUN_ACTUAL", "count_semantics": "ACTUAL_AC_ATTEMPTS",
            "count": int(PRODUCTION_ACTUAL_N), "wall_seconds": decimal_text(PRODUCTION_T),
            "ms_per_count": decimal_text(production_actual_ms),
            "evidence": "MEASURED_WALL_DERIVED_RATE", "notes": "87,229 first attempts plus 143 retries",
        },
        {
            "record_type": "AGGREGATE", "timestamp": "ALL",
            "metric": "PRODUCTION_TIMESTAMP_SCOPE_SUM", "count_semantics": "ACTUAL_AC_ATTEMPTS",
            "count": int(PRODUCTION_ACTUAL_N), "wall_seconds": decimal_text(timestamp_runtime_sum),
            "ms_per_count": decimal_text(timestamp_actual_ms),
            "evidence": "DERIVED_SUM_OF_32_MEASURED_TIMESTAMP_RUNTIMES", "notes": "Includes within-timestamp search orchestration and current checkpoints",
        },
        {
            "record_type": "AGGREGATE", "timestamp": "ALL",
            "metric": "STAGE0_EVALUATE_POINT_INTERNAL_SUM", "count_semantics": "ACTUAL_AC_ATTEMPTS",
            "count": int(PRODUCTION_ACTUAL_N), "wall_seconds": decimal_text(stage0_seconds),
            "ms_per_count": decimal_text(stage0_mean_ms),
            "evidence": "DERIVED_SUM_OF_STORED_RUNTIME_MS", "notes": f"median={quantile(runtimes, 0.5):.12g} ms; includes 286 expensive nonconverged attempts",
        },
        {
            "record_type": "REMAINDER", "timestamp": "ALL",
            "metric": "TIMESTAMP_SCOPE_MINUS_STAGE0_INTERNAL", "count_semantics": "ACTUAL_AC_ATTEMPTS_AMORTIZED",
            "count": int(PRODUCTION_ACTUAL_N), "wall_seconds": decimal_text(timestamp_remainder),
            "ms_per_count": decimal_text(Decimal(1000) * timestamp_remainder / PRODUCTION_ACTUAL_N),
            "evidence": "DERIVED_REMAINDER", "notes": "Search orchestration, wrapper work outside Stage0 internal timer, in-memory structures, and within-timestamp checkpoint I/O; not separately identifiable",
        },
        {
            "record_type": "REMAINDER", "timestamp": "ALL",
            "metric": "FULL_RUN_MINUS_TIMESTAMP_SCOPE", "count_semantics": "ACTUAL_AC_ATTEMPTS_AMORTIZED",
            "count": int(PRODUCTION_ACTUAL_N), "wall_seconds": decimal_text(run_remainder),
            "ms_per_count": decimal_text(Decimal(1000) * run_remainder / PRODUCTION_ACTUAL_N),
            "evidence": "DERIVED_REMAINDER", "notes": "Preflight/profile setup, between-timestamp completion checkpoint work, logging, and other run-scope gaps; not pure fixed startup",
        },
    ]
    for row in timestamp_rows:
        rows.append({
            "record_type": "TIMESTAMP", "timestamp": row["timestamp"],
            "metric": "TIMESTAMP_RUNTIME", "count_semantics": "ACTUAL_AC_ATTEMPTS",
            "count": int(row["actual_evaluations"]), "wall_seconds": row["runtime_seconds"],
            "ms_per_count": decimal_text(
                Decimal(1000) * Decimal(row["runtime_seconds"]) / Decimal(row["actual_evaluations"])
            ),
            "evidence": "MEASURED", "notes": f"selection_index={row['selection_index']};logical={row['logical_evaluations']};retries={row['retry_count']}",
        })
    return summary, rows


def timer_inventory() -> list[dict[str, object]]:
    return [
        {"operation": "coordinate assignment", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "benchmark:505-512;production:285-288", "detail": "Scalar P13/P30 argument access and Float64 normalization are inside; geometric point selection/derivation happened earlier."},
        {"operation": "physical-injection assembly", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "stage0:308-318", "detail": "Allocates injection and net-demand arrays per call."},
        {"operation": "network state preparation", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "stage0:310-317", "detail": "Per-call assembled inputs are inside; static network construction and profile loading are outside the benchmark point timer."},
        {"operation": "radial AC power-flow solve", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "stage0:320-332", "detail": "Primary flat-start radial BFS."},
        {"operation": "replay_s1b_interval", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "stage0:334-360", "detail": "Independent replay and residual solution path."},
        {"operation": "voltage-limit classification", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "stage0:369-375;production:296", "detail": "Stage0 classification and production attempt_class both occur before evaluate_physical! returns."},
        {"operation": "primary binding classification", "benchmark_timer_scope": "OUTSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "benchmark:512-531;production:534-536,747-749", "detail": "Benchmark binding_mechanism is computed after the point timer; production search-level binding analysis remains inside the full run timer."},
        {"operation": "evaluation ID allocation", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "production:287-288,303", "detail": "Logical and attempt counters mutate inside evaluate_physical!."},
        {"operation": "attempt-row construction", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "production:250-279,299-303", "detail": "In-memory NamedTuple construction and push are included."},
        {"operation": "provenance capture", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "production:253-278", "detail": "Per-attempt timestamp/search/phase/initialization provenance fields are captured inside; file hashing is outside."},
        {"operation": "neighbor/warm-start state update", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "production:304-309,321-350", "detail": "Accepted-neighbor voltage copy/push is included; nearest-neighbor search occurs only after first-attempt nonconvergence."},
        {"operation": "accepted-endpoint storage", "benchmark_timer_scope": "INSIDE_TIMER", "production_full_run_scope": "INSIDE_TIMER", "evidence": "production:304-309;471-560;698-763", "detail": "Numerically accepted neighbor storage is inside the point timer; production safe/violating search-vector storage is outside the point wrapper but inside the production run."},
        {"operation": "re-entry bookkeeping", "benchmark_timer_scope": "NOT_APPLICABLE", "production_full_run_scope": "INSIDE_TIMER", "evidence": "production:399-410,510-512,723-725", "detail": "The bounded benchmark does not run a ray/axis sweep."},
        {"operation": "adaptive-trigger bookkeeping", "benchmark_timer_scope": "NOT_APPLICABLE", "production_full_run_scope": "INSIDE_TIMER", "evidence": "production:784-801,1444-1455", "detail": "The bounded benchmark uses committed points and creates no adaptive plan."},
        {"operation": "CSV/dataframe row materialization", "benchmark_timer_scope": "OUTSIDE_TIMER", "production_full_run_scope": "OUTSIDE_TIMER", "evidence": "benchmark:512-531,551,557-570;production:1216-1281", "detail": "Benchmark timing-row merge and CSV writes are outside. Production final CSVs are after finished_at; in-memory attempt rows are a separate inside-timer item. No DataFrame is used."},
        {"operation": "checkpoint write", "benchmark_timer_scope": "NOT_APPLICABLE", "production_full_run_scope": "INSIDE_TIMER", "evidence": "production:815-834,867-874,1421-1455", "detail": "Production writes 1,794 current-work checkpoints and 32 completed-timestamp checkpoints; the benchmark writes none."},
        {"operation": "manifest/provenance hashing", "benchmark_timer_scope": "OUTSIDE_TIMER", "production_full_run_scope": "MIXED", "evidence": "benchmark:615-637;production:1470-1486,1265-1404", "detail": "Benchmark package hashes are after all timings. Production preregistration/provenance hashes are inside run wall, while final output-manifest hashing is after finished_at."},
    ]


def timing_order() -> tuple[list[dict[str, object]], dict[str, object]]:
    timings = read_csv(OUTPUT / "benchmark_timings.csv")
    rows: list[dict[str, object]] = []
    for index, row in enumerate(timings, 1):
        rows.append({
            "execution_index": index,
            "timestamp": row["timestamp"],
            "point_id": row["point_id"],
            "point_category": row["point_category"],
            "actual_convergence_status": row["actual_convergence_status"],
            "actual_feasibility_status": row["actual_feasibility_status"],
            "wall_time_seconds": row["wall_time_seconds"],
        })
    values = [float(row["wall_time_seconds"]) for row in rows]
    maximum_index = values.index(max(values)) + 1
    first_five_mean = sum(values[:5]) / 5
    later_ten_mean = sum(values[5:]) / 10
    return rows, {
        "first_timed_call_seconds": values[0],
        "first_timed_call_is_maximum": maximum_index == 1,
        "maximum_execution_index": maximum_index,
        "maximum_seconds": max(values),
        "first_five_mean_seconds": first_five_mean,
        "later_ten_mean_seconds": later_ten_mean,
        "descriptive_interpretation": "The maximum is call 2, not call 1. The anchor block is slower on average; calls 6-15 are comparatively stable. Timestamp and category are confounded by fixed execution order; no significance claim.",
    }


def planning_projections(affine_ms: Decimal, planning_ms: Decimal) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for count in PROJECTION_COUNTS:
        n = Decimal(count)
        micro = n * BENCHMARK_MEAN_SECONDS
        affine = n * affine_ms / Decimal(1000)
        conservative = n * planning_ms / Decimal(1000)
        rows.append({
            "evaluation_count": count,
            "microbenchmark_full_in_memory_mean_seconds": decimal_text(micro),
            "historical_affine_marginal_workload_seconds": decimal_text(affine),
            "conservative_planning_workload_seconds": decimal_text(conservative),
            "fixed_current_benchmark_setup_seconds": decimal_text(BENCHMARK_SETUP_SECONDS),
            "affine_plus_fixed_setup_seconds": decimal_text(affine + BENCHMARK_SETUP_SECONDS),
            "conservative_plus_fixed_setup_seconds": decimal_text(conservative + BENCHMARK_SETUP_SECONDS),
            "future_checkpoint_io_overhead_seconds": "NOT_MEASURED",
            "planning_note": "Serial projections; add preregistered validation checkpoint/I/O allowance. Conservative rate is historical production logical aggregate and already amortizes historical, non-transferable checkpoint/setup overhead.",
        })
    return rows


def build_report(summary: dict[str, object], order: dict[str, object], projections: list[dict[str, object]]) -> str:
    fit = summary["two_point_affine_fit"]
    aggregate = summary["aggregate_rates_ms"]
    layers = summary["broad_layer_reconciliation_seconds"]
    stage0 = summary["stage0_runtime_ms"]
    projection_lines = "\n".join(
        f"| {row['evaluation_count']:,} | {float(row['historical_affine_marginal_workload_seconds']):.3f} s | "
        f"{float(row['conservative_planning_workload_seconds']):.3f} s | {float(row['fixed_current_benchmark_setup_seconds']):.3f} s | "
        f"{float(row['conservative_plus_fixed_setup_seconds']):.3f} s | NOT_MEASURED |"
        for row in projections
    )
    return f"""# DSO-VPP AC runtime reconciliation audit

Decision: `MICROBENCHMARK_AND_PRODUCTION_TIMING_RECONCILED`

This is a deterministic source/artifact audit. `NO_NEW_AC_EVALUATIONS_PERFORMED`. It does not validate DOE interior safety.

## Authoritative production counts

- Logical point evaluations / first attempts: **87,229**.
- Retry attempts: **143**.
- Actual authoritative AC attempts and stored attempt rows: **87,372**.
- Numerically converged attempts added to `accepted_neighbors`: **87,086** (50,777 feasible; 36,309 infeasible).
- Nonconverged stored rows: **286** (143 first attempts plus 143 failed retries).
- Search objects: 128 signed-axis searches, 32 center units, 1,152 base rays, and 482 adaptive rays. Thus 1,634 ray searches, 1,762 axis-plus-ray boundary searches, and 1,794 axis/center/ray units.
- Full production run wall: **54.581000089645386 s**. The 32 timestamp runtimes are available individually in `production_timing_reconstruction.csv` and sum to **{summary['timestamp_runtime_sum_seconds']:.12f} s**.

`87,086` is a converged-attempt count, not a logical-evaluation count. `87,229` is a logical point-call count, not a ray/search count. `87,372` is the authoritative actual-attempt and stored-row count.

## Historical model reconstruction

The earlier 0.47 ms value came from the descriptive two-point fit `T = F + cN`:

- Phase-B: `N1=3,691`, `T1=15.3498603 s`.
- Production: `N2=87,229 logical evaluations`, `T2=54.581000089645386 s`.
- `c=(T2-T1)/(N2-N1)={fit['c_ms_per_logical_evaluation']:.15f} ms/logical evaluation`.
- `F=T1-c*N1={fit['F_seconds']:.15f} s`.

This two-point model is underdetermined as causal evidence: Phase-B and production have different workloads, coordinate/reference-PV contexts, timer setup scopes, and checkpoint behavior. The production aggregate rates are independently derived as **{aggregate['production_per_logical_evaluation']:.15f} ms/logical evaluation** and **{aggregate['production_per_actual_attempt']:.15f} ms/actual attempt**.

## What 65.9 microseconds measures

Precise label: `FULL_PRODUCTION_IN_MEMORY_LOGICAL_EVALUATION_NO_RETRY_EXCLUDING_SEARCH_ORCHESTRATION_AND_IO`.

The benchmark starts its timer immediately before `evaluate_physical!` and stops immediately after it returns. It includes scalar coordinate normalization, per-call injection/net-demand assembly, primary radial BFS, independent replay, voltage/replay classification, logical/attempt ID mutation, in-memory attempt-row construction, and accepted-neighbor voltage copying/storage. It excludes point selection, ray/axis coordinate derivation, post-return binding classification, benchmark timing-row construction, re-entry/adaptive logic, checkpoints, CSV output, and hashing. It is therefore neither `AC_CORE_ONLY` nor end-to-end production throughput. Exact itemization is in `timer_scope_inventory.csv`.

## State reuse

- `BENCHMARK_STATE_REUSE = PARTIAL`: network/profile objects and one mutable `EvaluationState` per timestamp persist. Every first attempt explicitly uses `initial_voltage=nothing` (`FLAT_START`). All 16 benchmark attempts converged first try, so no voltage warm start was reused; accepted-neighbor state merely accumulated.
- `PRODUCTION_STATE_REUSE = PARTIAL`: the same per-timestamp state persists across axes, center, and rays. Every logical evaluation first flat-starts. Only a nonconverged first attempt selects the nearest accepted neighbor and retries with its voltage. Production had 143 such retries; all 143 also failed. State resets with each timestamp's `TimestampWork`.

## Production overhead and broad reconciliation

The committed per-attempt `Stage0.evaluate_point` timer sums to **{layers['stage0_evaluate_point_internal_sum']:.9f} s**; median **{stage0['median']:.4f} ms**, mean **{stage0['mean']:.6f} ms/actual attempt**. Expensive nonconvergent attempts raise the mean.

The measured run decomposes exactly at broad timer boundaries:

| Layer | Seconds | Evidence | Interpretation |
|---|---:|---|---|
| Stored Stage0 internal attempt timers | {layers['stage0_evaluate_point_internal_sum']:.9f} | MEASURED/SUMMED | Assembly, primary solve, replay, Stage0 classification; excludes production wrapper tail. |
| Timestamp scopes minus Stage0 timers | {layers['timestamp_scope_minus_stage0_sum']:.9f} | DERIVED_REMAINDER | Wrapper/search allocations and bookkeeping, re-entry/refinement logic, growing in-memory state, and current-checkpoint serialization/I/O; not separately isolatable. |
| Full run minus summed timestamp scopes | {layers['run_scope_minus_timestamp_sum']:.9f} | DERIVED_REMAINDER | Preflight/profile work, completed-timestamp checkpoint work, logging, and other inter-scope gaps; not pure startup. |
| Full production timer | {layers['sum']:.9f} | MEASURED | 54.581000089645386 s. |

Production performs 1,794 growing-current-work checkpoint writes plus 32 completed-timestamp writes. Final CSV/artifact serialization occurs after `finished_at` and is excluded from the 54.581 s production timer. Attempt IDs, attempt/result allocation, per-attempt provenance, accepted-neighbor updates, and in-memory rows are computation/allocation rather than disk I/O. Search-level safe/violating storage and re-entry/adaptive work occur outside `evaluate_physical!` but inside the production run.

The 65.9 microsecond median and 0.47-0.63 ms historical effective rates can both be correct because they measure different scopes and runs. The current benchmark isolates a short, warmed, converged/no-retry in-memory call. Production includes a materially larger workload, 286 expensive nonconvergent attempts, search orchestration, growing state, frequent checkpoints, and fixed run work. Historical host CPU/RAM identity is not recorded, so the remaining machine/run-condition difference is not causally decomposed.

## Ordered benchmark behavior

The first timed call was **{order['first_timed_call_seconds'] * 1e6:.1f} microseconds** and was not the maximum. Call **{order['maximum_execution_index']}** was the maximum at **{order['maximum_seconds'] * 1e6:.1f} microseconds**. The first five-call anchor block averaged **{order['first_five_mean_seconds'] * 1e6:.3f} microseconds** versus **{order['later_ten_mean_seconds'] * 1e6:.3f} microseconds** for calls 6-15. Later calls are descriptively more stable, but timestamp and category are confounded by execution order; no significance claim is made. See `benchmark_timing_order.csv` for all 15 rows.

## Rates for validation planning

- `AC_CORE_RATE = NOT_SEPARATELY_IDENTIFIABLE_FROM_CURRENT_ARTIFACTS`. The 65.9 microsecond result includes more than the AC core.
- `FULL_IN_MEMORY_EVALUATION_RATE = 0.0659 ms median; 0.0758133333333 ms mean` for the current laptop's converged/no-retry benchmark scope.
- `VALIDATION_PLANNING_RATE = 0.625720804888803 ms/evaluation` (conservative upper rate: historical production wall/logical count).
- Supporting planning interval: `0.469620290043398-0.625720804888803 ms/evaluation`, from the weak affine marginal fit to the measured production logical aggregate.

Projections separate workload from the measured current setup cost. Future validation checkpoint/I/O cost remains unmeasured and must receive a preregistered allowance rather than a fabricated value.

| Evaluations | Affine workload | Conservative workload | Fixed setup | Conservative + setup | Future checkpoint/I/O |
|---:|---:|---:|---:|---:|---|
{projection_lines}

The conservative rate already amortizes historical production setup/checkpoint activity, so adding both it and the 22.382838 s current setup is intentionally conservative rather than a fitted end-to-end prediction.

## Interior-centroid observation

`DOE_BENCHMARK_CELL_CENTROIDS_3_OF_3_AC_FEASIBLE`

Mandatory qualifier: `CELL_CENTROID_POINTS_ONLY; SMALL_N; NO_INTERIOR_SAFETY_INFERENCE`.

These were arithmetic vertex centroids of the largest committed exact convex cell at the three selected timestamps. Existing Stage0 artifacts and source already contain earlier two-dimensional non-axis AC points (for example corrected Stage0 point 97 at P13=2000 kW, P30=500 kW under a different reference-PV context), so no "first off-skeleton in the whole project" claim is made.

## Provenance and unchanged scientific scope

`c18021d9b981f2629e54f60e8c2fc5f33b00c1a2` (`audit: finalize DOE preconstruction artifact analysis`)

-> `aaa6a745dd428c3efd267214337f6cb583489ed3` (`checkpoint: preserve DOE architecture audits`)

-> `29e20ac5115806738c47b587c795c422a1297eee` (`checkpoint: preserve VMAX pocket hulling audit`)

-> current runtime benchmark and reconciliation (`UNCOMMITTED`).

Architecture remains unchanged: `FULL EXACT CONVEX PARTITION = MAIN CANDIDATE`; `CONVEX-HULLED POCKET-DIFFERENCE = COMPACT FALLBACK`. The unresolved issue remains `INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY`.
"""


def update_benchmark_report(reconciliation_report: str) -> None:
    original = (OUTPUT / "benchmark_report.md").read_text(encoding="utf-8")
    marker = "\n## Runtime reconciliation correction\n"
    if marker in original:
        original = original.split(marker, 1)[0].rstrip() + "\n"
    correction = """
## Runtime reconciliation correction

The original 65.9 microsecond median is preserved, but its precise scope is corrected to `FULL_PRODUCTION_IN_MEMORY_LOGICAL_EVALUATION_NO_RETRY_EXCLUDING_SEARCH_ORCHESTRATION_AND_IO`, not AC-core-only or end-to-end production throughput. Future validation preregistration should use 0.625720804888803 ms/evaluation as the conservative workload rate, state the 22.382838 s measured current setup separately, and budget future checkpoint/I/O explicitly. See `runtime_reconciliation_report.md` for the deterministic count, timer-scope, and production-runtime reconstruction. `NO_NEW_AC_EVALUATIONS_PERFORMED`.
"""
    (OUTPUT / "benchmark_report.md").write_text(original.rstrip() + marker + correction.split(marker, 1)[-1].lstrip(), encoding="utf-8")


def write_manifest() -> None:
    names = sorted(
        path.name for path in OUTPUT.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "schema_version": 2,
        "source_branch": EXPECTED_BRANCH,
        "source_head": EXPECTED_HEAD,
        "package_classification": "RUNTIME_BENCHMARK_WITH_RECONCILIATION_AUDIT_NOT_VALIDATION",
        "reconciliation_decision": "MICROBENCHMARK_AND_PRODUCTION_TIMING_RECONCILED",
        "no_new_ac_evaluations_performed": True,
        "deterministic_reconciliation_outputs": True,
        "byte_identical_original_timing_outputs_expected": False,
        "files": [
            {"path": name, "bytes": (OUTPUT / name).stat().st_size, "sha256": sha256(OUTPUT / name)}
            for name in names
        ],
    }
    write_json(OUTPUT / "manifest.json", manifest)


def main() -> None:
    assert_repository_state()
    production, production_rows = reconstruct_production()
    inventory = timer_inventory()
    order_rows, order_summary = timing_order()
    fit = production["two_point_affine_fit"]
    planning_ms = Decimal(str(production["aggregate_rates_ms"]["production_per_logical_evaluation"]))
    affine_ms = Decimal(str(fit["c_ms_per_logical_evaluation"]))
    projections = planning_projections(affine_ms, planning_ms)

    summary = {
        "classification": "MICROBENCHMARK_AND_PRODUCTION_TIMING_RECONCILED",
        "no_new_ac_evaluations_performed": True,
        "benchmark_timer_label": "FULL_PRODUCTION_IN_MEMORY_LOGICAL_EVALUATION_NO_RETRY_EXCLUDING_SEARCH_ORCHESTRATION_AND_IO",
        "benchmark_state_reuse": "PARTIAL",
        "production_state_reuse": "PARTIAL",
        "ac_core_rate": "NOT_SEPARATELY_IDENTIFIABLE_FROM_CURRENT_ARTIFACTS",
        "full_in_memory_evaluation_rate": {
            "median_ms": float(BENCHMARK_MEDIAN_SECONDS * Decimal(1000)),
            "mean_ms": float(BENCHMARK_MEAN_SECONDS * Decimal(1000)),
            "scope": "CURRENT_LAPTOP_CONVERGED_NO_RETRY_IN_MEMORY_WRAPPER",
        },
        "validation_planning_rate": {
            "selected_ms_per_evaluation": float(planning_ms),
            "supporting_interval_ms_per_evaluation": [float(affine_ms), float(planning_ms)],
            "fixed_setup_seconds_reported_separately": float(BENCHMARK_SETUP_SECONDS),
            "future_checkpoint_io_overhead": "NOT_MEASURED_REQUIRES_PREREGISTERED_ALLOWANCE",
        },
        "production": production,
        "benchmark_timing_order": order_summary,
        "interior_centroid_result": {
            "classification": "DOE_BENCHMARK_CELL_CENTROIDS_3_OF_3_AC_FEASIBLE",
            "qualifier": "CELL_CENTROID_POINTS_ONLY;SMALL_N;NO_INTERIOR_SAFETY_INFERENCE",
            "first_ever_claim": False,
            "secondary_note": "Prior committed Stage0 two-dimensional non-axis AC points exist under a different reference-PV context.",
        },
        "provenance_chain": [
            {"commit": "c18021d9b981f2629e54f60e8c2fc5f33b00c1a2", "subject": "audit: finalize DOE preconstruction artifact analysis"},
            {"commit": "aaa6a745dd428c3efd267214337f6cb583489ed3", "subject": "checkpoint: preserve DOE architecture audits"},
            {"commit": EXPECTED_HEAD, "subject": "checkpoint: preserve VMAX pocket hulling audit"},
            {"commit": "UNCOMMITTED", "subject": "current runtime benchmark and reconciliation"},
        ],
        "architecture": {
            "main_candidate": "FULL_EXACT_CONVEX_PARTITION",
            "compact_fallback": "CONVEX_HULLED_POCKET_DIFFERENCE",
            "unresolved_issue": "INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY",
        },
    }

    write_csv(OUTPUT / "production_timing_reconstruction.csv", production_rows)
    write_csv(OUTPUT / "timer_scope_inventory.csv", inventory)
    write_csv(OUTPUT / "benchmark_timing_order.csv", order_rows)
    write_csv(OUTPUT / "runtime_projection.csv", projections)
    write_json(OUTPUT / "runtime_reconciliation_summary.json", summary)
    report = build_report(production, order_summary, projections)
    (OUTPUT / "runtime_reconciliation_report.md").write_text(report, encoding="utf-8")
    update_benchmark_report(report)
    write_manifest()
    print("reconciliation_complete=true")
    print("new_ac_evaluations=0")
    print("classification=MICROBENCHMARK_AND_PRODUCTION_TIMING_RECONCILED")


if __name__ == "__main__":
    main()
