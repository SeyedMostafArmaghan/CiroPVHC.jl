#!/usr/bin/env julia

const SCRIPT_STARTED_NS = time_ns()

using Dates
using Printf
using SHA
using TOML

const ROOT = normpath(joinpath(@__DIR__, ".."))
include(joinpath(ROOT, "src", "benchmark", "dso_vpp_production_probe.jl"))
const Probe = DSOVPPProductionProbe
const Stage0 = Probe.Stage0

const EXPECTED_HEAD = "29e20ac5115806738c47b587c795c422a1297eee"
const EXPECTED_BRANCH = "codex/dso-vpp-ac-map-pilot"
const ANCHOR_TIMESTAMP = "2012-10-15 13:00:00"
const MAXIMUM_AC_ATTEMPTS = 20
const TIMED_POINT_COUNT = 15
const PROJECTION_COUNTS = (1_000, 5_000, 10_000, 50_000)
const OUTPUT_DIR = joinpath(
    ROOT, "results", "dso_vpp_ac_map_pilot", "doe_ac_runtime_benchmark",
)
const PRODUCTION_DIR = joinpath(
    ROOT, "results", "dso_vpp_ac_map_pilot", "production_probe",
)
const PARTITION_DIR = joinpath(
    ROOT, "results", "dso_vpp_ac_map_pilot", "doe_construction_policy_preregistration",
    "convex_piecewise_architecture_audit",
)

function json_escape(value::AbstractString)
    escaped = replace(value, '\\' => "\\\\")
    escaped = replace(escaped, '"' => "\\\"")
    escaped = replace(escaped, '\n' => "\\n", '\r' => "\\r", '\t' => "\\t")
    return escaped
end

function write_json_value(io, value, indent::Int=0)
    if value === nothing
        print(io, "null")
    elseif value isa Bool
        print(io, lowercase(string(value)))
    elseif value isa Integer
        print(io, value)
    elseif value isa AbstractFloat
        isfinite(value) ? print(io, @sprintf("%.15g", value)) : print(io, "null")
    elseif value isa AbstractString
        print(io, '"', json_escape(value), '"')
    elseif value isa NamedTuple
        write_json_object(io, collect(pairs(value)), indent)
    elseif value isa AbstractDict
        ordered = [String(key) => value[key] for key in sort!(collect(keys(value)); by=string)]
        write_json_object(io, ordered, indent)
    elseif value isa AbstractVector || value isa Tuple
        items = collect(value)
        if isempty(items)
            print(io, "[]")
        else
            println(io, '[')
            for (index, item) in pairs(items)
                print(io, " "^(indent + 2))
                write_json_value(io, item, indent + 2)
                index < length(items) && print(io, ',')
                println(io)
            end
            print(io, " "^indent, ']')
        end
    else
        write_json_value(io, string(value), indent)
    end
end

function write_json_object(io, entries, indent::Int)
    if isempty(entries)
        print(io, "{}")
        return
    end
    println(io, '{')
    for (index, entry) in pairs(entries)
        key, value = entry
        print(io, " "^(indent + 2), '"', json_escape(string(key)), "\": ")
        write_json_value(io, value, indent + 2)
        index < length(entries) && print(io, ',')
        println(io)
    end
    print(io, " "^indent, '}')
end

function write_json(path::AbstractString, value)
    open(path, "w") do io
        write_json_value(io, value)
        println(io)
    end
    return path
end

parse_float(value) = parse(Float64, value)
parse_int(value) = parse(Int, value)
file_sha256(path) = bytes2hex(open(sha256, path))

function process_cpu_seconds()
    ticks = Float64(ccall(:clock, Clong, ()))
    return ticks / (Sys.iswindows() ? 1_000.0 : 1_000_000.0)
end

function current_process_rss_bytes()
    if Sys.iswindows()
        command = Cmd([
            "powershell", "-NoProfile", "-Command",
            "(Get-Process -Id $(getpid())).WorkingSet64",
        ])
        return parse(Int, strip(read(command, String)))
    end
    return Sys.maxrss()
end

function git_state()
    branch = Probe.git_output(ROOT, "branch", "--show-current")
    head = Probe.git_output(ROOT, "rev-parse", "HEAD")
    status = Probe.git_output(ROOT, "status", "--short")
    divergence = split(Probe.git_output(
        ROOT, "rev-list", "--left-right", "--count",
        "HEAD...origin/$EXPECTED_BRANCH",
    ))
    length(divergence) == 2 || error("unexpected divergence output")
    return (
        branch=branch,
        head=head,
        working_tree_clean=isempty(status),
        status_short=status,
        behind=parse(Int, divergence[1]),
        ahead=parse(Int, divergence[2]),
    )
