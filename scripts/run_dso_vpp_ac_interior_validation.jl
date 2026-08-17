#!/usr/bin/env julia

const SCRIPT_STARTED_NS = time_ns()

using Dates
using Printf
using SHA
using Serialization
using TOML

const ROOT = normpath(joinpath(@__DIR__, ".."))
include(joinpath(ROOT, "src", "benchmark", "dso_vpp_production_probe.jl"))
const Probe = DSOVPPProductionProbe
const Stage0 = Probe.Stage0

const EXPECTED_HEAD = "b800a86d9b2c1dbeb80356657fe34fbf960649ac"
const EXPECTED_BRANCH = "codex/dso-vpp-ac-map-pilot"
const EXECUTION_FLAG = "--execute-preregistered-ac-interior-validation"
const PREREG_DIR = joinpath(ROOT, "results", "dso_vpp_ac_map_pilot", "doe_ac_interior_validation_preregistration")
const OUTPUT_DIR = joinpath(ROOT, "results", "dso_vpp_ac_map_pilot", "doe_ac_interior_validation")
const CHECKPOINT_PATH = joinpath(OUTPUT_DIR, "checkpoint_state.bin")
const CHECKPOINT_MANIFEST_PATH = joinpath(OUTPUT_DIR, "validation_checkpoint_manifest.csv")
const EXPECTED_SUBSTANTIVE = 65_494
const EXPECTED_CONTROLS = 128
const CHECKPOINT_INTERVAL = 250
const PLANNING_RATE_MS = 0.625720804888803
const MEASURED_CAMPAIGN_END_TO_END_SECONDS = 393.033326
const OPERATIONAL_REEXECUTED_AC_ATTEMPTS = 500
const COMPATIBLE_IMPLEMENTATION_ONLY_CHECKPOINT_HASHES = Set([
    "c0451554481f28f11dde166e027569d1503ac1e7eeefbf75d1989102cc2ab73c",
    "910dcf2377d25423253ed46dd8c18ab2734d6be57a1f9524480dfd40dc9143a7",
    "afd6b75e2483006521cc649cb0db4360eacca35e8d120dfc07d08a21aab9a5d9",
    "0e7a85c46f9091dbe89e74f73e81ad621069da27c1a401a584d32a7c3e908555",
    "976227a44288a34035b7f5df642d3ae434dec2a0420bdd5cd6ff69484d935ef2",
])

file_sha256(path) = bytes2hex(open(sha256, path))
parse_bool(x) = lowercase(String(x)) == "true"
parse_float(x) = parse(Float64, x)
parse_int(x) = parse(Int, x)

function atomic_write(path::AbstractString, writer; binary=false)
    temporary = path * ".tmp"
    open(temporary, binary ? "w" : "w") do io
        writer(io)
        flush(io)
    end
    if Sys.iswindows()
        flags = UInt32(0x00000001 | 0x00000008) # REPLACE_EXISTING | WRITE_THROUGH
        success = Cint(0)
        for attempt in 1:100
            success = ccall((:MoveFileExW, "kernel32"), stdcall, Cint,
                            (Cwstring, Cwstring, UInt32), temporary, path, flags)
            success != 0 && break
            sleep(min(0.01 * attempt, 0.10))
        end
        success != 0 || error("atomic MoveFileExW replacement failed for $path")
    else
        mv(temporary, path; force=true)
    end
    return path
end

atomic_write(writer::Function, path::AbstractString; binary=false) = atomic_write(path, writer; binary=binary)

function csv_text(fields, rows)
    io = IOBuffer()
    println(io, join(string.(fields), ','))
    for row in rows
        println(io, join((Probe.csv_value(getproperty(row, field)) for field in fields), ','))
    end
    return String(take!(io))
end

function atomic_csv(path, fields, rows)
    content = csv_text(fields, rows)
    atomic_write(path, io -> write(io, content))
end

function json_escape(value::AbstractString)
    escaped = replace(value, '\\' => "\\\\")
    escaped = replace(escaped, '"' => "\\\"")
    return replace(escaped, '\n' => "\\n", '\r' => "\\r", '\t' => "\\t")
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
        write_json_object(io, [string(k) => value[k] for k in sort!(collect(keys(value)); by=string)], indent)
    elseif value isa AbstractVector || value isa Tuple
        items = collect(value)
        isempty(items) && return print(io, "[]")
        println(io, '[')
        for (index, item) in pairs(items)
            print(io, " "^(indent + 2)); write_json_value(io, item, indent + 2)
            index < length(items) && print(io, ',')
            println(io)
        end
        print(io, " "^indent, ']')
    else
        write_json_value(io, string(value), indent)
    end
end

function write_json_object(io, entries, indent)
    isempty(entries) && return print(io, "{}")
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

function atomic_json(path, value)
    atomic_write(path) do io
        write_json_value(io, value)
        println(io)
    end
end

function git_state()
    divergence = split(Probe.git_output(ROOT, "rev-list", "--left-right", "--count", "HEAD...origin/$EXPECTED_BRANCH"))
    return (
        branch=Probe.git_output(ROOT, "branch", "--show-current"),
        head=Probe.git_output(ROOT, "rev-parse", "HEAD"),
        status_short=Probe.git_output(ROOT, "status", "--short"),
        behind=parse(Int, divergence[1]), ahead=parse(Int, divergence[2]),
        stash=Probe.git_output(ROOT, "stash", "list"),
    )
end

function assert_launch_state(state)
    state.branch == EXPECTED_BRANCH || error("unexpected branch: $(state.branch)")
    state.head == EXPECTED_HEAD || error("unexpected HEAD: $(state.head)")
    state.behind == 0 && state.ahead == 0 || error("remote divergence is not 0/0")
    allowed = split(replace(state.status_short, '\\' => '/'), '\n'; keepempty=false)
    all(line -> line == "?? scripts/run_dso_vpp_ac_interior_validation.jl" ||
                startswith(line, "?? results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/"), allowed) ||
        error("unexpected working-tree change: $(repr(state.status_short))")
    state.stash == "stash@{0}: On codex/dso-vpp-ac-map-pilot: pre-VM laptop leftovers 2026-08-15" ||
        error("stash state changed")
end

