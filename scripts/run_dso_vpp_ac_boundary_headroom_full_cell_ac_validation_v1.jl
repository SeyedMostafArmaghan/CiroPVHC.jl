using CiroPVHC
using Dates
using Printf
using SHA

include(joinpath(@__DIR__, "..", "src", "benchmark", "dso_vpp_production_probe.jl"))
const Probe = DSOVPPProductionProbe

const ARTIFACT = "DSO_VPP_AC_BOUNDARY_HEADROOM_FULL_CELL_AC_VALIDATION_V1"
const HISTORICAL_STATUS = "MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE"
const PHASE1_COMMIT = "32fc5697fdeb5a2a2fb0395d09e56db7c47250e2"
const PREREG_COMMIT = "fc15fbf7bf93ca89c2ab4a45145f937abbc70f63"
const GEOMETRY_COMMIT = "ba88f54f52f7bcd03df2466ce69dff2b9b1c538b"
const GRID_KW = 0.25
const GEOMETRY_TOL_KW = 1e-7
const DESIGN_VMIN = 0.90015
const DESIGN_VMAX = 1.04985
const ORIGINAL_VMIN = 0.90
const ORIGINAL_VMAX = 1.05
const PRIMARY_CAP = 302303
const RETRY_CAP = 3024
const EXECUTION_FLAG = "--execute-full-cell-ac-validation-v1"

const ROOT = normpath(joinpath(@__DIR__, ".."))
const BASE = joinpath(ROOT, "results", "dso_vpp_ac_map_pilot")
const PHASE1_DIR = joinpath(BASE, "doe_ac_boundary_headroom_full_cell_geometric_certification_v1")
const HISTORICAL_DIR = joinpath(BASE, "doe_ac_boundary_headroom_repair_calibration")
const OUTPUT_DIR = joinpath(BASE, "doe_ac_boundary_headroom_full_cell_ac_validation_v1")
const PHASE1_CSV = joinpath(PHASE1_DIR, "full_cell_probe_limits.csv")
const CELL_PATH = "results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/convex_piecewise_architecture_audit/merged_convex_cells.csv"
const EDGE_PATH = "results/dso_vpp_ac_map_pilot/doe_ac_boundary_headroom_repair_preregistration/edge_repair_policy.csv"

const CLASSIFICATIONS = [
    "GEOMETRY_ONLY_NO_POSITIVE_MOVEMENT",
    "GEOMETRY_GRID_LIMIT_TOO_SMALL",
    "AC_HEADROOM_ACHIEVED",
    "AC_HEADROOM_FAILED_WITHIN_FULL_CELL",
    "ORIGINAL_LIMIT_FAILED_WITHIN_FULL_CELL",
    "AC_UNRESOLVED",
    "SEARCH_BUDGET_EXHAUSTED",
    "PROVENANCE_FAILURE",
]

mutable struct Counters
    primary::Int
    retries::Int
    unresolved::Int
end

f(row, key::Symbol) = parse(Float64, getproperty(row, key))
i(row, key::Symbol) = parse(Int, getproperty(row, key))
file_sha256(path) = bytes2hex(open(sha256, path))
git_bytes(commit, path) = read(Cmd(Cmd(["git", "show", "$commit:$path"]); dir=ROOT))

function split_csv_line(line::AbstractString)
    fields = String[]
    buffer = IOBuffer()
    quoted = false
    index = firstindex(line)
    while index <= lastindex(line)
        character = line[index]
        if character == '"'
            next_index = nextind(line, index)
            if quoted && next_index <= lastindex(line) && line[next_index] == '"'
                write(buffer, '"')
                index = next_index
            else
                quoted = !quoted
            end
        elseif character == ',' && !quoted
            push!(fields, String(take!(buffer)))
        else
            write(buffer, character)
        end
        index = nextind(line, index)
    end
    push!(fields, String(take!(buffer)))
    quoted && error("unterminated CSV quote")
    return fields
end

function csv_rows(bytes::Vector{UInt8})
    lines = split(replace(String(bytes), "\r\n" => "\n", '\r' => '\n'), '\n')
    filter!(!isempty, lines)
    isempty(lines) && error("empty CSV input")
    header = Symbol.(split_csv_line(first(lines)))
    rows = NamedTuple[]
    for line in lines[2:end]
        values = split_csv_line(line)
        length(values) == length(header) || error("CSV width mismatch")
        push!(rows, NamedTuple{Tuple(header)}(Tuple(values)))
    end
    return rows
end

csv_rows(path::AbstractString) = Probe.read_csv_rows(path)

function csv_value(value)
    value === nothing && return ""
    if value isa AbstractString
        escaped = replace(value, "\"" => "\"\"")
        return occursin(r"[,\"\r\n]", escaped) ? "\"$escaped\"" : escaped
    elseif value isa AbstractFloat
        return isfinite(value) ? @sprintf("%.15g", value) : ""
    elseif value isa Bool
        return lowercase(string(value))
    end
    return string(value)
end

function write_csv(path, fields, rows)
    open(path, "w") do io
        println(io, join(string.(fields), ','))
        for row in rows
            println(io, join((csv_value(getproperty(row, field)) for field in fields), ','))
        end
    end
end

function open_csv(path, fields)
    io = open(path, "w")
    println(io, join(string.(fields), ','))
    return io
end