end

function assert_starting_state(state)
    state.branch == EXPECTED_BRANCH || error("unexpected branch: $(state.branch)")
    state.head == EXPECTED_HEAD || error("unexpected HEAD: $(state.head)")
    state.working_tree_clean || error(
        "benchmark must be launched from the expected clean starting state; " *
        "create the benchmark script first, then pass --allow-benchmark-script-untracked",
    )
    state.behind == 0 || error("authoritative branch is behind remote")
    state.ahead == 0 || error("authoritative branch is ahead of remote")
end

function assert_launch_state(state)
    state.branch == EXPECTED_BRANCH || error("unexpected branch: $(state.branch)")
    state.head == EXPECTED_HEAD || error("unexpected HEAD: $(state.head)")
    state.behind == 0 || error("authoritative branch is behind remote")
    state.ahead == 0 || error("authoritative branch is ahead of remote")
    allowed = replace(state.status_short, '\\' => '/')
    allowed == "?? scripts/benchmark_dso_vpp_ac_evaluation_runtime.jl" || error(
        "launch state contains changes beyond the new benchmark script: $(repr(state.status_short))",
    )
end

function select_timestamps(runtime_rows)
    anchor = only(row for row in runtime_rows if row.timestamp == ANCHOR_TIMESTAMP)
    non_anchor = [row for row in runtime_rows if row.timestamp != ANCHOR_TIMESTAMP]
    low = first(sort(non_anchor; by=row -> (parse_float(row.runtime_seconds), row.timestamp)))
    high = first(sort(non_anchor; by=row -> (-parse_float(row.runtime_seconds), row.timestamp)))
    return [
        (
            selection_role="MANDATORY_ANCHOR",
            timestamp=anchor.timestamp,
            production_selection_index=parse_int(anchor.selection_index),
            historical_runtime_seconds=parse_float(anchor.runtime_seconds),
            historical_actual_evaluations=parse_int(anchor.actual_evaluations),
            selection_provenance="MANDATORY_ANCHOR_FROM_COMMITTED_32_TIMESTAMP_SET",
        ),
        (
            selection_role="LOW_HISTORICAL_PRODUCTION_RUNTIME",
            timestamp=low.timestamp,
            production_selection_index=parse_int(low.selection_index),
            historical_runtime_seconds=parse_float(low.runtime_seconds),
            historical_actual_evaluations=parse_int(low.actual_evaluations),
            selection_provenance="MINIMUM_TIMESTAMP_RUNTIME_EXCLUDING_MANDATORY_ANCHOR",
        ),
        (
            selection_role="HIGH_HISTORICAL_PRODUCTION_RUNTIME",
            timestamp=high.timestamp,
            production_selection_index=parse_int(high.selection_index),
            historical_runtime_seconds=parse_float(high.runtime_seconds),
            historical_actual_evaluations=parse_int(high.actual_evaluations),
            selection_provenance="MAXIMUM_TIMESTAMP_RUNTIME_EXCLUDING_MANDATORY_ANCHOR",
        ),
    ]
end

function ray_sort_key(row)
    level_rank = row.level == "BASE" ? 0 : 1
    return (parse_float(row.angle_deg), level_rank, row.level)
end

function select_ray(rows, timestamp, mechanism)
    candidates = [
        row for row in rows
        if row.timestamp == timestamp && row.status == "RAY_CERTIFIED_BOUNDARY" &&
           row.binding_mechanism == mechanism &&
           row.safe_solver_status == "CONVERGED_FEASIBLE" &&
           row.violating_solver_status == "CONVERGED_INFEASIBLE"
    ]
    isempty(candidates) && error("no paired $mechanism ray for $timestamp")
    return first(sort(candidates; by=ray_sort_key))
end