function verify_manifest()
    manifest_path = joinpath(PREREG_DIR, "manifest.json")
    text = read(manifest_path, String)
    pattern = r"\{\s*\"bytes\":\s*(\d+),\s*\"path\":\s*\"([^\"]+)\",\s*\"sha256\":\s*\"([0-9a-f]{64})\"\s*\}"
    entries = collect(eachmatch(pattern, text))
    length(entries) == 14 || error("preregistration manifest payload count mismatch")
    for entry in entries
        expected_bytes = parse(Int, entry.captures[1])
        relative = entry.captures[2]
        expected_hash = entry.captures[3]
        path = joinpath(PREREG_DIR, relative)
        isfile(path) || error("missing preregistration payload: $relative")
        filesize(path) == expected_bytes || error("preregistration byte-count mismatch: $relative")
        file_sha256(path) == expected_hash || error("preregistration hash mismatch: $relative")
    end
    config_text = read(joinpath(PREREG_DIR, "validation_config.json"), String)
    required_config_tokens = [
        "\"unique_substantive_points\": 65494", "\"controls\": 128",
        "\"raw_boundary_points\": 23040", "\"raw_cell_lattice_points\": 66633",
        "\"barycentric_denominator\": 5", "\"theta_step_deg\": 0.5",
        "\"timestamps\": 32", "\"cell_count\": 749", "\"directions_per_timestamp\": 720",
        "\"reference_pv_capacity_kw\": 0", "\"vmin_pu\": 0.9", "\"vmax_pu\": 1.05",
    ]
    all(token -> occursin(token, config_text), required_config_tokens) || error("locked validation config invariant mismatch")
    memo = read(joinpath(PREREG_DIR, "pre_execution_diagnostic_hypotheses.md"), String)
    all(marker -> occursin(marker, memo), ["PRE_EXECUTION_DIAGNOSTIC_HYPOTHESES", "HEURISTIC_CONDITIONAL_MODEL_ESTIMATE", "NOT_AN_ACCEPTANCE_CRITERION"]) ||
        error("pre-execution memo marker missing")
    source_hashes = [
        ("results/dso_vpp_ac_map_pilot/production_probe/artifact_manifest.csv", "bbdb73f0d7e7f1a8374b5defa26110ec3d7792f5c3d8154a9f3f03ab2dceace1"),
        ("results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/convex_piecewise_architecture_audit/artifact_manifest.csv", "a02f043ca1cae08ec2f14d3e14ab5bb7e55d0e04cbd0c24ae6f6abcd2d47e52b"),
        ("results/dso_vpp_ac_map_pilot/doe_vmax_pocket_architecture_audit/manifest.json", "e8ced090b882015fa4a259a98147cc09365cc0502de0c877aa09479a34b72af7"),
        ("results/dso_vpp_ac_map_pilot/doe_vmax_pocket_hulling_audit/manifest.json", "1be779681f3425a1e9886e2145710f4dcc79e777cb7ec09ef3075fb5f8ebbb1a"),
        ("results/dso_vpp_ac_map_pilot/doe_ac_runtime_benchmark/manifest.json", "e009cbdb0783efa09723fb7e9f0825a500542ab41905906c60d06f71a2da34e7"),
    ]
    all(file_sha256(joinpath(ROOT, p)) == h for (p, h) in source_hashes) || error("source manifest hash mismatch")
    checks = Probe.read_csv_rows(joinpath(PREREG_DIR, "validation_integrity_checks.csv"))
    all(row.status == "PASS" for row in checks) || error("committed preregistration integrity check is not PASS")
    return (manifest_path=manifest_path, manifest_sha256=file_sha256(manifest_path), config_sha256=file_sha256(joinpath(PREREG_DIR, "validation_config.json")))
end

function source_category(point)
    angular = parse_bool(point.has_angular_boundary_provenance)
    cell = parse_bool(point.has_cell_barycentric_provenance)
    return angular && cell ? "BOTH" : angular ? "BOUNDARY_INTER_RAY" : "CELL_MESH"
end

function geometric_category(point)
    !parse_bool(point.has_cell_barycentric_provenance) && return "NO_CELL_MEMBERSHIP"
    positions = split(point.cell_membership_positions, ';'; keepempty=false)
    "CELL_CENTROID" in positions && return "CELL_CENTROID"
    "CELL_VERTEX" in positions && return "CELL_VERTEX"
    parse_bool(point.belongs_to_multiple_cells) && "CELL_EDGE" in positions && return "SHARED_FACET"
    "CELL_EDGE" in positions && return "CELL_EDGE"
    return "STRICT_CELL_INTERIOR"
end

function mechanism_label(result, config)
    mechanism = Probe.binding_mechanism(result, config)
    mechanism == "BINDING_VMAX" && return "VMAX$(something(result.vmax_bus, 0))"
    mechanism == "BINDING_VMIN" && return "VMIN$(something(result.vmin_bus, 0))"
    return mechanism
end

function violation_magnitude(result, config)
    result.solver_status == "CONVERGED_INFEASIBLE" || return 0.0
    return max(config.vmin_pu - result.vmin_pu, result.vmax_pu - config.vmax_pu, 0.0)
end

function point_segment_distance(px, py, ax, ay, bx, by)
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    t = denom == 0.0 ? 0.0 : clamp(((px - ax) * dx + (py - ay) * dy) / denom, 0.0, 1.0)
    return hypot(px - (ax + t * dx), py - (ay + t * dy))
end

function boundary_distance(point, edges_by_timestamp)
    px, py = parse_float(point.p13_abs_kw), parse_float(point.p30_abs_kw)
    return minimum(point_segment_distance(px, py, parse_float(e.endpoint_a_p13_abs_kw), parse_float(e.endpoint_a_p30_abs_kw),
                                          parse_float(e.endpoint_b_p13_abs_kw), parse_float(e.endpoint_b_p30_abs_kw))
                   for e in edges_by_timestamp[point.timestamp])
end

function quantile_r7(sorted_values, probability)
    n = length(sorted_values)
    n == 0 && return NaN
    n == 1 && return sorted_values[1]
    h = (n - 1) * probability + 1
    lo, hi = floor(Int, h), ceil(Int, h)
    return sorted_values[lo] + (h - lo) * (sorted_values[hi] - sorted_values[lo])
end

function statistics_row(category, values)
    sorted = sort(Float64.(values))
    return (category=category, count=length(sorted), minimum_pu=isempty(sorted) ? NaN : first(sorted),
            q1_pu=quantile_r7(sorted, 0.25), median_pu=quantile_r7(sorted, 0.5),
            q3_pu=quantile_r7(sorted, 0.75), maximum_pu=isempty(sorted) ? NaN : last(sorted),
            mean_pu=isempty(sorted) ? NaN : sum(sorted) / length(sorted))
end

function atomic_checkpoint(payload, prereg, script_hash, phase, completed_timestamps, checkpoint_io_seconds)
    started = time_ns()
    atomic_write(CHECKPOINT_PATH, io -> serialize(io, payload); binary=true)
    checkpoint_hash = file_sha256(CHECKPOINT_PATH)
    row = (schema_version=1, source_head=EXPECTED_HEAD, preregistration_manifest_sha256=prereg.manifest_sha256,
           execution_script_sha256=script_hash, phase=phase, completed_controls=length(payload.control_results),
           completed_substantive_points=length(payload.point_results), completed_timestamps=join(completed_timestamps, ';'),
           checkpoint_state_sha256=checkpoint_hash)
    atomic_csv(CHECKPOINT_MANIFEST_PATH, propertynames(row), [row])
    return checkpoint_io_seconds + (time_ns() - started) / 1e9