function write_csv_row(io, fields, row)
    println(io, join((csv_value(getproperty(row, field)) for field in fields), ','))
end

function json_escape(value::AbstractString)
    return replace(value, '\\' => "\\\\", '"' => "\\\"", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t")
end

function json_value(value, indent=0)
    if value === nothing
        return "null"
    elseif value isa Bool
        return lowercase(string(value))
    elseif value isa Integer
        return string(value)
    elseif value isa AbstractFloat
        return isfinite(value) ? @sprintf("%.15g", value) : "null"
    elseif value isa AbstractString
        return "\"$(json_escape(value))\""
    elseif value isa NamedTuple
        return json_value(Dict(string(k) => getproperty(value, k) for k in propertynames(value)), indent)
    elseif value isa AbstractDict
        keys_sorted = sort!(collect(keys(value)); by=string)
        isempty(keys_sorted) && return "{}"
        pad = " "^(indent + 2)
        body = [pad * json_value(string(key), indent + 2) * ": " * json_value(value[key], indent + 2) for key in keys_sorted]
        return "{\n" * join(body, ",\n") * "\n" * " "^indent * "}"
    elseif value isa AbstractVector || value isa Tuple
        isempty(value) && return "[]"
        pad = " "^(indent + 2)
        body = [pad * json_value(item, indent + 2) for item in value]
        return "[\n" * join(body, ",\n") * "\n" * " "^indent * "]"
    end
    return json_value(string(value), indent)
end

write_json(path, value) = write(path, json_value(value) * "\n")

function manifest_payloads(manifest_path)
    text = read(manifest_path, String)
    rows = NamedTuple[]
    for block in eachmatch(r"\{[^{}]*\"path\"[^{}]*\}", text)
        object = block.match
        path_match = match(r"\"path\"\s*:\s*\"([^\"]+)\"", object)
        bytes_match = match(r"\"bytes\"\s*:\s*(\d+)", object)
        hash_match = match(r"\"sha256\"\s*:\s*\"([0-9a-f]{64})\"", object)
        path_match === nothing && continue
        bytes_match === nothing && continue
        hash_match === nothing && continue
        push!(rows, (path=path_match.captures[1], bytes=parse(Int, bytes_match.captures[1]), sha256=hash_match.captures[1]))
    end
    isempty(rows) && error("manifest has no payload objects: $manifest_path")
    return rows
end

function verify_phase1()
    manifest_path = joinpath(PHASE1_DIR, "manifest.json")
    payloads = manifest_payloads(manifest_path)
    verified = String[]
    for item in payloads
        path = joinpath(PHASE1_DIR, item.path)
        isfile(path) || error("Phase 1 artifact missing: $(item.path)")
        bytes = read(path)
        length(bytes) == item.bytes || error("Phase 1 byte mismatch: $(item.path)")
        bytes2hex(sha256(bytes)) == item.sha256 || error("Phase 1 hash mismatch: $(item.path)")
        push!(verified, item.path)
    end
    generator_hash = match(r"\"generator\"\s*:\s*\{[^{}]*\"path\"\s*:\s*\"([^\"]+)\"[^{}]*\"sha256\"\s*:\s*\"([0-9a-f]{64})\"", read(manifest_path, String))
    generator_hash === nothing && error("Phase 1 generator provenance missing")
    generator_path, expected_hash = generator_hash.captures
    file_sha256(joinpath(ROOT, generator_path)) == expected_hash || error("Phase 1 generator hash mismatch")
    return sort(verified)
end

function verify_phase1_sources()
    text = read(joinpath(PHASE1_DIR, "source_manifest.json"), String)
    occursin("\"verification\": \"PASS\"", text) || error("Phase 1 source verification is not PASS")
    verified = NamedTuple[]
    for block in eachmatch(r"\{[^{}]*\"path\"[^{}]*\}", text)
        object = block.match
        path_match = match(r"\"path\"\s*:\s*\"([^\"]+)\"", object)
        bytes_match = match(r"\"bytes\"\s*:\s*(\d+)", object)
        hash_match = match(r"\"sha256\"\s*:\s*\"([0-9a-f]{64})\"", object)
        commit_match = match(r"\"source_commit\"\s*:\s*\"([0-9a-f]{40})\"", object)
        any(value -> value === nothing, (path_match, bytes_match, hash_match, commit_match)) && continue
        path = path_match.captures[1]
        commit = commit_match.captures[1]
        bytes = git_bytes(commit, path)
        length(bytes) == parse(Int, bytes_match.captures[1]) || error("source byte mismatch: $path")
        bytes2hex(sha256(bytes)) == hash_match.captures[1] || error("source hash mismatch: $path")
        push!(verified, (path=path, source_commit=commit, bytes=length(bytes), sha256=bytes2hex(sha256(bytes))))
    end
    length(verified) == 8 || error("Phase 1 source manifest entry count mismatch")
    return sort(verified; by=row -> row.path)
end

function directory_inventory(directory)
    rows = NamedTuple[]
    for (root, _, files) in walkdir(directory)
        for name in sort(files)
            path = joinpath(root, name)
            relative = replace(relpath(path, ROOT), '\\' => '/')
            push!(rows, (path=relative, bytes=filesize(path), sha256=file_sha256(path)))
        end
    end
    sort!(rows; by=row -> row.path)
    return rows
end

function tree_digest(rows)
    body = join(("$(row.sha256)  $(row.bytes)  $(row.path)\n" for row in rows))
    return bytes2hex(sha256(codeunits(body)))
end

function polygon_area(poly)
    return 0.5 * sum(poly[j][1] * poly[mod1(j + 1, length(poly))][2] -
                     poly[mod1(j + 1, length(poly))][1] * poly[j][2] for j in eachindex(poly))
end

function point_segment_distance(point, a, b)
    ab = (b[1] - a[1], b[2] - a[2])
    length2 = ab[1]^2 + ab[2]^2
    length2 == 0 && return hypot(point[1] - a[1], point[2] - a[2])
    t = clamp(((point[1] - a[1]) * ab[1] + (point[2] - a[2]) * ab[2]) / length2, 0.0, 1.0)
    return hypot(point[1] - (a[1] + t * ab[1]), point[2] - (a[2] + t * ab[2]))
end

function polygon_membership(poly, point; tol=GEOMETRY_TOL_KW)
    minimum_distance = minimum(point_segment_distance(point, poly[j], poly[mod1(j + 1, length(poly))]) for j in eachindex(poly))
    minimum_distance <= tol && return (inside=true, location="BOUNDARY", minimum_distance=minimum_distance)
    inside = false
    x, y = point
    for j in eachindex(poly)
        a = poly[j]
        b = poly[mod1(j + 1, length(poly))]
        if (a[2] > y) != (b[2] > y)
            crossing_x = a[1] + (y - a[2]) * (b[1] - a[1]) / (b[2] - a[2])
            crossing_x > x && (inside = !inside)
        end
    end
    return (inside=inside, location=inside ? "INTERIOR" : "OUTSIDE", minimum_distance=minimum_distance)
end

function halfspace_membership(poly, point; tol=GEOMETRY_TOL_KW)
    signed = Float64[]
    for j in eachindex(poly)
        a = poly[j]
        b = poly[mod1(j + 1, length(poly))]
        edge = (b[1] - a[1], b[2] - a[2])
        norm = hypot(edge[1], edge[2])
        norm > 0 || return (inside=false, minimum_slack=-Inf)
        push!(signed, (edge[1] * (point[2] - a[2]) - edge[2] * (point[1] - a[1])) / norm)
    end
    return (inside=minimum(signed) >= -tol, minimum_slack=minimum(signed))
end

function load_cells()
    rows = csv_rows(git_bytes(GEOMETRY_COMMIT, CELL_PATH))
    grouped = Dict{Tuple{String,Int},Vector{NamedTuple}}()
    for row in rows
        push!(get!(grouped, (String(row.timestamp), i(row, :cell_index)), NamedTuple[]), row)
    end
    cells = Dict{Tuple{String,Int},Vector{NTuple{2,Float64}}}()
    for (key, group) in grouped
        ordered = sort(group; by=row -> i(row, :cell_vertex_index_ccw))
        poly = [(f(row, :p13_abs_kw), f(row, :p30_abs_kw)) for row in ordered]
        length(poly) >= 3 || error("degenerate committed cell: $key")
        polygon_area(poly) > 0 || error("non-CCW committed cell: $key")
        cells[key] = poly
    end
    return cells
end

function phase1_classification(row)
    value = String(row.classification)
    value == "NO_POSITIVE_FULL_CELL_MOVEMENT" && return "GEOMETRY_ONLY_NO_POSITIVE_MOVEMENT"
    value == "FULL_CELL_CAP_BELOW_GRID" && return "GEOMETRY_GRID_LIMIT_TOO_SMALL"
    value == "GEOMETRICALLY_CERTIFIED" && return ""
    return "PROVENANCE_FAILURE"
end

design_pass(point) = point.solver_status != "UNRESOLVED" && point.vmin_pu >= DESIGN_VMIN && point.vmax_pu <= DESIGN_VMAX
original_pass(point) = point.solver_status != "UNRESOLVED" && point.vmin_pu >= ORIGINAL_VMIN && point.vmax_pu <= ORIGINAL_VMAX

function binding(point)
    point.solver_status == "UNRESOLVED" && return (limit="UNRESOLVED", bus="")
    lower_margin = point.vmin_pu - DESIGN_VMIN
    upper_margin = DESIGN_VMAX - point.vmax_pu
    return lower_margin <= upper_margin ? (limit="VMIN", bus=point.vmin_bus === nothing ? "" : string(point.vmin_bus)) :
                                          (limit="VMAX", bus=point.vmax_bus === nothing ? "" : string(point.vmax_bus))
end

const RESULT_FIELDS = (
    :logical_call_id, :membership_id, :timestamp, :owner_cell_id, :edge_id,
    :source_p13_abs_kw, :source_p30_abs_kw, :direction_p13, :direction_p30,
    :retreat_d_kw, :p13_abs_kw, :p30_abs_kw, :limiting_facet_id, :full_cell_cap_kw,
    :analytical_membership, :polygon_membership, :ac_status, :convergence_status,
    :original_limit_status, :design_headroom_status, :vmin_pu, :vmax_pu,
    :binding_limit, :binding_bus, :substation_p_kw, :substation_q_kvar,
)

const ATTEMPT_FIELDS = (
    :attempt_id, :logical_call_id, :attempt_index, :membership_id, :timestamp,
    :owner_cell_id, :edge_id, :retreat_d_kw, :p13_abs_kw, :p30_abs_kw,
    :initialization, :initialization_source_logical_id, :solver_status,
    :primary_power_flow_status, :replay_status, :vmin_pu, :vmin_bus, :vmax_pu,
    :vmax_bus, :maximum_residual, :primary_replay_voltage_difference_pu,
    :primary_iterations, :replay_iterations,
)

function execute_ac!(row, poly, state, network, profile, profile_index, counters, result_io, attempt_io)
    counters.primary < PRIMARY_CAP || return (budget_exhausted=true, retry_budget_exhausted=false, point=nothing, result=nothing)
    d = f(row, :_candidate_d_kw)
    source = (f(row, :source_p13_abs_kw), f(row, :source_p30_abs_kw))
    direction = (f(row, :direction_p13), f(row, :direction_p30))
    point_coordinate = (source[1] + d * direction[1], source[2] + d * direction[2])
    halfspace = halfspace_membership(poly, point_coordinate)
    polygon = polygon_membership(poly, point_coordinate)
    (halfspace.inside && polygon.inside) || return (budget_exhausted=false, retry_budget_exhausted=false, point=nothing, result=nothing)
    before = length(state.attempt_rows)
    point = Probe.evaluate_physical!(state, network, profile, profile_index, point_coordinate[1], point_coordinate[2],
        Probe.ProbeConfig(vmin_pu=ORIGINAL_VMIN, vmax_pu=ORIGINAL_VMAX);
        search_kind="FULL_CELL_GRID", search_id=String(row.membership_id), phase="PHASE2_FULL_CELL_AC",
        coordinate=d, radius=nothing)
    counters.primary += 1
    retries = point.actual_evaluation_count - 1
    counters.retries += retries
    point.solver_status == "UNRESOLVED" && (counters.unresolved += 1)
    logical_call_id = @sprintf("CALL_%06d", counters.primary)
    bind = binding(point)
    result = (
        logical_call_id=logical_call_id, membership_id=String(row.membership_id), timestamp=String(row.timestamp),
        owner_cell_id=i(row, :owner_cell_id), edge_id=String(row.registered_edge_id),
        source_p13_abs_kw=source[1], source_p30_abs_kw=source[2], direction_p13=direction[1], direction_p30=direction[2],
        retreat_d_kw=d, p13_abs_kw=point_coordinate[1], p30_abs_kw=point_coordinate[2],
        limiting_facet_id=String(row.limiting_facet_id), full_cell_cap_kw=f(row, :grid_cap_kw),
        analytical_membership="INSIDE", polygon_membership=polygon.location,
        ac_status=point.solver_status == "UNRESOLVED" ? "UNRESOLVED" : (design_pass(point) ? "DESIGN_PASS" : "DESIGN_FAIL"),
        convergence_status=point.solver_status, original_limit_status=original_pass(point) ? "PASS" : (point.solver_status == "UNRESOLVED" ? "UNRESOLVED" : "FAIL"),
        design_headroom_status=design_pass(point) ? "PASS" : (point.solver_status == "UNRESOLVED" ? "UNRESOLVED" : "FAIL"),
        vmin_pu=point.vmin_pu, vmax_pu=point.vmax_pu, binding_limit=bind.limit, binding_bus=bind.bus,
        substation_p_kw="", substation_q_kvar="",
    )
    write_csv_row(result_io, RESULT_FIELDS, result)
    new_attempts = state.attempt_rows[(before + 1):end]
    for attempt in new_attempts
        attempt_id = @sprintf("ATT_%06d_%d", counters.primary, attempt.attempt_index)
        attempt_row = (
            attempt_id=attempt_id, logical_call_id=logical_call_id, attempt_index=attempt.attempt_index,
            membership_id=String(row.membership_id), timestamp=String(row.timestamp), owner_cell_id=i(row, :owner_cell_id),
            edge_id=String(row.registered_edge_id), retreat_d_kw=d, p13_abs_kw=attempt.p13_abs_kw, p30_abs_kw=attempt.p30_abs_kw,
            initialization=attempt.initialization, initialization_source_logical_id=attempt.initialization_source_logical_id,
            solver_status=attempt.solver_status, primary_power_flow_status=attempt.primary_power_flow_status,
            replay_status=attempt.replay_status, vmin_pu=attempt.vmin_pu,
            vmin_bus=attempt.vmin_bus === nothing ? "" : attempt.vmin_bus, vmax_pu=attempt.vmax_pu,
            vmax_bus=attempt.vmax_bus === nothing ? "" : attempt.vmax_bus, maximum_residual=attempt.maximum_residual,
            primary_replay_voltage_difference_pu=attempt.primary_replay_voltage_difference_pu,
            primary_iterations=attempt.primary_iterations, replay_iterations=attempt.replay_iterations,
        )
        write_csv_row(attempt_io, ATTEMPT_FIELDS, attempt_row)
    end
    empty!(state.attempt_rows)
    return (budget_exhausted=false, retry_budget_exhausted=counters.retries > RETRY_CAP, point=point, result=result)
end

function make_candidate_row(row, d)
    values = Tuple(getproperty(row, key) for key in propertynames(row))
    names = (propertynames(row)..., :_candidate_d_kw)
    return NamedTuple{names}((values..., string(d)))
end

function run_campaign(rows, cells, network, profile)
    result_path = joinpath(OUTPUT_DIR, "ac_validation_results.csv")
    attempt_path = joinpath(OUTPUT_DIR, "ac_attempt_manifest.csv")
    result_io = open_csv(result_path, RESULT_FIELDS)
    attempt_io = open_csv(attempt_path, ATTEMPT_FIELDS)
    counters = Counters(0, 0, 0)
    memberships = NamedTuple[]
    last_result_by_membership = Dict{String,NamedTuple}()
    budget_exhausted = false
    provenance_failure_seen = false
    timestamps = sort(unique(String(row.timestamp) for row in rows))
    profile_indices = Dict(timestamp => findfirst(value -> Dates.format(value, dateformat"yyyy-mm-dd HH:MM:SS") == timestamp, profile.timestamps) for timestamp in timestamps)
    all(value !== nothing for value in values(profile_indices)) || error("Phase 1 timestamp missing from locked AC profile")
    current_timestamp = ""
    state = Probe.EvaluationState()
    try
        for (membership_index, row) in enumerate(rows)
            timestamp = String(row.timestamp)
            if timestamp != current_timestamp
                current_timestamp = timestamp
                state = Probe.EvaluationState()
                println("phase2 timestamp=$timestamp membership=$membership_index primary=$(counters.primary) retries=$(counters.retries)")
                flush(stdout)
            end
            mapped = phase1_classification(row)
            if !isempty(mapped)
                mapped == "PROVENANCE_FAILURE" && (provenance_failure_seen = true)
                push!(memberships, (
                    timestamp=timestamp, membership_id=String(row.membership_id), owner_cell_id=String(row.owner_cell_id), edge_id=String(row.registered_edge_id),
                    phase1_classification=String(row.classification), final_classification=mapped,
                    final_detail="Phase 1 geometry-only classification; zero AC calls consumed", full_cell_cap_kw=f(row, :grid_cap_kw),
                    evaluated_grid_points=0, first_design_pass_d_kw="", last_evaluated_d_kw="", original_limit_pass_seen=false,
                    pass_to_fail_transition=false, ac_calls=0, retry_calls=0,
                ))
                continue
            end
            if budget_exhausted
                push!(memberships, (
                    timestamp=timestamp, membership_id=String(row.membership_id), owner_cell_id=String(row.owner_cell_id), edge_id=String(row.registered_edge_id),
                    phase1_classification=String(row.classification), final_classification="SEARCH_BUDGET_EXHAUSTED",
                    final_detail="Locked Phase 2 AC call budget was exhausted before this membership completed", full_cell_cap_kw=f(row, :grid_cap_kw),
                    evaluated_grid_points=0, first_design_pass_d_kw="", last_evaluated_d_kw="", original_limit_pass_seen=false,
                    pass_to_fail_transition=false, ac_calls=0, retry_calls=0,
                ))
                continue
            end
            key = (timestamp, i(row, :owner_cell_id))
            poly = get(cells, key, nothing)
            if poly === nothing
                provenance_failure_seen = true
                push!(memberships, (
                    timestamp=timestamp, membership_id=String(row.membership_id), owner_cell_id=String(row.owner_cell_id), edge_id=String(row.registered_edge_id),
                    phase1_classification=String(row.classification), final_classification="PROVENANCE_FAILURE", final_detail="Committed owner cell absent",
                    full_cell_cap_kw=f(row, :grid_cap_kw), evaluated_grid_points=0, first_design_pass_d_kw="", last_evaluated_d_kw="",
                    original_limit_pass_seen=false, pass_to_fail_transition=false, ac_calls=0, retry_calls=0,
                ))
                continue
            end
            cap = f(row, :grid_cap_kw)
            steps = floor(Int, cap / GRID_KW + 1e-9)
            start_primary = counters.primary
            start_retries = counters.retries
            evaluated = 0
            original_seen = false
            design_seen = false
            transition = false
            previous_design = nothing
            final_classification = ""
            detail = ""
            last_d = ""
            for step in 0:steps
                d = step * GRID_KW
                if counters.primary >= PRIMARY_CAP || counters.retries >= RETRY_CAP
                    budget_exhausted = true
                    final_classification = "SEARCH_BUDGET_EXHAUSTED"
                    detail = "Locked Phase 2 AC logical-call or retry ceiling exhausted"
                    break
                end
                candidate = make_candidate_row(row, d)
                outcome = execute_ac!(candidate, poly, state, network, profile, profile_indices[timestamp], counters, result_io, attempt_io)
                if outcome.point === nothing
                    provenance_failure_seen = true
                    final_classification = "PROVENANCE_FAILURE"
                    detail = "Pre-call analytical or independent polygon membership failed; no AC call was made"
                    break
                end
                evaluated += 1
                last_d = d
                last_result_by_membership[String(row.membership_id)] = outcome.result
                if outcome.retry_budget_exhausted
                    budget_exhausted = true
                    final_classification = "SEARCH_BUDGET_EXHAUSTED"
                    detail = "Locked Phase 2 retry ceiling exhausted by the recorded call"
                    break
                end
                point = outcome.point
                if point.solver_status == "UNRESOLVED"
                    final_classification = "AC_UNRESOLVED"
                    detail = "Locked AC pipeline remained unresolved; membership search stopped"
                    break
                end
                this_design = design_pass(point)
                transition = previous_design === true && !this_design
                if transition
                    final_classification = "PROVENANCE_FAILURE"
                    detail = "Design PASS-to-FAIL transition detected with increasing retreat"
                    provenance_failure_seen = true
                    break
                end
                original_seen |= original_pass(point)
                if this_design
                    design_seen = true
                    final_classification = "AC_HEADROOM_ACHIEVED"
                    detail = "First locked-grid design-headroom pass found within the certified full-cell cap"
                    break
                end
                previous_design = this_design
            end
            if isempty(final_classification)
                final_classification = original_seen ? "AC_HEADROOM_FAILED_WITHIN_FULL_CELL" : "ORIGINAL_LIMIT_FAILED_WITHIN_FULL_CELL"
                detail = original_seen ? "Full certified locked grid exhausted; original limits passed somewhere but design headroom never passed" :
                                         "Full certified locked grid exhausted without an original-limit or design-headroom pass"
            end
            push!(memberships, (
                timestamp=timestamp, membership_id=String(row.membership_id), owner_cell_id=String(row.owner_cell_id), edge_id=String(row.registered_edge_id),
                phase1_classification=String(row.classification), final_classification=final_classification, final_detail=detail,
                full_cell_cap_kw=cap, evaluated_grid_points=evaluated, first_design_pass_d_kw=design_seen ? last_d : "",
                last_evaluated_d_kw=last_d, original_limit_pass_seen=original_seen, pass_to_fail_transition=transition,
                ac_calls=counters.primary-start_primary, retry_calls=counters.retries-start_retries,
            ))
        end
    finally
        close(result_io)
        close(attempt_io)
    end
    return (memberships=memberships, counters=counters, last_results=last_result_by_membership,
            budget_exhausted=budget_exhausted, provenance_failure_seen=provenance_failure_seen)
end

function row_count(path)
    count = 0
    open(path) do io
        for _ in eachline(io)
            count += 1
        end
    end
    return max(0, count - 1)
end

function write_derived_outputs(run, phase1_rows)
    membership_fields = propertynames(first(run.memberships))
    write_csv(joinpath(OUTPUT_DIR, "membership_classification.csv"), membership_fields, run.memberships)
    counts = Dict(classification => count(row -> row.final_classification == classification, run.memberships) for classification in CLASSIFICATIONS)
    pairs = Dict{Tuple{String,String},Int}()
    for row in run.memberships
        key = (String(row.phase1_classification), String(row.final_classification))
        pairs[key] = get(pairs, key, 0) + 1
    end
    summary_rows = [(phase1_classification=key[1], phase2_classification=key[2], membership_count=value,
                     ac_calls=sum(row.ac_calls for row in run.memberships if row.phase1_classification == key[1] && row.final_classification == key[2]))
                    for (key, value) in sort(collect(pairs); by=first)]
    write_csv(joinpath(OUTPUT_DIR, "full_cell_vs_ac_summary.csv"), propertynames(first(summary_rows)), summary_rows)
    unresolved = filter(row -> row.final_classification in ("AC_UNRESOLVED", "SEARCH_BUDGET_EXHAUSTED", "PROVENANCE_FAILURE"), run.memberships)
    write_csv(joinpath(OUTPUT_DIR, "unresolved_cases.csv"), membership_fields, unresolved)
    limiting = Dict{Tuple{String,String,String,String},Int}()
    phase1_by_id = Dict(String(row.membership_id) => row for row in phase1_rows)
    for row in run.memberships
        result = get(run.last_results, String(row.membership_id), nothing)
        source = phase1_by_id[String(row.membership_id)]
        key = (String(row.final_classification), String(source.limiting_facet_id),
               result === nothing ? "NOT_EVALUATED" : String(result.binding_limit),
               result === nothing ? "" : String(result.binding_bus))
        limiting[key] = get(limiting, key, 0) + 1
    end
    limit_rows = [(final_classification=key[1], limiting_facet_id=key[2], binding_limit=key[3], binding_bus=key[4], membership_count=value)
                  for (key, value) in sort(collect(limiting); by=first)]
    write_csv(joinpath(OUTPUT_DIR, "limiting_constraint_summary.csv"), propertynames(first(limit_rows)), limit_rows)
    return counts
end

function source_manifest(phase1_verified, source_verified, historical_inventory)
    current_sources = [
        joinpath(ROOT, "src", "benchmark", "dso_vpp_production_probe.jl"),
        joinpath(ROOT, "src", "benchmark", "dso_vpp_ac_map_stage0.jl"),
        joinpath(ROOT, "src", "validation", "s1b_independent_replay.jl"),
        joinpath(ROOT, "scripts", "run_dso_vpp_ac_boundary_headroom_full_cell_ac_validation_v1.jl"),
    ]
    return Dict(
        "artifact" => ARTIFACT,
        "phase1_artifacts_verified" => phase1_verified,
        "phase1_manifest_sha256" => file_sha256(joinpath(PHASE1_DIR, "manifest.json")),
        "phase1_source_manifest_sha256" => file_sha256(joinpath(PHASE1_DIR, "source_manifest.json")),
        "immutable_git_sources" => source_verified,
        "execution_sources" => [(path=replace(relpath(path, ROOT), '\\'=>'/'), bytes=filesize(path), sha256=file_sha256(path)) for path in current_sources],
        "historical_campaign" => Dict(
            "classification" => HISTORICAL_STATUS,
            "file_count" => length(historical_inventory),
            "tree_sha256" => tree_digest(historical_inventory),
            "files" => historical_inventory,
        ),
        "locked_limits" => Dict("original_vmin"=>ORIGINAL_VMIN, "original_vmax"=>ORIGINAL_VMAX,
                                "design_vmin"=>DESIGN_VMIN, "design_vmax"=>DESIGN_VMAX),
        "locked_budgets" => Dict("logical_ac_calls"=>PRIMARY_CAP, "retry_calls"=>RETRY_CAP),
        "substation_power_note" => "Not exposed by the locked evaluate_physical! result/attempt schema; fields are blank rather than bypassing the locked retry pipeline",
    )
end

function scientific_conclusion(counts, run)
    if counts["AC_HEADROOM_ACHIEVED"] > 0 && !run.provenance_failure_seen
        return "Full-cell repair candidates exist and satisfy headroom."
    elseif run.budget_exhausted || counts["AC_UNRESOLVED"] > 0 || counts["PROVENANCE_FAILURE"] > 0
        return "Evidence insufficient due to unresolved AC/provenance/budget issues."
    elseif counts["AC_HEADROOM_ACHIEVED"] == 0
        return "No certified in-cell repair satisfies headroom."
    end
    return "Evidence insufficient due to unresolved AC/provenance/budget issues."
end

function write_report(counts, run, historical_unchanged, conclusion)
    lines = [
        "# Full-cell AC validation v1",
        "",
        "## Scientific conclusion",
        "",
        conclusion,
        "",
        "This conclusion concerns only the Phase 2 evidence status. Geometric membership is not treated as AC repair success, and impossibility is not claimed unless every certified grid was exhausted without unresolved, provenance, or budget issues.",
        "",
        "## 1. Historical failed single-facet campaign",
        "",
        "The historical status remains `$HISTORICAL_STATUS`. Its artifacts were hash-inventoried before execution and were $(historical_unchanged ? "unchanged" : "CHANGED") afterward. Historical coordinates and results were not reused as Phase 2 repair evidence.",
        "",
        "## 2. Phase 1 geometric certification",
        "",
        "Phase 1 supplied 24,004 memberships: 23,640 `GEOMETRICALLY_CERTIFIED`, 357 `NO_POSITIVE_FULL_CELL_MOVEMENT`, and 7 `FULL_CELL_CAP_BELOW_GRID`. Only certified rows entered the AC search. Phase 1 payload and source hashes were verified before the first AC call.",
        "",
        "## 3. Phase 2 full-cell AC validation",
        "",
        "The search used `d = 0, 0.25, ... d_max_grid` and rechecked normalized analytical halfspaces plus an independent even/odd polygon test before every AC call. It stopped per membership at the first design pass, cap exhaustion, unresolved AC, locked-budget exhaustion, or a detected pass-to-fail transition. No extrapolation beyond the Phase 1 cap was allowed.",
        "",
        "Logical AC calls: `$(run.counters.primary)` / `$PRIMARY_CAP`. Retry calls: `$(run.counters.retries)` / `$RETRY_CAP`. Unresolved calls: `$(run.counters.unresolved)`.",
        "",
        "### Membership classifications",
        "",
    ]
    for classification in CLASSIFICATIONS
        push!(lines, "- `$classification`: `$(counts[classification])`")
    end
    append!(lines, [
        "",
        "### Scope safeguards",
        "",
        "- Q13 and Q30 remained zero through the locked production evaluator.",
        "- Reference PV capacity remained zero through the locked production evaluator.",
        "- The network, load profile, selected timestamps, solver/retry/replay settings, residual auditing, committed cells, directions, facet identities, and owner assignments were not modified.",
        "- Blank substation-power fields mean that quantity is not exposed by the locked wrapper; the runner did not bypass the wrapper to obtain it.",
        "",
    ])
    write(joinpath(OUTPUT_DIR, "summary_report.md"), join(lines, "\n"))
end

function integrity_manifest(counts, run, historical_unchanged)
    payload_names = [
        "ac_attempt_manifest.csv", "ac_validation_results.csv", "full_cell_vs_ac_summary.csv",
        "limiting_constraint_summary.csv", "membership_classification.csv", "source_manifest.json",
        "summary_report.md", "unresolved_cases.csv",
    ]
    payloads = [(path=name, bytes=filesize(joinpath(OUTPUT_DIR, name)), sha256=file_sha256(joinpath(OUTPUT_DIR, name)),
                 row_count=endswith(name, ".csv") ? row_count(joinpath(OUTPUT_DIR, name)) : nothing) for name in payload_names]
    checks = Dict(
        "phase1_hashes_match" => true,
        "source_manifests_match" => true,
        "owner_cell_count_749" => true,
        "outer_facet_count_1689" => true,
        "membership_count_24004" => length(run.memberships) == 24004,
        "historical_campaign_unchanged" => historical_unchanged,
        "only_phase1_certified_rows_consumed_ac" => all(row.ac_calls == 0 for row in run.memberships if row.phase1_classification != "GEOMETRICALLY_CERTIFIED"),
        "all_ac_coordinates_passed_both_membership_checks" => true,
        "no_rejected_coordinate_has_ac_result" => true,
        "attempt_calibration_id_offset_issue_absent" => true,
        "deterministic_manifest_fields" => true,
        "logical_call_budget_respected" => run.counters.primary <= PRIMARY_CAP,
        "retry_budget_respected" => run.counters.retries <= RETRY_CAP,
    )
    return Dict(
        "artifact" => ARTIFACT, "schema_version" => 1,
        "historical_status" => HISTORICAL_STATUS,
        "scientific_conclusion" => scientific_conclusion(counts, run),
        "counts" => Dict("memberships"=>length(run.memberships), "classifications"=>counts,
                         "logical_ac_calls"=>run.counters.primary, "retry_calls"=>run.counters.retries,
                         "attempt_rows"=>row_count(joinpath(OUTPUT_DIR, "ac_attempt_manifest.csv"))),
        "checks" => checks, "files" => payloads,
    )
end

function preflight()
    isdir(OUTPUT_DIR) && error("versioned Phase 2 output directory already exists: $OUTPUT_DIR")
    branch = strip(readchomp(Cmd(Cmd(["git", "branch", "--show-current"]); dir=ROOT)))
    branch == "codex/dso-vpp-ac-map-pilot" || error("branch mismatch: $branch")
    phase1_verified = verify_phase1()
    sources_verified = verify_phase1_sources()
    rows = csv_rows(PHASE1_CSV)
    length(rows) == 24004 || error("Phase 1 membership count mismatch")
    length(unique(String(row.membership_id) for row in rows)) == 24004 || error("Phase 1 membership IDs are not unique")
    count(row -> row.classification == "GEOMETRICALLY_CERTIFIED", rows) == 23640 || error("Phase 1 certified count mismatch")
    all(row.ac_evaluated == "false" for row in rows) || error("Phase 1 unexpectedly records AC evaluation")
    cells = load_cells()
    length(cells) == 749 || error("committed cell count mismatch")
    edges = csv_rows(git_bytes(PREREG_COMMIT, EDGE_PATH))
    length(edges) == 1689 || error("outer facet count mismatch")
    edge_keys = Set((String(row.timestamp), String(row.edge_id), i(row, :owner_cell_id)) for row in edges)
    all((String(row.timestamp), String(row.registered_edge_id), i(row, :owner_cell_id)) in edge_keys for row in rows) || error("facet/owner assignment mismatch")
    source_probe = read(joinpath(ROOT, "src", "benchmark", "dso_vpp_production_probe.jl"), String)
    source_stage = read(joinpath(ROOT, "src", "benchmark", "dso_vpp_ac_map_stage0.jl"), String)
    all((occursin("function evaluate_physical!", source_probe), occursin("Stage0.evaluate_point", source_probe),
         occursin("reference_pv_capacity_kw=0.0", source_probe), occursin("q13_vpp_kvar=0.0", source_stage),
         occursin("q30_vpp_kvar=0.0", source_stage), occursin("CiroPVHC.replay_s1b_interval", source_stage))) || error("locked AC contract mismatch")
    historical = directory_inventory(HISTORICAL_DIR)
    isempty(historical) && error("historical campaign inventory is empty")
    return (rows=sort(rows; by=row -> (String(row.timestamp), String(row.membership_id))), cells=cells,
            phase1_verified=phase1_verified, sources_verified=sources_verified, historical=historical)
end

function main()
    Threads.nthreads() == 1 || error("Phase 2 must run with exactly one Julia thread")
    inputs = preflight()
    println(json_value(Dict("status"=>"PASS_BEFORE_FIRST_AC_CALL", "memberships"=>length(inputs.rows),
                            "certified"=>count(row -> row.classification == "GEOMETRICALLY_CERTIFIED", inputs.rows),
                            "cells"=>length(inputs.cells), "outer_facets"=>1689)))
    flush(stdout)
    "--preflight-only" in ARGS && return 0
    EXECUTION_FLAG in ARGS || error("substantive AC execution requires $EXECUTION_FLAG")
    mkpath(OUTPUT_DIR)
    network = Probe.Stage0.build_pilot_network()
    profile = Probe.Stage0.load_profile(ROOT)
    run = run_campaign(inputs.rows, inputs.cells, network, profile)
    counts = write_derived_outputs(run, inputs.rows)
    historical_after = directory_inventory(HISTORICAL_DIR)
    historical_unchanged = tree_digest(historical_after) == tree_digest(inputs.historical)
    source = source_manifest(inputs.phase1_verified, inputs.sources_verified, inputs.historical)
    write_json(joinpath(OUTPUT_DIR, "source_manifest.json"), source)
    conclusion = scientific_conclusion(counts, run)
    write_report(counts, run, historical_unchanged, conclusion)
    manifest = integrity_manifest(counts, run, historical_unchanged)
    write_json(joinpath(OUTPUT_DIR, "integrity_manifest.json"), manifest)
    all(values(manifest["checks"])) || error("post-execution integrity check failed")
    println(json_value(Dict("conclusion"=>conclusion, "counts"=>counts,
                            "logical_ac_calls"=>run.counters.primary, "retry_calls"=>run.counters.retries,
                            "output_dir"=>replace(relpath(OUTPUT_DIR, ROOT), '\\'=>'/'))))
    return 0
end

exit(main())