function select_interior_point(partition_rows, timestamp)
    rows = [row for row in partition_rows if row.timestamp == timestamp]
    isempty(rows) && error("no exact partition cells for $timestamp")
    cell_areas = Dict{Int,Float64}()
    for row in rows
        cell_areas[parse_int(row.cell_index)] = parse_float(row.cell_area_kw2)
    end
    chosen_cell = first(sort!(collect(keys(cell_areas)); by=index -> (-cell_areas[index], index)))
    vertices = [row for row in rows if parse_int(row.cell_index) == chosen_cell]
    sort!(vertices; by=row -> parse_int(row.cell_vertex_index_ccw))
    p13 = sum(parse_float(row.p13_abs_kw) for row in vertices) / length(vertices)
    p30 = sum(parse_float(row.p30_abs_kw) for row in vertices) / length(vertices)
    return (
        p13_abs_kw=p13,
        p30_abs_kw=p30,
        provenance=@sprintf(
            "ARITHMETIC_VERTEX_CENTROID_OF_LARGEST_COMMITTED_EXACT_CONVEX_CELL:%d:AREA_KW2=%.12g",
            chosen_cell, cell_areas[chosen_cell],
        ),
    )
end

function benchmark_points(selected_timestamps, center_rows, ray_rows, partition_rows)
    points = NamedTuple[]
    for selection in selected_timestamps
        timestamp = selection.timestamp
        center = only(row for row in center_rows if row.timestamp == timestamp)
        vmax = select_ray(ray_rows, timestamp, "BINDING_VMAX")
        vmin = select_ray(ray_rows, timestamp, "BINDING_VMIN")
        interior = select_interior_point(partition_rows, timestamp)
        prefix = @sprintf("T%02d", selection.production_selection_index)
        append!(points, [
            (
                timestamp=timestamp, timestamp_selection_role=selection.selection_role,
                point_id="$(prefix)_CENTER", point_category="CERTIFIED_PRODUCTION_CENTER",
                p13_abs_kw=parse_float(center.p13_abs_kw), p30_abs_kw=parse_float(center.p30_abs_kw),
                expected_prior_status="CONVERGED_FEASIBLE",
                point_provenance="production_probe/center_results.csv:selection_index=$(selection.production_selection_index)",
            ),
            (
                timestamp=timestamp, timestamp_selection_role=selection.selection_role,
                point_id="$(prefix)_VMAX_INWARD", point_category="INWARD_VMAX_SIDE_BOUNDARY",
                p13_abs_kw=parse_float(vmax.safe_p13_abs_kw), p30_abs_kw=parse_float(vmax.safe_p30_abs_kw),
                expected_prior_status="CONVERGED_FEASIBLE",
                point_provenance="production_probe/$(lowercase(vmax.level))_ray_results.csv:angle_deg=$(vmax.angle_deg):SAFE",
            ),
            (
                timestamp=timestamp, timestamp_selection_role=selection.selection_role,
                point_id="$(prefix)_VMIN_INWARD", point_category="INWARD_VMIN_SIDE_BOUNDARY",
                p13_abs_kw=parse_float(vmin.safe_p13_abs_kw), p30_abs_kw=parse_float(vmin.safe_p30_abs_kw),
                expected_prior_status="CONVERGED_FEASIBLE",
                point_provenance="production_probe/$(lowercase(vmin.level))_ray_results.csv:angle_deg=$(vmin.angle_deg):SAFE",
            ),
            (
                timestamp=timestamp, timestamp_selection_role=selection.selection_role,
                point_id="$(prefix)_INTERIOR", point_category="CLEARLY_INTERIOR_GEOMETRIC_POINT",
                p13_abs_kw=interior.p13_abs_kw, p30_abs_kw=interior.p30_abs_kw,
                expected_prior_status="UNKNOWN_NOT_PREVIOUSLY_AC_EVALUATED",
                point_provenance=interior.provenance,
            ),
            (
                timestamp=timestamp, timestamp_selection_role=selection.selection_role,
                point_id="$(prefix)_OUTWARD", point_category="STORED_OUTWARD_INFEASIBLE_ENDPOINT",
                p13_abs_kw=parse_float(vmax.violating_p13_abs_kw), p30_abs_kw=parse_float(vmax.violating_p30_abs_kw),
                expected_prior_status="CONVERGED_INFEASIBLE",
                point_provenance="production_probe/$(lowercase(vmax.level))_ray_results.csv:angle_deg=$(vmax.angle_deg):VIOLATING",
            ),
        ])
    end
    length(points) == TIMED_POINT_COUNT || error("unexpected timed point count")
    return points
end

function sample_quantile(values, probability)
    sorted_values = sort(Float64.(values))
    isempty(sorted_values) && return NaN
    length(sorted_values) == 1 && return only(sorted_values)
    position = 1 + (length(sorted_values) - 1) * Float64(probability)
    lower = floor(Int, position)
    upper = ceil(Int, position)
    lower == upper && return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction
end