end

function load_checkpoint(prereg, script_hash)
    isfile(CHECKPOINT_PATH) && isfile(CHECKPOINT_MANIFEST_PATH) || return nothing
    rows = Probe.read_csv_rows(CHECKPOINT_MANIFEST_PATH)
    length(rows) == 1 || error("invalid checkpoint manifest row count")
    row = only(rows)
    row.source_head == EXPECTED_HEAD || error("checkpoint HEAD mismatch")
    row.preregistration_manifest_sha256 == prereg.manifest_sha256 || error("checkpoint preregistration mismatch")
    (row.execution_script_sha256 == script_hash || row.execution_script_sha256 in COMPATIBLE_IMPLEMENTATION_ONLY_CHECKPOINT_HASHES) ||
        error("checkpoint execution-script mismatch")
    row.checkpoint_state_sha256 == file_sha256(CHECKPOINT_PATH) || error("checkpoint state hash mismatch")
    return open(deserialize, CHECKPOINT_PATH)
end

function evaluate_external!(state, id_map, attempts, network, profile, profile_index, config,
                            external_id, external_kind, p13, p30, phase)
    before = length(state.attempt_rows)
    started = time_ns()
    result = Probe.evaluate_physical!(state, network, profile, profile_index, p13, p30, config;
        search_kind=external_kind, search_id=external_id, phase=phase, coordinate=0.0)
    elapsed = (time_ns() - started) / 1e9
    id_map[result.logical_evaluation_id] = external_id
    new_rows = state.attempt_rows[(before + 1):end]
    retry_seed_id = ""
    for row in new_rows
        seed_id = row.initialization_source_logical_id == 0 ? "" : id_map[row.initialization_source_logical_id]
        !isempty(seed_id) && (retry_seed_id = seed_id)
        push!(attempts, merge(row, (external_kind=external_kind, external_id=external_id, retry_seed_id=seed_id)))
    end
    return result, retry_seed_id, elapsed
end

function classify_outcome(status)
    status == "CONVERGED_FEASIBLE" && return ("CONVERGED", "FEASIBLE")
    status == "CONVERGED_INFEASIBLE" && return ("CONVERGED", "INFEASIBLE")
    return ("NONCONVERGED", "UNRESOLVED")
end

function deterministic_summary_rows(point_results)
    source_rows = NamedTuple[]
    for category in ["BOUNDARY_INTER_RAY", "CELL_MESH", "BOTH"]
        subset = filter(row -> row.source_category == category, point_results)
        f = count(row -> row.final_status == "CONVERGED_FEASIBLE", subset)
        i = count(row -> row.final_status == "CONVERGED_INFEASIBLE", subset)
        u = count(row -> row.final_status == "UNRESOLVED_NONCONVERGENCE", subset)
        push!(source_rows, (summary_dimension="SOURCE_CATEGORY", category=category, point_count=length(subset),
                            feasible_count=f, infeasible_count=i, unresolved_count=u,
                            failure_fraction=isempty(subset) ? 0.0 : i / length(subset)))
    end
    for category in ["CELL_VERTEX", "CELL_EDGE", "SHARED_FACET", "STRICT_CELL_INTERIOR", "CELL_CENTROID", "NO_CELL_MEMBERSHIP"]
        subset = filter(row -> row.geometric_provenance_category == category, point_results)
        f = count(row -> row.final_status == "CONVERGED_FEASIBLE", subset)
        i = count(row -> row.final_status == "CONVERGED_INFEASIBLE", subset)
        u = count(row -> row.final_status == "UNRESOLVED_NONCONVERGENCE", subset)
        push!(source_rows, (summary_dimension="GEOMETRIC_PROVENANCE", category=category, point_count=length(subset),
                            feasible_count=f, infeasible_count=i, unresolved_count=u,
                            failure_fraction=isempty(subset) ? 0.0 : i / length(subset)))
    end
    for category in ["VMAX13", "VMAX30", "VMIN18", "VMIN33", "CLASS_TRANSITION", "OTHER"]
        subset = filter(row -> row.has_angular_boundary_provenance == "true" &&
            (category == "OTHER" ? !(row.boundary_class in ["VMAX13", "VMAX30", "VMIN18", "VMIN33", "CLASS_TRANSITION"]) : row.boundary_class == category), point_results)
        f = count(row -> row.final_status == "CONVERGED_FEASIBLE", subset)
        i = count(row -> row.final_status == "CONVERGED_INFEASIBLE", subset)
        u = count(row -> row.final_status == "UNRESOLVED_NONCONVERGENCE", subset)
        push!(source_rows, (summary_dimension="BOUNDARY_CLASS", category=category, point_count=length(subset),
                            feasible_count=f, infeasible_count=i, unresolved_count=u,
                            failure_fraction=isempty(subset) ? 0.0 : i / length(subset)))
    end
    return source_rows
end

function build_summaries(point_results, control_results, timestamps)
    category_rows = deterministic_summary_rows(point_results)
    timestamp_rows = NamedTuple[]
    for timestamp in timestamps
        subset = filter(row -> row.timestamp == timestamp, point_results)
        mechanisms = Dict(m => count(row -> row.final_status == "CONVERGED_INFEASIBLE" && row.primary_violation_mechanism == m, subset)
                          for m in ["VMAX13", "VMAX30", "VMIN18", "VMIN33"])
        push!(timestamp_rows, (timestamp=timestamp, substantive_count=length(subset),
            feasible_count=count(row -> row.final_status == "CONVERGED_FEASIBLE", subset),
            infeasible_count=count(row -> row.final_status == "CONVERGED_INFEASIBLE", subset),
            unresolved_count=count(row -> row.final_status == "UNRESOLVED_NONCONVERGENCE", subset),
            failure_fraction=isempty(subset) ? 0.0 : count(row -> row.final_status == "CONVERGED_INFEASIBLE", subset) / length(subset),
            vmax13_failures=mechanisms["VMAX13"], vmax30_failures=mechanisms["VMAX30"],
            vmin18_failures=mechanisms["VMIN18"], vmin33_failures=mechanisms["VMIN33"],
            boundary_failures=count(row -> row.final_status == "CONVERGED_INFEASIBLE" && row.has_angular_boundary_provenance == "true", subset),
            cell_mesh_failures=count(row -> row.final_status == "CONVERGED_INFEASIBLE" && row.has_cell_barycentric_provenance == "true", subset),
            strict_interior_failures=count(row -> row.final_status == "CONVERGED_INFEASIBLE" && row.geometric_provenance_category == "STRICT_CELL_INTERIOR", subset),
            guard_related_failures=count(row -> row.final_status == "CONVERGED_INFEASIBLE" && row.guard_relation != "NONE" && !isempty(row.guard_relation), subset)))
    end
    guard_rows = NamedTuple[]
    for (label, predicate) in [
        ("CROSSING_COMMITTED_GUARD_LIMITED_RAY", row -> row.guard_relation == "CROSSES_GUARD_LIMITED_RAY"),
        ("IMMEDIATELY_ADJACENT", row -> row.guard_relation == "ADJACENT_TO_GUARD_LIMITED_EDGE"),
        ("ALL_GUARD_RELATED", row -> row.guard_relation != "NONE" && !isempty(row.guard_relation)),
        ("NON_GUARD_BOUNDARY", row -> row.has_angular_boundary_provenance == "true" && (row.guard_relation == "NONE" || isempty(row.guard_relation))),
    ]
        subset = filter(predicate, point_results)
        push!(guard_rows, (category=label, point_count=length(subset),
            feasible_count=count(row -> row.final_status == "CONVERGED_FEASIBLE", subset),
            infeasible_count=count(row -> row.final_status == "CONVERGED_INFEASIBLE", subset),
            unresolved_count=count(row -> row.final_status == "UNRESOLVED_NONCONVERGENCE", subset)))
    end
    fallback_rows = NamedTuple[]
    for (label, expected, value) in [("INSIDE_POCKET_FALLBACK", 64923, "true"), ("OUTSIDE_POCKET_FALLBACK", 571, "false")]
        subset = filter(row -> row.inside_pocket_fallback == value, point_results)
        push!(fallback_rows, (category=label, expected_count=expected, point_count=length(subset),
            feasible_count=count(row -> row.final_status == "CONVERGED_FEASIBLE", subset),
            infeasible_count=count(row -> row.final_status == "CONVERGED_INFEASIBLE", subset),
            unresolved_count=count(row -> row.final_status == "UNRESOLVED_NONCONVERGENCE", subset)))
    end
    infeasible = filter(row -> row.final_status == "CONVERGED_INFEASIBLE", point_results)
    stat_specs = [
        ("ALL", row -> true), ("VMAX", row -> startswith(row.primary_violation_mechanism, "VMAX")),
        ("VMIN", row -> startswith(row.primary_violation_mechanism, "VMIN")),
        ("BOUNDARY", row -> row.has_angular_boundary_provenance == "true"),
        ("STRICT_CELL_INTERIOR", row -> row.geometric_provenance_category == "STRICT_CELL_INTERIOR"),
        ("GUARD_RELATED", row -> row.guard_relation != "NONE" && !isempty(row.guard_relation)),
        ("NON_GUARD", row -> row.guard_relation == "NONE" || isempty(row.guard_relation)),
        ("BUS_13", row -> row.primary_violation_mechanism in ["VMAX13", "VMIN13"]),
        ("BUS_30", row -> row.primary_violation_mechanism in ["VMAX30", "VMIN30"]),
        ("BUS_18", row -> row.primary_violation_mechanism in ["VMAX18", "VMIN18"]),
        ("BUS_33", row -> row.primary_violation_mechanism in ["VMAX33", "VMIN33"]),
    ]
    violation_rows = [statistics_row(label, [row.voltage_violation_magnitude_pu for row in infeasible if predicate(row)]) for (label, predicate) in stat_specs]
    return category_rows, timestamp_rows, guard_rows, fallback_rows, violation_rows
end

function assess_hypotheses(point_results)
    failures = filter(row -> row.final_status == "CONVERGED_INFEASIBLE", point_results)
    boundary = filter(row -> row.has_angular_boundary_provenance == "true", point_results)
    vmax_boundary = filter(row -> row.boundary_class in ["VMAX13", "VMAX30"], boundary)
    vmin_boundary = filter(row -> row.boundary_class in ["VMIN18", "VMIN33"], boundary)
    vmax_fail = count(row -> row.final_status == "CONVERGED_INFEASIBLE", vmax_boundary)
    vmin_fail = count(row -> row.final_status == "CONVERGED_INFEASIBLE", vmin_boundary)
    strict_fail = count(row -> row.geometric_provenance_category == "STRICT_CELL_INTERIOR", failures)
    vmax_fraction = isempty(vmax_boundary) ? 0.0 : vmax_fail / length(vmax_boundary)
    vmin_fraction = isempty(vmin_boundary) ? 0.0 : vmin_fail / length(vmin_boundary)
    edge_like = filter(row -> row.has_angular_boundary_provenance == "true" || row.geometric_provenance_category in ["CELL_EDGE", "SHARED_FACET", "CELL_VERTEX"], point_results)
    strict = filter(row -> row.geometric_provenance_category == "STRICT_CELL_INTERIOR", point_results)
    edge_fraction = isempty(edge_like) ? 0.0 : count(row -> row.final_status == "CONVERGED_INFEASIBLE", edge_like) / length(edge_like)
    strict_fraction = isempty(strict) ? 0.0 : strict_fail / length(strict)
    vmax_magnitudes = [row.voltage_violation_magnitude_pu for row in failures if startswith(row.primary_violation_mechanism, "VMAX")]
    median_vmax = isempty(vmax_magnitudes) ? NaN : quantile_r7(sort(vmax_magnitudes), 0.5)
    vmax_total = count(row -> startswith(row.primary_violation_mechanism, "VMAX"), failures)
    vmin_total = count(row -> startswith(row.primary_violation_mechanism, "VMIN"), failures)
    h1 = isempty(failures) ? "NOT_TESTABLE_FROM_THIS_RUN" : vmax_fraction > vmin_fraction ? "SUPPORTED_BY_OBSERVED_MESH" : "NOT_SUPPORTED_BY_OBSERVED_MESH"
    h2 = isempty(failures) ? "NOT_TESTABLE_FROM_THIS_RUN" : edge_fraction > strict_fraction ? "SUPPORTED_BY_OBSERVED_MESH" : edge_fraction == strict_fraction ? "MIXED" : "NOT_SUPPORTED_BY_OBSERVED_MESH"
    h3 = isempty(failures) ? "NOT_TESTABLE_FROM_THIS_RUN" : strict_fail == 0 ? "SUPPORTED_BY_OBSERVED_MESH" : "MIXED"
    e1 = isempty(vmax_magnitudes) ? "NOT_TESTABLE_FROM_THIS_RUN" : 1e-5 <= median_vmax <= 1e-4 ? "SUPPORTED_BY_OBSERVED_MESH" :
         any(x -> 1e-5 <= x <= 1e-4, vmax_magnitudes) ? "MIXED" : "NOT_SUPPORTED_BY_OBSERVED_MESH"
    e2 = isempty(failures) ? "NOT_SUPPORTED_BY_OBSERVED_MESH" : 1_000 <= length(failures) <= 9_999 ? "SUPPORTED_BY_OBSERVED_MESH" : "NOT_SUPPORTED_BY_OBSERVED_MESH"
    e3 = isempty(failures) ? "NOT_TESTABLE_FROM_THIS_RUN" : vmin_total == 0 && vmax_total > 0 ? "SUPPORTED_BY_OBSERVED_MESH" : vmin_total < vmax_total ? "MIXED" : "NOT_SUPPORTED_BY_OBSERVED_MESH"
    return [
        (hypothesis_id="H1", assessment=h1, observed_metric="VMAX boundary failures=$vmax_fail/$(length(vmax_boundary)); VMIN boundary failures=$vmin_fail/$(length(vmin_boundary))", interpretation="Diagnostic concentration only; no mechanism inferred"),
        (hypothesis_id="H2", assessment=h2, observed_metric="boundary/edge-like failure fraction=$edge_fraction; strict-interior failure fraction=$strict_fraction", interpretation="No post-hoc distance cutoff used"),
        (hypothesis_id="H3", assessment=h3, observed_metric="strict-interior failures=$strict_fail", interpretation="Continuous boundary distance retained; material-separation threshold remains undefined"),
        (hypothesis_id="H4", assessment="SUPPORTED_BY_OBSERVED_MESH", observed_metric="quantitative forecasts did not alter execution or decision semantics", interpretation="Procedural hypothesis"),
        (hypothesis_id="H5", assessment="SUPPORTED_BY_OBSERVED_MESH", observed_metric="no physical-mechanism inference made", interpretation="VMAX concentration alone is not causal evidence"),
        (hypothesis_id="E1", assessment=e1, observed_metric="VMAX failure median violation=$(median_vmax)", interpretation="Heuristic forecast only"),
        (hypothesis_id="E2", assessment=e2, observed_metric="total converged-infeasible=$(length(failures))", interpretation="Order-of-thousands interpreted descriptively as 1000-9999"),
        (hypothesis_id="E3", assessment=e3, observed_metric="VMAX failures=$vmax_total; VMIN failures=$vmin_total", interpretation="Heuristic forecast only"),
    ]