function summary_row(group_type, group_value, values)
    return (
        group_type=String(group_type), group_value=String(group_value), count=length(values),
        min_seconds=minimum(values), q1_seconds=sample_quantile(values, 0.25),
        median_seconds=sample_quantile(values, 0.50), q3_seconds=sample_quantile(values, 0.75),
        max_seconds=maximum(values), mean_seconds=sum(values) / length(values),
    )
end

function timing_summary(timings)
    rows = NamedTuple[]
    push!(rows, summary_row("OVERALL", "ALL_STEADY_STATE_TIMED_EVALUATIONS",
                            [row.wall_time_seconds for row in timings]))
    for field in (:actual_feasibility_status, :actual_convergence_status, :timestamp, :point_category)
        group_type = field == :actual_feasibility_status ? "FEASIBILITY" :
                     field == :actual_convergence_status ? "CONVERGENCE" :
                     field == :timestamp ? "TIMESTAMP" : "POINT_CATEGORY"
        for value in sort!(unique(String(getproperty(row, field)) for row in timings))
            values = [row.wall_time_seconds for row in timings if getproperty(row, field) == value]
            push!(rows, summary_row(group_type, value, values))
        end
    end
    return rows
end

function human_duration(seconds)
    seconds < 60 && return @sprintf("%.3f s", seconds)
    seconds < 3600 && return @sprintf("%.3f min", seconds / 60)
    return @sprintf("%.3f h", seconds / 3600)
end

function projection_rows(overall)
    rows = NamedTuple[]
    bases = (("MEAN_STEADY_STATE", overall.mean_seconds),
             ("MEDIAN_STEADY_STATE", overall.median_seconds))
    for count in PROJECTION_COUNTS, (basis, per_eval) in bases, workers in (1, 4, 8)
        seconds = count * per_eval / workers
        scenario = workers == 1 ? "SERIAL_MEASURED_RATE_PROJECTION" :
                   "IDEALIZED_PARALLEL_PROJECTION_NOT_MEASURED"
        push!(rows, (
            evaluation_count=count, scenario=scenario, worker_count=workers,
            timing_basis=basis, per_evaluation_seconds=per_eval,
            projected_wall_seconds=seconds, projected_wall_human=human_duration(seconds),
            overhead_included=false,
            caveat=workers == 1 ? "EXCLUDES_LAUNCH_SETUP_AND_CHECKPOINT_IO" :
                "PERFECT_DIVISION_ONLY;EXCLUDES_WORKER_STARTUP,IPC,MERGE,CHECKPOINT_IO,AND_CONTENTION",
        ))
    end
    return rows
end