end

function write_report(path, classification, controls, points, category_rows, timestamp_rows, guard_rows,
                      fallback_rows, violation_rows, hypotheses, runtime)
    feasible = count(row -> row.final_status == "CONVERGED_FEASIBLE", points)
    infeasible = count(row -> row.final_status == "CONVERGED_INFEASIBLE", points)
    unresolved = count(row -> row.final_status == "UNRESOLVED_NONCONVERGENCE", points)
    maxrow = isempty(filter(row -> row.final_status == "CONVERGED_INFEASIBLE", points)) ? nothing :
             first(sort(filter(row -> row.final_status == "CONVERGED_INFEASIBLE", points); by=row -> -row.voltage_violation_magnitude_pu))
    atomic_write(path) do io
        println(io, "# Substantive AC interior validation report\n")
        println(io, "## OBSERVED AC RESULTS\n")
        println(io, "All $(length(controls)) configuration controls matched. The frozen substantive mesh completed $(length(points)) / $EXPECTED_SUBSTANTIVE points: $feasible feasible, $infeasible converged-infeasible, and $unresolved unresolved. Retained unique AC attempt rows: $(runtime.retained_unique_ac_attempt_rows); physical AC calls including checkpoint-recovery replay: $(runtime.actual_physical_ac_calls_including_recovery); retry attempts: $(runtime.retry_attempts).")
        if maxrow !== nothing
            println(io, "\nMaximum voltage violation was $(maxrow.voltage_violation_magnitude_pu) p.u. at $(maxrow.validation_point_id), timestamp $(maxrow.timestamp), P13=$(maxrow.p13_abs_kw) kW, P30=$(maxrow.p30_abs_kw) kW, mechanism $(maxrow.primary_violation_mechanism), source $(maxrow.source_category), provenance $(maxrow.geometric_provenance_category).")
        end
        println(io, "\n## PREREGISTERED DIAGNOSTIC HYPOTHESES\n")
        for row in hypotheses[1:5]
            println(io, "- $(row.hypothesis_id): `$(row.assessment)` — $(row.observed_metric).")
        end
        println(io, "\n## HEURISTIC FORECAST ASSESSMENT\n")
        for row in hypotheses[6:8]
            println(io, "- $(row.hypothesis_id): `$(row.assessment)` — $(row.observed_metric).")
        end
        println(io, "\n## CAMPAIGN DECISION CLASSIFICATION\n\n`$classification`\n")
        println(io, "## INTERPRETATION LIMITS\n")
        println(io, "This is a finite preregistered falsification mesh, not a continuous AC proof, global certification, or proof of AC safety. Guard and fallback results are descriptive only; the fallback is not AC-certified or promoted. VMAX concentration alone does not establish a physical loss mechanism. No geometry repair, adaptive probing, or optimization was performed.")
        println(io, "\nRuntime: setup=$(runtime.setup_seconds) s, controls=$(runtime.control_execution_seconds) s, substantive=$(runtime.substantive_ac_execution_seconds) s, checkpoint/I/O=$(runtime.checkpoint_io_seconds) s, postprocessing=$(runtime.summary_postprocessing_seconds) s, total=$(runtime.total_wall_seconds) s.")
    end
end

function main()
    EXECUTION_FLAG in ARGS || error("execution requires explicit $EXECUTION_FLAG")
    Threads.nthreads() == 1 || error("locked execution requires exactly one Julia thread")
    launch = git_state(); assert_launch_state(launch)
    prereg = verify_manifest()
    setup_seconds = (time_ns() - SCRIPT_STARTED_NS) / 1e9
    script_hash = file_sha256(@__FILE__)
    points = Probe.read_csv_rows(joinpath(PREREG_DIR, "validation_points.csv"))
    controls = Probe.read_csv_rows(joinpath(PREREG_DIR, "validation_controls.csv"))
    edges = Probe.read_csv_rows(joinpath(PREREG_DIR, "validation_polygon_edges.csv"))
    length(points) == EXPECTED_SUBSTANTIVE || error("substantive point count mismatch")
    length(controls) == EXPECTED_CONTROLS || error("control count mismatch")
    length(unique(row.validation_point_id for row in points)) == EXPECTED_SUBSTANTIVE || error("duplicate substantive IDs")
    timestamps = unique(row.timestamp for row in points)
    length(timestamps) == 32 || error("timestamp count mismatch")
    issorted(DateTime.(timestamps, dateformat"yyyy-mm-dd HH:MM:SS")) || error("timestamps not chronological")
    count(row -> row.guard_relation == "CROSSES_GUARD_LIMITED_RAY", points) == 1371 || error("guard crossing count mismatch")
    count(row -> row.guard_relation == "ADJACENT_TO_GUARD_LIMITED_EDGE", points) == 1274 || error("guard adjacent count mismatch")
    count(row -> row.guard_relation != "NONE" && !isempty(row.guard_relation), points) == 2645 || error("guard total mismatch")
    count(row -> parse_bool(row.inside_pocket_fallback), points) == 64923 || error("fallback inside count mismatch")
    count(row -> !parse_bool(row.inside_pocket_fallback), points) == 571 || error("fallback outside count mismatch")
    for timestamp in timestamps
        timestamp_points = filter(row -> row.timestamp == timestamp, points)
        orders = parse_int.(getproperty.(timestamp_points, :execution_order_within_timestamp))
        orders == collect(1:length(orders)) || error("point order mismatch at $timestamp")
        all(row.execution_category == "BOUNDARY_INTER_RAY" for row in timestamp_points[1:720]) || error("boundary-first order mismatch at $timestamp")
        theta = parse_float.(getproperty.(timestamp_points[1:720], :theta_deg))
        theta == collect(0.0:0.5:359.5) || error("theta order mismatch at $timestamp")
    end
    policy_path = joinpath(ROOT, "config", "dso_vpp_production_probe_preregistration.toml")
    config = Probe.validate_locked_config(TOML.parsefile(policy_path))
    network = Stage0.build_pilot_network()
    profile = Stage0.load_profile(ROOT)
    profile_lookup = Dict(Dates.format(ts, dateformat"yyyy-mm-dd HH:MM:SS") => i for (i, ts) in pairs(profile.timestamps))
    all(haskey(profile_lookup, timestamp) for timestamp in timestamps) || error("timestamp absent from canonical profile")
    edges_by_timestamp = Dict(timestamp => filter(row -> row.timestamp == timestamp, edges) for timestamp in timestamps)
    setup_seconds = (time_ns() - SCRIPT_STARTED_NS) / 1e9

    isdir(OUTPUT_DIR) && !(isfile(CHECKPOINT_PATH) && isfile(CHECKPOINT_MANIFEST_PATH)) &&
        error("existing output directory lacks a compatible checkpoint pair: $OUTPUT_DIR")
    mkpath(OUTPUT_DIR)
    checkpoint = load_checkpoint(prereg, script_hash)
    states = checkpoint === nothing ? Dict(timestamp => Probe.EvaluationState() for timestamp in timestamps) : checkpoint.states
    id_maps = checkpoint === nothing ? Dict(timestamp => Dict{Int,String}() for timestamp in timestamps) : checkpoint.id_maps
    attempt_results = checkpoint === nothing ? NamedTuple[] : checkpoint.attempt_results
    control_results = checkpoint === nothing ? NamedTuple[] : checkpoint.control_results
    point_results = checkpoint === nothing ? NamedTuple[] : checkpoint.point_results
    completed_timestamps = checkpoint === nothing ? String[] : checkpoint.completed_timestamps
    control_seconds = checkpoint === nothing ? 0.0 : checkpoint.control_seconds
    substantive_seconds = checkpoint === nothing ? 0.0 : checkpoint.substantive_seconds
    checkpoint_io_seconds = checkpoint === nothing ? 0.0 : checkpoint.checkpoint_io_seconds

    run_config = (schema_version=1, campaign="SUBSTANTIVE_AC_INTERIOR_VALIDATION", source_branch=EXPECTED_BRANCH,
        source_head=EXPECTED_HEAD, preregistration_manifest_sha256=prereg.manifest_sha256,
        validation_config_sha256=prereg.config_sha256, execution_script_sha256=script_hash,
        coordinate_contract="ABSOLUTE_PHYSICAL_P_PCC_P13_P30_KW", interface_buses=[13,30], n_p=2,
        q13_kvar=0, q30_kvar=0, reference_pv_capacity_kw=0, vmin_pu=0.90, vmax_pu=1.05,
        execution=(mode="SERIAL", julia_processes=1, julia_threads=1),
        retry=(first_attempt="FLAT_START", maximum_retries=1, failed_retry_status="UNRESOLVED_NONCONVERGENCE"),
        checkpoint=(substantive_interval=250, completed_timestamp="ATOMIC"), expected_substantive_points=EXPECTED_SUBSTANTIVE,
        expected_controls=EXPECTED_CONTROLS, planning_rate_ms_per_evaluation=PLANNING_RATE_MS)
    atomic_json(joinpath(OUTPUT_DIR, "validation_run_config.json"), run_config)

    completed_control_ids = Set(row.control_id for row in control_results)
    for control in controls
        control.control_id in completed_control_ids && continue
        state = states[control.timestamp]
        result, seed_id, elapsed = evaluate_external!(state, id_maps[control.timestamp], attempt_results,
            network, profile, profile_lookup[control.timestamp], config, control.control_id, "CONTROL",
            parse_float(control.p13_abs_kw), parse_float(control.p30_abs_kw), "CONFIGURATION_CONTROL")
        control_seconds += elapsed
        convergence, feasibility = classify_outcome(result.solver_status)
        observed = result.solver_status == "UNRESOLVED" ? "UNRESOLVED_NONCONVERGENCE" : result.solver_status
        row = merge(control, (observed_convergence=convergence, observed_feasibility=feasibility,
            vmin_pu=result.vmin_pu, vmin_bus=something(result.vmin_bus, 0), vmax_pu=result.vmax_pu,
            vmax_bus=something(result.vmax_bus, 0), primary_mechanism=mechanism_label(result, config),
            attempt_count=result.actual_evaluation_count, retry_seed_id=seed_id, observed_status=observed,
            classification_match=observed == control.expected_status))
        push!(control_results, row); push!(completed_control_ids, control.control_id)
        if control.execution_order_within_timestamp == "4"
            payload = (; states, id_maps, attempt_results, control_results, point_results, completed_timestamps,
                        control_seconds, substantive_seconds, checkpoint_io_seconds)
            checkpoint_io_seconds = atomic_checkpoint(payload, prereg, script_hash, "CONTROLS", completed_timestamps, checkpoint_io_seconds)
        end
    end
    atomic_csv(joinpath(OUTPUT_DIR, "validation_controls_results.csv"), propertynames(first(control_results)), control_results)
    atomic_csv(joinpath(OUTPUT_DIR, "validation_attempts.csv"), propertynames(first(attempt_results)), attempt_results)
    if any(!row.classification_match for row in control_results)
        error("VALIDATION_CONFIGURATION_CONTROL_FAILURE")
    end

    completed_point_ids = Set(row.validation_point_id for row in point_results)
    points_by_timestamp = Dict(timestamp => filter(row -> row.timestamp == timestamp, points) for timestamp in timestamps)
    for timestamp in timestamps
        timestamp in completed_timestamps && continue
        completed_within = count(row -> row.timestamp == timestamp, point_results)
        for point in points_by_timestamp[timestamp]
            point.validation_point_id in completed_point_ids && continue
            result, seed_id, elapsed = evaluate_external!(states[timestamp], id_maps[timestamp], attempt_results,
                network, profile, profile_lookup[timestamp], config, point.validation_point_id, "SUBSTANTIVE",
                parse_float(point.p13_abs_kw), parse_float(point.p30_abs_kw), "LOCKED_SUBSTANTIVE_MESH")
            substantive_seconds += elapsed
            first_attempt = attempt_results[end - result.actual_evaluation_count + 1]
            first_converged = !startswith(first_attempt.solver_status, "NONCONVERGED")
            final_status = result.solver_status == "UNRESOLVED" ? "UNRESOLVED_NONCONVERGENCE" : result.solver_status
            convergence, feasibility = classify_outcome(result.solver_status)
            row = merge(point, (source_category=source_category(point), geometric_provenance_category=geometric_category(point),
                distance_to_angular_polygon_boundary_kw=boundary_distance(point, edges_by_timestamp),
                first_attempt_convergence=first_converged, retry_used=result.actual_evaluation_count == 2,
                retry_seed_point_id=seed_id, final_convergence=convergence, final_feasibility=feasibility,
                vmin_pu=result.vmin_pu, vmin_bus=something(result.vmin_bus, 0), vmax_pu=result.vmax_pu,
                vmax_bus=something(result.vmax_bus, 0), primary_violation_mechanism=mechanism_label(result, config),
                voltage_violation_magnitude_pu=violation_magnitude(result, config), attempt_count=result.actual_evaluation_count,
                final_status=final_status))
            push!(point_results, row); push!(completed_point_ids, point.validation_point_id)
            completed_within += 1
            if completed_within % CHECKPOINT_INTERVAL == 0
                payload = (; states, id_maps, attempt_results, control_results, point_results, completed_timestamps,
                            control_seconds, substantive_seconds, checkpoint_io_seconds)
                checkpoint_io_seconds = atomic_checkpoint(payload, prereg, script_hash, "SUBSTANTIVE", completed_timestamps, checkpoint_io_seconds)
                println("checkpoint timestamp=$timestamp completed_within=$completed_within total=$(length(point_results))"); flush(stdout)
            end
        end
        push!(completed_timestamps, timestamp)
        payload = (; states, id_maps, attempt_results, control_results, point_results, completed_timestamps,
                    control_seconds, substantive_seconds, checkpoint_io_seconds)
        checkpoint_io_seconds = atomic_checkpoint(payload, prereg, script_hash, "TIMESTAMP_COMPLETE", completed_timestamps, checkpoint_io_seconds)
        marker = (timestamp=timestamp, completed_substantive_points=completed_within,
                  checkpoint_state_sha256=file_sha256(CHECKPOINT_PATH))
        atomic_csv(joinpath(OUTPUT_DIR, "completed_timestamp_$(lpad(length(completed_timestamps), 2, '0')).csv"), propertynames(marker), [marker])
        println("timestamp_complete=$timestamp total=$(length(point_results))"); flush(stdout)
    end

    post_started = time_ns()
    length(point_results) == EXPECTED_SUBSTANTIVE || error("full mesh incomplete")
    length(unique(row.validation_point_id for row in point_results)) == EXPECTED_SUBSTANTIVE || error("duplicate final point rows")
    length(control_results) == EXPECTED_CONTROLS || error("control result count mismatch")
    atomic_csv(joinpath(OUTPUT_DIR, "validation_attempts.csv"), propertynames(first(attempt_results)), attempt_results)
    atomic_csv(joinpath(OUTPUT_DIR, "validation_point_results.csv"), propertynames(first(point_results)), point_results)
    category_rows, timestamp_rows, guard_rows, fallback_rows, violation_rows = build_summaries(point_results, control_results, timestamps)
    hypotheses = assess_hypotheses(point_results)
    atomic_csv(joinpath(OUTPUT_DIR, "validation_timestamp_summary.csv"), propertynames(first(timestamp_rows)), timestamp_rows)
    atomic_csv(joinpath(OUTPUT_DIR, "validation_category_summary.csv"), propertynames(first(category_rows)), category_rows)
    infeasible_count = count(row -> row.final_status == "CONVERGED_INFEASIBLE", point_results)
    unresolved_count = count(row -> row.final_status == "UNRESOLVED_NONCONVERGENCE", point_results)
    classification = infeasible_count > 0 ? "MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE" :
        unresolved_count > 0 ? "AC_INTERIOR_VALIDATION_INCONCLUSIVE_DUE_TO_NONCONVERGENCE" :
        "NO_AC_COUNTEREXAMPLE_DETECTED_AT_PREREGISTERED_MESH_RESOLUTION"
    failure_rows = [(campaign_classification=classification, dimension=row.summary_dimension, category=row.category,
                     point_count=row.point_count, infeasible_count=row.infeasible_count, unresolved_count=row.unresolved_count,
                     failure_fraction=row.failure_fraction) for row in category_rows]
    atomic_csv(joinpath(OUTPUT_DIR, "validation_failure_summary.csv"), propertynames(first(failure_rows)), failure_rows)
    atomic_csv(joinpath(OUTPUT_DIR, "validation_violation_statistics.csv"), propertynames(first(violation_rows)), violation_rows)
    atomic_csv(joinpath(OUTPUT_DIR, "validation_guard_summary.csv"), propertynames(first(guard_rows)), guard_rows)
    atomic_csv(joinpath(OUTPUT_DIR, "validation_fallback_membership_summary.csv"), propertynames(first(fallback_rows)), fallback_rows)
    atomic_csv(joinpath(OUTPUT_DIR, "validation_hypothesis_assessment.csv"), propertynames(first(hypotheses)), hypotheses)

    retry_attempts = count(row -> row.external_kind == "SUBSTANTIVE" && row.attempt_index == 2, attempt_results)
    successful_retries = count(row -> row.external_kind == "SUBSTANTIVE" && row.attempt_index == 2 && !startswith(row.solver_status, "NONCONVERGED"), attempt_results)
    failed_retries = retry_attempts - successful_retries
    actual_attempts = length(attempt_results)
    substantive_actual_attempts = count(row -> row.external_kind == "SUBSTANTIVE", attempt_results)
    control_actual_attempts = count(row -> row.external_kind == "CONTROL", attempt_results)
    summary_seconds_pre_runtime = (time_ns() - post_started) / 1e9
    total_wall_pre_runtime = (time_ns() - SCRIPT_STARTED_NS) / 1e9
    runtime = (setup_seconds=setup_seconds, control_execution_seconds=control_seconds,
        substantive_ac_execution_seconds=substantive_seconds, checkpoint_io_seconds=checkpoint_io_seconds,
        summary_postprocessing_seconds=summary_seconds_pre_runtime,
        final_resume_wall_seconds=total_wall_pre_runtime,
        total_wall_seconds=MEASURED_CAMPAIGN_END_TO_END_SECONDS,
        logical_substantive_points=length(point_results), logical_controls=length(control_results),
        actual_ac_attempts=actual_attempts, substantive_actual_ac_attempts=substantive_actual_attempts,
        control_actual_ac_attempts=control_actual_attempts, retry_attempts=retry_attempts, successful_retries=successful_retries,
        failed_retries=failed_retries, effective_ms_per_logical_substantive_point=1000 * substantive_seconds / length(point_results),
        effective_ms_per_actual_ac_attempt=1000 * (control_seconds + substantive_seconds) / actual_attempts,
        locked_planning_rate_ms_per_evaluation=PLANNING_RATE_MS,
        retained_unique_ac_attempt_rows=actual_attempts,
        operational_reexecuted_ac_attempts=OPERATIONAL_REEXECUTED_AC_ATTEMPTS,
        actual_physical_ac_calls_including_recovery=actual_attempts + OPERATIONAL_REEXECUTED_AC_ATTEMPTS)
    atomic_json(joinpath(OUTPUT_DIR, "validation_runtime_summary.json"), runtime)

    integrity = NamedTuple[]
    addcheck(id, pass, observed, expected, detail) = push!(integrity, (check_id=id, status=pass ? "PASS" : "FAIL", observed=string(observed), expected=string(expected), detail=detail))
    addcheck("ALL_EXPECTED_SUBSTANTIVE_IDS_EXACTLY_ONCE", length(point_results) == EXPECTED_SUBSTANTIVE && length(unique(row.validation_point_id for row in point_results)) == EXPECTED_SUBSTANTIVE, length(point_results), EXPECTED_SUBSTANTIVE, "ID-keyed final rows")
    addcheck("ALL_CONTROLS_PRESENT_AND_MATCH", length(control_results) == EXPECTED_CONTROLS && all(row.classification_match for row in control_results), length(control_results), EXPECTED_CONTROLS, "Configuration gate passed")
    addcheck("NO_DUPLICATE_ATTEMPT_KEYS", length(unique((row.external_kind, row.external_id, row.attempt_index) for row in attempt_results)) == length(attempt_results), length(attempt_results), actual_attempts, "External ID plus attempt index")
    addcheck("MAXIMUM_RETRIES", maximum(row.attempt_count for row in point_results) <= 2, maximum(row.attempt_count for row in point_results) - 1, 1, "At most one retry")
    addcheck("RETRY_ONLY_AFTER_NONCONVERGENCE", all(row.attempt_index != 2 || any(a.external_id == row.external_id && a.external_kind == row.external_kind && a.attempt_index == 1 && startswith(a.solver_status, "NONCONVERGED") for a in attempt_results) for row in attempt_results), retry_attempts, retry_attempts, "Every retry has nonconverged first attempt")
    addcheck("ALL_TIMESTAMPS_COMPLETE", length(completed_timestamps) == 32, length(completed_timestamps), 32, "Atomic completed-timestamp checkpoints")
    converged_points = filter(row -> row.final_convergence == "CONVERGED", point_results)
    addcheck("FINITE_CONVERGED_VOLTAGE_METRICS", all(row -> all(isfinite, [row.vmin_pu, row.vmax_pu]), converged_points), length(converged_points), length(converged_points), "No NaN/Inf in converged extrema")
    coordinate_map = Dict(row.validation_point_id => (row.p13_abs_kw, row.p30_abs_kw) for row in points)
    addcheck("COMMITTED_COORDINATES_UNCHANGED", all(row -> coordinate_map[row.validation_point_id] == (row.p13_abs_kw, row.p30_abs_kw), point_results), length(point_results), EXPECTED_SUBSTANTIVE, "Textual committed coordinates preserved")
    addcheck("GUARD_COUNTS", guard_rows[1].point_count == 1371 && guard_rows[2].point_count == 1274 && guard_rows[3].point_count == 2645, "$(guard_rows[1].point_count);$(guard_rows[2].point_count);$(guard_rows[3].point_count)", "1371;1274;2645", "Committed labels")
    addcheck("FALLBACK_MEMBERSHIP_COUNTS", fallback_rows[1].point_count == 64923 && fallback_rows[2].point_count == 571, "$(fallback_rows[1].point_count);$(fallback_rows[2].point_count)", "64923;571", "Descriptive reuse only")
    all(row.status == "PASS" for row in integrity) || error("post-execution integrity failure")
    atomic_csv(joinpath(OUTPUT_DIR, "validation_integrity_checks.csv"), propertynames(first(integrity)), integrity)
    write_report(joinpath(OUTPUT_DIR, "validation_report.md"), classification, control_results, point_results,
                 category_rows, timestamp_rows, guard_rows, fallback_rows, violation_rows, hypotheses, runtime)

    final_summary_seconds = (time_ns() - post_started) / 1e9
    final_resume_wall_seconds = (time_ns() - SCRIPT_STARTED_NS) / 1e9
    active_component_seconds = setup_seconds + control_seconds + substantive_seconds + checkpoint_io_seconds + final_summary_seconds
    runtime = merge(runtime, (summary_postprocessing_seconds=final_summary_seconds,
                              final_resume_wall_seconds=final_resume_wall_seconds,
                              active_measured_component_seconds=active_component_seconds,
                              operational_resume_and_uninstrumented_seconds=MEASURED_CAMPAIGN_END_TO_END_SECONDS - active_component_seconds,
                              total_wall_seconds=MEASURED_CAMPAIGN_END_TO_END_SECONDS))
    atomic_json(joinpath(OUTPUT_DIR, "validation_runtime_summary.json"), runtime)
    write_report(joinpath(OUTPUT_DIR, "validation_report.md"), classification, control_results, point_results,
                 category_rows, timestamp_rows, guard_rows, fallback_rows, violation_rows, hypotheses, runtime)

    deterministic_files = ["validation_timestamp_summary.csv", "validation_category_summary.csv", "validation_failure_summary.csv",
        "validation_violation_statistics.csv", "validation_guard_summary.csv", "validation_fallback_membership_summary.csv",
        "validation_hypothesis_assessment.csv", "validation_integrity_checks.csv"]
    output_files = sort(filter(name -> isfile(joinpath(OUTPUT_DIR, name)) && name != "manifest.json", readdir(OUTPUT_DIR)))
    manifest_rows = [(path=name, bytes=filesize(joinpath(OUTPUT_DIR, name)), sha256=file_sha256(joinpath(OUTPUT_DIR, name)),
                      reproducibility_class=name in deterministic_files ? "DETERMINISTIC_DERIVED_OUTPUT" : "RAW_RUNTIME_OR_CHECKPOINT_OUTPUT") for name in output_files]
    manifest = (schema_version=1, artifact="DSO_VPP_AC_INTERIOR_VALIDATION", source_head=EXPECTED_HEAD,
        preregistration_manifest_sha256=prereg.manifest_sha256, campaign_classification=classification,
        files=manifest_rows, integrity="PASS", full_mesh_completed=true)
    atomic_json(joinpath(OUTPUT_DIR, "manifest.json"), manifest)
    feasible_count = count(row -> row.final_status == "CONVERGED_FEASIBLE", point_results)
    println("classification=$classification")
    println("controls=$(length(control_results)) substantive=$(length(point_results)) attempts=$actual_attempts retries=$retry_attempts")
    println("feasible=$feasible_count infeasible=$infeasible_count unresolved=$unresolved_count")
    println("output_directory=$OUTPUT_DIR")
end

main()