function write_report(path, config, points, warmup, summaries, resource, projections, timings)
    overall = only(row for row in summaries if row.group_type == "OVERALL")
    feasible = filter(row -> row.group_type == "FEASIBILITY" && row.group_value == "FEASIBLE", summaries)
    infeasible = filter(row -> row.group_type == "FEASIBILITY" && row.group_value == "INFEASIBLE", summaries)
    serial_mean = [row for row in projections if row.worker_count == 1 && row.timing_basis == "MEAN_STEADY_STATE"]
    open(path, "w") do io
        println(io, "# DSO-VPP authoritative AC evaluation runtime benchmark")
        println(io)
        println(io, "Classification: `RESOURCE_PLANNING_BENCHMARK_ONLY`; `NOT_DOE_INTERIOR_VALIDATION`.")
        println(io)
        println(io, "## Locked evaluation path")
        println(io)
        println(io, "`DSOVPPProductionProbe.evaluate_physical!` calls `DSOVPPACMapStage0.evaluate_point`, which assembles absolute physical P13/P30 injections, runs `primary_power_flow`, then independently replays with `CiroPVHC.replay_s1b_interval`. The benchmark uses `reference_pv_capacity_kw=0`, Q13=Q30=0, buses 13 and 30, VMIN=0.90 p.u., VMAX=1.05 p.u., and the production flat-start/retry semantics.")
        println(io)
        println(io, "A point is `FEASIBLE` only when the production wrapper returns `CONVERGED_FEASIBLE`; `INFEASIBLE` means `CONVERGED_INFEASIBLE`; nonconvergence after the production retry policy is `UNRESOLVED`. Successful execution here does not certify any inter-ray edge or angular interior.")
        println(io)
        println(io, "## Design")
        println(io)
        println(io, "One untimed warm-up plus $(length(timings)) timed logical point evaluations were run serially. Underlying AC attempts: $(resource.actual_ac_attempt_count), with a hard cap of $(resource.maximum_ac_attempt_count). Timestamps were the mandatory anchor, committed production-runtime minimum excluding the anchor, and committed production-runtime maximum excluding the anchor.")
        println(io)
        println(io, "Each timestamp contributes its committed certified center, the lowest-angle paired VMAX ray safe endpoint, the lowest-angle paired VMIN ray safe endpoint, the arithmetic vertex centroid of its largest committed exact convex cell, and the paired stored outward-infeasible endpoint from the selected VMAX ray.")
        println(io)
        println(io, "## Warm-up and steady state")
        println(io)
        @printf(io, "- In-script setup before warm-up: %.6f s.\n", resource.in_script_setup_seconds)
        @printf(io, "- First-call/JIT warm-up: %.6f s (%s, %s).\n", warmup.wall_time_seconds, warmup.actual_convergence_status, warmup.actual_feasibility_status)
        @printf(io, "- Steady state (n=%d): min %.9f, Q1 %.9f, median %.9f, Q3 %.9f, max %.9f, mean %.9f s.\n",
                overall.count, overall.min_seconds, overall.q1_seconds, overall.median_seconds,
                overall.q3_seconds, overall.max_seconds, overall.mean_seconds)
        !isempty(feasible) && @printf(io, "- Feasible (n=%d): median %.9f s, mean %.9f s.\n", only(feasible).count, only(feasible).median_seconds, only(feasible).mean_seconds)
        !isempty(infeasible) && @printf(io, "- Infeasible (n=%d): median %.9f s, mean %.9f s.\n", only(infeasible).count, only(infeasible).median_seconds, only(infeasible).mean_seconds)
        println(io)
        println(io, "These subgroup samples are deliberately tiny and are descriptive only.")
        println(io)
        println(io, "## CPU and RAM")
        println(io)
        @printf(io, "- Available logical CPUs: %d; Julia processes: 1; Julia threads: %d.\n", resource.logical_cpu_count, resource.julia_thread_count)
        @printf(io, "- Baseline current process RSS before warm-up: %.3f MiB; approximate peak process RSS: %.3f MiB.\n", resource.baseline_process_rss_bytes / 2.0^20, resource.peak_process_rss_bytes / 2.0^20)
        @printf(io, "- Timed-loop process CPU: %.6f s over %.6f s aggregate loop wall time (%.3f average process cores; coarse observation).\n", resource.timed_loop_process_cpu_seconds, resource.timed_loop_wall_seconds, resource.average_process_cores)
        println(io, "- Source inspection finds no threading in this call path; execution was serial and appears single-threaded. The short CPU sample is too small for an exact utilization claim.")
        println(io)
        println(io, "## Projection and execution recommendation")
        println(io)
        println(io, "Mean-rate serial projections (excluding startup and checkpoint I/O):")
        println(io)
        for row in serial_mean
            println(io, "- $(row.evaluation_count): $(row.projected_wall_human)")
        end
        println(io)
        println(io, "Four- and eight-worker rows in `runtime_projection.csv` are `IDEALIZED_PARALLEL_PROJECTION_NOT_MEASURED`. Perfect scaling is not assumed for planning.")
        println(io)
        println(io, "Later point/timestamp evaluation is `TECHNICALLY_PARALLELIZABLE` with worker-owned network/evaluation state and deterministic result merging. The current production implementation is `CURRENT_IMPLEMENTATION_ALREADY_SUPPORTS_PARALLEL_EXECUTION = false`: it serially mutates evaluation IDs, accepted-neighbor warm starts, and attempt rows. Parallelizing that shared state directly would be unsafe and could change retry behavior.")
        println(io)
        println(io, "Laptop classification: `SAFE_ON_PERSONAL_LAPTOP_WITH_CHECKPOINTING`. Use deterministic per-timestamp partitions, checkpoint every fixed 250 candidate points within a timestamp, finalize an atomic checkpoint per timestamp, and merge in preregistered timestamp/point order. Reuse production probing's atomic write and provenance-hash pattern, but not its schema-specific serialized `TimestampWork` objects.")
        println(io)
        println(io, "## Reproducibility and guardrails")
        println(io)
        println(io, "Timestamp selection, point selection, coordinates, configuration, and provenance are deterministic structural inputs. Wall times, CPU observations, and RSS are nondeterministic measurements and are not expected to reproduce byte-for-byte.")
        println(io)
        println(io, "The locked architecture findings are unchanged: `FULL EXACT CONVEX PARTITION` remains the current main coupled DOE candidate; the convex-hulled VMAX pocket-difference representation remains the compact geometric fallback. Both remain `GEOMETRIC_ONLY` and `NOT_AC_INTERIOR_CERTIFIED`; `INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY` remains unresolved.")
        println(io)
        println(io, "No validation mesh, boundary search, DOE construction, optimization, replay campaign, parameter tuning, parallel benchmark, staging, commit, push, or stash operation was performed.")
    end
end

function main()
    launch_state = git_state()
    assert_launch_state(launch_state)
    isdir(OUTPUT_DIR) && error("benchmark output directory already exists: $OUTPUT_DIR")

    policy_path = joinpath(ROOT, "config", "dso_vpp_production_probe_preregistration.toml")
    config = Probe.validate_locked_config(TOML.parsefile(policy_path))
    runtime_path = joinpath(PRODUCTION_DIR, "timestamp_runtime_evaluation_summary.csv")
    center_path = joinpath(PRODUCTION_DIR, "center_results.csv")
    base_ray_path = joinpath(PRODUCTION_DIR, "base_ray_results.csv")
    adaptive_ray_path = joinpath(PRODUCTION_DIR, "adaptive_ray_results.csv")
    partition_path = joinpath(PARTITION_DIR, "merged_convex_cells.csv")
    source_paths = [runtime_path, center_path, base_ray_path, adaptive_ray_path, partition_path, policy_path]
    all(isfile, source_paths) || error("one or more committed source artifacts are missing")

    runtime_rows = Probe.read_csv_rows(runtime_path)
    center_rows = Probe.read_csv_rows(center_path)
    ray_rows = vcat(Probe.read_csv_rows(base_ray_path), Probe.read_csv_rows(adaptive_ray_path))
    partition_rows = Probe.read_csv_rows(partition_path)
    selections = select_timestamps(runtime_rows)
    points = benchmark_points(selections, center_rows, ray_rows, partition_rows)

    mkpath(OUTPUT_DIR)
    points_fields = propertynames(first(points))
    Probe.write_csv(joinpath(OUTPUT_DIR, "benchmark_points.csv"), points_fields, points)

    benchmark_config = (
        schema_version=1,
        purpose="RESOURCE_PLANNING_BENCHMARK_ONLY_NOT_VALIDATION",
        source_branch=launch_state.branch,
        source_head=launch_state.head,
        starting_state=(working_tree_clean=true, behind=0, ahead=0),
        authoritative_entry_function="DSOVPPProductionProbe.evaluate_physical!",
        authoritative_call_path=[
            "DSOVPPProductionProbe.evaluate_physical!",
            "DSOVPPACMapStage0.evaluate_point",
            "DSOVPPACMapStage0.primary_power_flow",
            "CiroPVHC.replay_s1b_interval",
            "DSOVPPProductionProbe.attempt_class",
        ],
        coordinate_contract=(
            active_power="ABSOLUTE_PHYSICAL_PCC_ACTIVE_POWER_KW",
            interface_buses=[13, 30], n_p=2, q_pcc_kvar=0.0,
            reference_pv_capacity_kw=0.0, positive_p="INJECTION_EXPORT_SUBTRACTED_FROM_BUS_DEMAND",
        ),
        voltage_policy=(vmin_pu=config.vmin_pu, vmax_pu=config.vmax_pu),
        convergence_policy=(
            primary_tolerance_pu=Stage0.PRIMARY_TOLERANCE_PU,
            primary_maximum_iterations=Stage0.PRIMARY_MAXIMUM_ITERATIONS,
            replay_tolerance_pu=Stage0.REPLAY_TOLERANCE_PU,
            replay_maximum_iterations=Stage0.REPLAY_MAXIMUM_ITERATIONS,
            residual_tolerance_pu=Stage0.RESIDUAL_TOLERANCE_PU,
            nonconvergence_classification="UNRESOLVED_NOT_INFEASIBLE",
        ),
        warmup=(count=1, point_id=points[1].point_id, included_in_steady_state=false),
        timed_logical_evaluation_count=length(points),
        maximum_underlying_ac_attempt_count=MAXIMUM_AC_ATTEMPTS,
        execution=(process_count=1, julia_thread_count=Threads.nthreads(), parallel=false),
        timestamp_selections=selections,
        source_artifacts=[(
            path=replace(relpath(path, ROOT), '\\' => '/'), sha256=file_sha256(path),
        ) for path in source_paths],
        script=(
            path="scripts/benchmark_dso_vpp_ac_evaluation_runtime.jl",
            sha256=file_sha256(@__FILE__),
        ),
        reproducibility=(
            deterministic_structural_inputs=true,
            byte_identical_timing_outputs_expected=false,
            nondeterministic_fields=["wall_time_seconds", "CPU observations", "RSS observations"],
        ),
    )
    write_json(joinpath(OUTPUT_DIR, "benchmark_config.json"), benchmark_config)

    network = Stage0.build_pilot_network()
    profile = Stage0.load_profile(ROOT)
    profile_lookup = Dict(
        Dates.format(timestamp, dateformat"yyyy-mm-dd HH:MM:SS") => index
        for (index, timestamp) in pairs(profile.timestamps)
    )
    all(haskey(profile_lookup, selection.timestamp) for selection in selections) ||
        error("selected timestamp absent from canonical profile")
    states = Dict(selection.timestamp => Probe.EvaluationState() for selection in selections)

    baseline_rss = current_process_rss_bytes()
    setup_seconds = (time_ns() - SCRIPT_STARTED_NS) / 1e9
    total_attempts = Ref(0)

    function evaluate_one(point, phase)
        total_attempts[] <= MAXIMUM_AC_ATTEMPTS - 2 || error(
            "hard attempt cap prevents another possibly retried production evaluation",
        )
        state = states[point.timestamp]
        before_rows = length(state.attempt_rows)
        cpu_started = process_cpu_seconds()
        started_ns = time_ns()
        result = Probe.evaluate_physical!(
            state, network, profile, profile_lookup[point.timestamp],
            point.p13_abs_kw, point.p30_abs_kw, config;
            search_kind="RUNTIME_BENCHMARK", search_id=point.point_id,
            phase=phase, coordinate=0.0,
        )
        wall_seconds = (time_ns() - started_ns) / 1e9
        cpu_seconds = process_cpu_seconds() - cpu_started
        new_rows = state.attempt_rows[(before_rows + 1):end]
        total_attempts[] += length(new_rows)
        total_attempts[] <= MAXIMUM_AC_ATTEMPTS || error("hard AC attempt cap exceeded")
        last_attempt = last(new_rows)
        convergence = result.solver_status in ("CONVERGED_FEASIBLE", "CONVERGED_INFEASIBLE") ?
                      "CONVERGED" : "NONCONVERGED_OR_UNRESOLVED"
        feasibility = result.solver_status == "CONVERGED_FEASIBLE" ? "FEASIBLE" :
                      result.solver_status == "CONVERGED_INFEASIBLE" ? "INFEASIBLE" : "UNRESOLVED"
        mechanism = Probe.binding_mechanism(result, config)
        return result, (
            wall_time_seconds=wall_seconds,
            process_cpu_seconds=cpu_seconds,
            actual_attempt_count=length(new_rows),
            actual_convergence_status=convergence,
            actual_feasibility_status=feasibility,
            primary_power_flow_status=last_attempt.primary_power_flow_status,
            replay_status=last_attempt.replay_status,
            voltage_status=last_attempt.voltage_status,
            primary_voltage_mechanism=mechanism,
            vmin_pu=result.vmin_pu,
            vmin_bus=result.vmin_bus,
            vmax_pu=result.vmax_pu,
            vmax_bus=result.vmax_bus,
        )
    end

    _, warmup_measurement = evaluate_one(points[1], "UNTIMED_WARMUP_FIRST_CALL_JIT")
    warmup = merge((
        timestamp=points[1].timestamp, point_id=points[1].point_id,
        point_category=points[1].point_category,
    ), warmup_measurement)

    timings = NamedTuple[]
    timed_loop_cpu_started = process_cpu_seconds()
    timed_loop_started_ns = time_ns()
    for point in points
        _, measurement = evaluate_one(point, "STEADY_STATE_TIMED")
        push!(timings, merge(point, measurement))
    end
    timed_loop_wall_seconds = (time_ns() - timed_loop_started_ns) / 1e9
    timed_loop_cpu_seconds = process_cpu_seconds() - timed_loop_cpu_started
    peak_rss = max(Sys.maxrss(), current_process_rss_bytes())

    Probe.write_csv(
        joinpath(OUTPUT_DIR, "benchmark_timings.csv"),
        propertynames(first(timings)), timings,
    )
    summaries = timing_summary(timings)
    Probe.write_csv(
        joinpath(OUTPUT_DIR, "benchmark_runtime_summary.csv"),
        propertynames(first(summaries)), summaries,
    )
    overall = only(row for row in summaries if row.group_type == "OVERALL")
    projections = projection_rows(overall)
    Probe.write_csv(
        joinpath(OUTPUT_DIR, "runtime_projection.csv"),
        propertynames(first(projections)), projections,
    )

    resource = (
        observation_scope="COARSE_PROCESS_LEVEL_OBSERVATION_DURING_BOUNDED_BENCHMARK",
        logical_cpu_count=Sys.CPU_THREADS,
        julia_process_count=1,
        julia_thread_count=Threads.nthreads(),
        ac_path_threading_observation="NO_THREADING_CONSTRUCT_FOUND;SERIAL_SINGLE_JULIA_THREAD_EXECUTION",
        exact_cpu_utilization_claimed=false,
        in_script_setup_seconds=setup_seconds,
        baseline_process_rss_bytes=baseline_rss,
        peak_process_rss_bytes=peak_rss,
        approximate_incremental_peak_rss_bytes=max(0, peak_rss - baseline_rss),
        total_physical_memory_bytes=Sys.total_memory(),
        timed_loop_wall_seconds=timed_loop_wall_seconds,
        timed_loop_process_cpu_seconds=timed_loop_cpu_seconds,
        average_process_cores=timed_loop_wall_seconds > 0 ? timed_loop_cpu_seconds / timed_loop_wall_seconds : 0.0,
        warmup_wall_seconds=warmup.wall_time_seconds,
        timed_logical_evaluation_count=length(timings),
        actual_ac_attempt_count=total_attempts[],
        retry_attempt_count=total_attempts[] - (length(timings) + 1),
        maximum_ac_attempt_count=MAXIMUM_AC_ATTEMPTS,
        laptop_safety_classification="SAFE_ON_PERSONAL_LAPTOP_WITH_CHECKPOINTING",
        historical_production_probe=(
            source="production_probe/run_manifest.toml",
            wall_seconds=54.581000089645386,
            actual_ac_evaluation_count=87_372,
            julia_thread_count=1,
            peak_rss_bytes=996_311_040,
            historical_not_new_benchmark=true,
        ),
        parallelization=(
            technically_parallelizable=true,
            current_implementation_already_supports_parallel_execution=false,
            safe_deterministic_condition="WORKER_OWNED_NETWORK_AND_EVALUATION_STATE;DETERMINISTIC_STATIC_PARTITION;ORDERED_MERGE",
            shared_state_hazard="EvaluationState mutates logical IDs, attempt IDs, accepted-neighbor warm starts, and attempt rows",
        ),
        checkpoint_recommendation=(
            within_timestamp_batch_size=250,
            atomic_completion_unit="PER_TIMESTAMP",
            ordering="PREREGISTERED_TIMESTAMP_THEN_POINT_ID",
            production_infrastructure_reuse="REUSE_ATOMIC_WRITE_AND_PROVENANCE_HASH_PATTERN;DO_NOT_REUSE_SCHEMA_SPECIFIC_SERIALIZED_TIMESTAMPWORK",
        ),
    )
    write_json(joinpath(OUTPUT_DIR, "resource_observation.json"), resource)

    report_path = joinpath(OUTPUT_DIR, "benchmark_report.md")
    write_report(report_path, benchmark_config, points, warmup, summaries, resource, projections, timings)

    package_files = [
        "benchmark_config.json", "benchmark_points.csv", "benchmark_timings.csv",
        "benchmark_runtime_summary.csv", "resource_observation.json",
        "runtime_projection.csv", "benchmark_report.md",
    ]
    manifest = (
        schema_version=1,
        source_branch=launch_state.branch,
        source_head=launch_state.head,
        package_classification="RESOURCE_PLANNING_BENCHMARK_ONLY_NOT_VALIDATION",
        deterministic_structural_inputs=true,
        byte_identical_timing_outputs_expected=false,
        files=[(
            path=name, bytes=filesize(joinpath(OUTPUT_DIR, name)),
            sha256=file_sha256(joinpath(OUTPUT_DIR, name)),
        ) for name in package_files],
    )
    write_json(joinpath(OUTPUT_DIR, "manifest.json"), manifest)

    println("benchmark_complete=true")
    println("timed_logical_evaluations=$(length(timings))")
    println("actual_ac_attempts=$(total_attempts[])")
    @printf("warmup_seconds=%.9f\n", warmup.wall_time_seconds)
    @printf("steady_state_mean_seconds=%.9f\n", overall.mean_seconds)
    @printf("peak_rss_mib=%.3f\n", peak_rss / 2.0^20)
    println("output_directory=$(relpath(OUTPUT_DIR, ROOT))")
end

main()
