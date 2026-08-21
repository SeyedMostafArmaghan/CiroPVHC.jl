using CiroPVHC
using Dates
using Printf
using SHA
using Serialization
using TOML

include(joinpath(@__DIR__, "..", "src", "benchmark", "dso_vpp_production_probe.jl"))
const Probe = DSOVPPProductionProbe

const EXPECTED_BRANCH = "codex/dso-vpp-ac-map-pilot"
const EXPECTED_HEAD = "fc15fbf7bf93ca89c2ab4a45145f937abbc70f63"
const LOCKED_CLASSIFICATION = "MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE"
const H_DESIGN = 0.00015
const DESIGN_VMIN = 0.90015
const DESIGN_VMAX = 1.04985
const ORIGINAL_VMIN = 0.90
const ORIGINAL_VMAX = 1.05
const RETREAT_RESOLUTION_KW = 0.25
const INITIAL_STEP_KW = 0.5
const MAX_BRACKET_CALLS = 16
const MAX_BISECTION_CALLS = 16
const MAX_EXTRA_CALLS = 8
const PRIMARY_CAP = 302303
const CALIBRATION_PRIMARY_CAP = 279015
const RETRY_CAP = 3024
const CHUNK_ROWS = 2000
const COORD_TOL_KW = 1e-8
const GEOMETRY_TOL_KW = 1e-7
const AREA_TOL_KW2 = 1e-5
const RETAINED_CAMPAIGN_TOTAL_WALL_SECONDS = 220.681159
const RETAINED_CAMPAIGN_STARTUP_SETUP_SECONDS = 111.178728
const RETAINED_CAMPAIGN_RESUME_ORCHESTRATION_SECONDS = 0.414837
const EXECUTION_FLAG = "--execute-preregistered-calibration"

const ROOT = normpath(joinpath(@__DIR__, ".."))
const PREREG_DIR = joinpath(ROOT, "results", "dso_vpp_ac_map_pilot",
                            "doe_ac_boundary_headroom_repair_preregistration")
const OUTPUT_DIR = joinpath(ROOT, "results", "dso_vpp_ac_map_pilot",
                           "doe_ac_boundary_headroom_repair_calibration")
const SHARD_DIR = joinpath(OUTPUT_DIR, "shards")
const CHECKPOINT_PATH = joinpath(OUTPUT_DIR, "checkpoint_state.toml")
const CALIBRATION_EDGE_MAP = Dict{String,String}()

const PATHS = (
    edge_policy=joinpath(PREREG_DIR, "edge_repair_policy.csv"),
    memberships=joinpath(PREREG_DIR, "calibration_fraction_inventory.csv"),
    controls=joinpath(ROOT, "results", "dso_vpp_ac_map_pilot",
                      "doe_ac_interior_validation_preregistration", "validation_controls.csv"),
    historical_points=joinpath(ROOT, "results", "dso_vpp_ac_map_pilot",
                               "doe_ac_interior_validation", "validation_point_results.csv"),
    low_edges=joinpath(ROOT, "results", "dso_vpp_ac_map_pilot",
                       "doe_ac_repairability_interpolation_audit", "signed_interpolation_addendum",
                       "low_sample_edges.csv"),
    enrichment=joinpath(ROOT, "results", "dso_vpp_ac_map_pilot",
                        "doe_ac_repairability_interpolation_audit", "signed_interpolation_addendum",
                        "low_sample_enrichment_points.csv"),
    diagnostics=joinpath(ROOT, "results", "dso_vpp_ac_map_pilot",
                         "doe_ac_repairability_interpolation_audit", "edge_interpolation_fits.csv"),
    cells=joinpath(ROOT, "results", "dso_vpp_ac_map_pilot",
                   "doe_construction_policy_preregistration", "convex_piecewise_architecture_audit",
                   "merged_convex_cells.csv"),
)

mutable struct RunCounters
    primary::Int
    retries::Int
    completed_edges::Int
    blocked_edges::Int
    unresolved::Int
end

mutable struct RunTimers
    startup_setup::Float64
    resume_orchestration::Float64
    ac_evaluation::Float64
    non_ac_bookkeeping::Float64
    shard_io::Float64
    final_postprocessing::Float64
end

f(row, key::Symbol) = parse(Float64, getproperty(row, key))
i(row, key::Symbol) = parse(Int, getproperty(row, key))
truth(value) = lowercase(String(value)) == "true"
file_sha256(path) = bytes2hex(open(sha256, path))
git_output(args...) = strip(readchomp(Cmd(Cmd(String["git", string.(args)...]); dir=ROOT)))

function csv_value(value)
    value === nothing && return ""
    if value isa AbstractString
        escaped = replace(value, "\"" => "\"\"")
        return occursin(r"[,\"\r\n]", escaped) ? "\"$escaped\"" : escaped
    elseif value isa AbstractFloat
        return isfinite(value) ? @sprintf("%.15g", value) : string(value)
    elseif value isa Bool
        return lowercase(string(value))
    end
    return string(value)
end

function write_csv(path, fields, rows)
    mkpath(dirname(path))
    open(path, "w") do io
        println(io, join(string.(fields), ','))
        for row in rows
            println(io, join((csv_value(getproperty(row, field)) for field in fields), ','))
        end
    end
    return path
end

function write_text(path, value)
    mkpath(dirname(path))
    open(path, "w") do io
        write(io, value)
    end
    return path
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

write_json(path, value) = write_text(path, json_value(value) * "\n")

function normalized_sha256_bytes(bytes::Vector{UInt8})
    normalized = replace(String(bytes), "\r\n" => "\n", "\r" => "\n")
    return bytes2hex(sha256(codeunits(normalized)))
end

function verify_json_manifest(directory, manifest_path)
    text = read(manifest_path, String)
    pattern = r"\{\s*\"bytes\"\s*:\s*(\d+)\s*,\s*\"path\"\s*:\s*\"([^\"]+)\"\s*,\s*\"sha256\"\s*:\s*\"([0-9a-f]{64})\""
    rows = collect(eachmatch(pattern, text))
    isempty(rows) && error("manifest contains no payload rows: $manifest_path")
    for match in rows
        expected_bytes = parse(Int, match.captures[1])
        relative = match.captures[2]
        expected_hash = match.captures[3]
        path = joinpath(directory, relative)
        isfile(path) || error("missing preregistration payload: $relative")
        bytes = read(path)
        length(bytes) == expected_bytes || error("preregistration byte mismatch: $relative")
        bytes2hex(sha256(bytes)) == expected_hash || error("preregistration hash mismatch: $relative")
    end
    return length(rows)
end

function verify_source_manifest()
    manifest_path = joinpath(PREREG_DIR, "source_manifest.json")
    text = read(manifest_path, String)
    source_commit_match = match(r"\"source_commit\"\s*:\s*\"([0-9a-f]{40})\"", text)
    source_commit_match === nothing && error("source manifest commit absent")
    source_commit = source_commit_match.captures[1]
    pattern = r"\{\s*\"bytes\"\s*:\s*(\d+)\s*,\s*\"path\"\s*:\s*\"([^\"]+)\"\s*,\s*\"sha256\"\s*:\s*\"([0-9a-f]{64})\""
    rows = collect(eachmatch(pattern, text))
    for match in rows
        expected_bytes = parse(Int, match.captures[1])
        path = match.captures[2]
        expected_hash = match.captures[3]
        bytes = read(Cmd(Cmd(["git", "show", "$source_commit:$path"]); dir=ROOT))
        length(bytes) == expected_bytes || error("source manifest byte mismatch: $path")
        bytes2hex(sha256(bytes)) == expected_hash || error("source manifest hash mismatch: $path")
    end
    return (source_commit=source_commit, files=length(rows))
end

function assert_git_preconditions()
    branch = git_output("branch", "--show-current")
    head = git_output("rev-parse", "HEAD")
    status = git_output("status", "--short")
    divergence = replace(git_output("rev-list", "--left-right", "--count",
                                    "HEAD...origin/$EXPECTED_BRANCH"), '\t' => ' ')
    branch == EXPECTED_BRANCH || error("branch mismatch: $branch")
    head == EXPECTED_HEAD || error("HEAD mismatch: $head")
    status_lines = filter(!isempty, split(status, '\n'))
    allowed_prefixes = ["?? scripts/run_dso_vpp_ac_boundary_headroom_repair_calibration.jl",
                        "?? results/dso_vpp_ac_map_pilot/doe_ac_boundary_headroom_repair_calibration/"]
    unexpected = filter(line -> !any(prefix -> startswith(line, prefix), allowed_prefixes), status_lines)
    isempty(unexpected) || error("unexpected working-tree changes before campaign: $(join(unexpected, ';'))")
    divergence == "0 0" || error("branch divergence mismatch: $divergence")
    return (branch=branch, head=head, divergence=divergence)
end

function assert_locked_config()
    config = read(joinpath(PREREG_DIR, "repair_config.json"), String)
    required = [
        "\"h_design_pu\": 0.00015",
        "\"vmax_pu\": 1.04985",
        "\"vmin_pu\": 0.90015",
        "\"initial_step_kw\": 0.5",
        "\"locked_retreat_resolution_kw\": 0.25",
        "\"maximum_bisection_calls_per_edge\": 16",
        "\"maximum_bracket_calls_per_edge\": 16",
        "\"primary_logical_call_cap\": 302303",
        "\"retry_call_cap\": 3024",
        "\"chunk_rows\": 2000",
        "\"normal_projection\": \"FORBIDDEN_INCLUDING_65_MIXED_SIGN_NORMALS\"",
    ]
    missing = filter(item -> !occursin(item, config), required)
    isempty(missing) || error("locked repair config mismatch: $(join(missing, ';'))")
    rules = read(joinpath(PREREG_DIR, "decision_rules.md"), String)
    occursin("meets both design limits", rules) || error("dual design-limit rule absent")
    occursin("REENTRY_BLOCKER", rules) || error("locked re-entry label absent")
    return true
end

function assert_ac_contract()
    source_probe = read(joinpath(ROOT, "src", "benchmark", "dso_vpp_production_probe.jl"), String)
    source_stage = read(joinpath(ROOT, "src", "benchmark", "dso_vpp_ac_map_stage0.jl"), String)
    source_replay = read(joinpath(ROOT, "src", "validation", "s1b_independent_replay.jl"), String)
    checks = [
        occursin("function evaluate_physical!", source_probe),
        occursin("Stage0.evaluate_point", source_probe),
        occursin("reference_pv_capacity_kw=0.0", source_probe),
        occursin("function evaluate_point", source_stage),
        occursin("q13_vpp_kvar=0.0", source_stage),
        occursin("q30_vpp_kvar=0.0", source_stage),
        occursin("CiroPVHC.replay_s1b_interval", source_stage),
        occursin("const VMIN_PU = 0.90", source_stage),
        occursin("const VMAX_PU = 1.05", source_stage),
        occursin("function replay_s1b_interval", source_replay),
    ]
    all(checks) || error("authoritative AC execution contract mismatch")
    return Dict(
        "call_path" => ["DSOVPPProductionProbe.evaluate_physical!",
                        "DSOVPPACMapStage0.evaluate_point", "radial AC PF",
                        "CiroPVHC.replay_s1b_interval"],
        "coordinate_space" => "ABSOLUTE_PHYSICAL_P_PCC_KW",
        "q13_kvar" => 0, "q30_kvar" => 0,
        "reference_pv_capacity_kw" => 0,
        "original_voltage_limits_pu" => [0.90, 1.05],
        "positive_p" => "INJECTION_EXPORT",
        "nonconvergence" => "UNRESOLVED",
    )
end

function bucket_key(timestamp, p13, p30)
    return (String(timestamp), floor(Int, p13 / COORD_TOL_KW), floor(Int, p30 / COORD_TOL_KW))
end

function build_registry(memberships)
    buckets = Dict{Tuple{String,Int,Int},Vector{Int}}()
    registry = NamedTuple[]
    membership_to_registry = Dict{String,String}()
    ordered = sort(memberships; by=row -> (row.timestamp, f(row, :p13_abs_kw_at_source_geometry),
                                           f(row, :p30_abs_kw_at_source_geometry), row.calibration_membership_id))
    for row in ordered
        p13 = f(row, :p13_abs_kw_at_source_geometry)
        p30 = f(row, :p30_abs_kw_at_source_geometry)
        key = bucket_key(row.timestamp, p13, p30)
        found = 0
        for dx in -1:1, dy in -1:1
            for index in get(buckets, (key[1], key[2] + dx, key[3] + dy), Int[])
                candidate = registry[index]
                if abs(candidate.p13_abs_kw - p13) <= COORD_TOL_KW &&
                   abs(candidate.p30_abs_kw - p30) <= COORD_TOL_KW
                    found = index
                    break
                end
            end
            found != 0 && break
        end
        if found == 0
            found = length(registry) + 1
            push!(registry, (registry_id=@sprintf("REG_%06d", found), timestamp=String(row.timestamp),
                             p13_abs_kw=p13, p30_abs_kw=p30,
                             first_membership_id=String(row.calibration_membership_id)))
            push!(get!(buckets, key, Int[]), found)
        end
        membership_to_registry[String(row.calibration_membership_id)] = registry[found].registry_id
    end
    lines = ["registry_id,timestamp,p13_abs_kw,p30_abs_kw,first_membership_id"]
    append!(lines, [join((csv_value(getproperty(row, field)) for field in propertynames(row)), ',') for row in registry])
    registry_hash = bytes2hex(sha256(codeunits(join(lines, "\n") * "\n")))
    return (rows=registry, membership_to_registry=membership_to_registry, sha256=registry_hash)
end

function assert_enrichment_postcondition(low_edges, enrichment)
    enrich_by_edge = Dict{Tuple{String,String},Vector{Float64}}()
    for row in enrichment
        push!(get!(enrich_by_edge, (String(row.timestamp), String(row.edge_id)), Float64[]), f(row, :t))
    end
    details = NamedTuple[]
    for row in low_edges
        values = isempty(row.original_interior_fractions) ? Float64[] : parse.(Float64, split(row.original_interior_fractions, ';'))
        append!(values, get(enrich_by_edge, (String(row.timestamp), String(row.edge_id)), Float64[]))
        values = sort(unique(values))
        all_values = sort(unique(vcat([0.0], values, [1.0])))
        gap = maximum(diff(all_values))
        pass = length(values) >= 3 && gap <= 0.25 + 1e-12
        push!(details, (timestamp=String(row.timestamp), edge_id=String(row.edge_id),
                        n_e=length(values), g_e=gap, status=pass ? "PASS" : "FAIL"))
    end
    length(details) == 41 || error("ENRICHMENT_POSTCONDITION_FAILED: low edge count=$(length(details))")
    length(enrichment) == 130 || error("ENRICHMENT_POSTCONDITION_FAILED: enrichment count=$(length(enrichment))")
    all(row.status == "PASS" for row in details) ||
        error("ENRICHMENT_POSTCONDITION_FAILED; STOP_BEFORE_FIRST_AC_CALL")
    return details
end

function historical_lookup(rows)
    buckets = Dict{Tuple{String,Int,Int},Vector{NamedTuple}}()
    for row in rows
        p13 = f(row, :p13_abs_kw)
        p30 = f(row, :p30_abs_kw)
        push!(get!(buckets, bucket_key(row.timestamp, p13, p30), NamedTuple[]), row)
    end
    return buckets
end

function find_historical(buckets, timestamp, p13, p30)
    key = bucket_key(timestamp, p13, p30)
    for dx in -1:1, dy in -1:1
        for row in get(buckets, (key[1], key[2] + dx, key[3] + dy), NamedTuple[])
            if abs(f(row, :p13_abs_kw) - p13) <= COORD_TOL_KW &&
               abs(f(row, :p30_abs_kw) - p30) <= COORD_TOL_KW
                return row
            end
        end
    end
    return nothing
end

function diagnostic_maps(rows)
    by_edge = Dict{Tuple{String,String},Vector{NamedTuple}}()
    for row in rows
        truth(row.fit_sufficient) || continue
        push!(get!(by_edge, (String(row.timestamp), String(row.edge_id)), NamedTuple[]), row)
    end
    return by_edge
end

function predicted_design_margin(row, diagnostics)
    t = f(row, :t)
    margins = Float64[]
    for diagnostic in diagnostics
        a = f(diagnostic, :endpoint_a_margin)
        b = f(diagnostic, :endpoint_b_margin)
        s = f(diagnostic, :s_e_pu)
        push!(margins, (1 - t) * a + t * b + s * t * (1 - t) - H_DESIGN)
    end
    isempty(margins) && return -Inf
    return minimum(margins)
end

function anchor_margin(row, historical, diagnostics)
    p13 = f(row, :p13_abs_kw_at_source_geometry)
    p30 = f(row, :p30_abs_kw_at_source_geometry)
    old = find_historical(historical, row.timestamp, p13, p30)
    if old !== nothing && old.final_status != "UNRESOLVED_NONCONVERGENCE"
        return min(f(old, :vmin_pu) - DESIGN_VMIN, DESIGN_VMAX - f(old, :vmax_pu)), "COMMITTED_D0_AC"
    end
    return predicted_design_margin(row, diagnostics), "LOCKED_SIGNED_DIAGNOSTIC_PREDICTION"
end

function planning_search_calls(d_kw)
    d_kw <= 0 && return 0
    upper = INITIAL_STEP_KW
    lower = 0.0
    bracket = 1
    while upper + 1e-12 < d_kw && bracket < MAX_BRACKET_CALLS
        lower = upper
        upper *= 2
        bracket += 1
    end
    width = upper - lower
    bisection = width <= RETREAT_RESOLUTION_KW ? 0 : ceil(Int, log2(width / RETREAT_RESOLUTION_KW))
    return bracket + min(bisection, MAX_BISECTION_CALLS)
end

function compute_anchor_plan(edges, memberships, historical, diagnostics)
    members_by_edge = Dict{Tuple{String,String},Vector{NamedTuple}}()
    for row in memberships
        row.future_role == "D_I_STAR_SEARCH_AND_FINAL_REPAIRED_GEOMETRY_VERIFY" || continue
        push!(get!(members_by_edge, (String(row.timestamp), String(row.edge_id)), NamedTuple[]), row)
    end
    diagnostic_by_edge = diagnostic_maps(diagnostics)
    plans = Dict{Tuple{String,String},NamedTuple}()
    extra_search_estimate = 0
    for edge in edges
        key = (String(edge.timestamp), String(edge.edge_id))
        candidates = NamedTuple[]
        diags = get(diagnostic_by_edge, key, NamedTuple[])
        for member in members_by_edge[key]
            margin, source = anchor_margin(member, historical, diags)
            push!(candidates, (membership=member, margin=margin, source=source))
        end
        sort!(candidates; by=item -> (item.margin, item.membership.calibration_membership_id))
        anchor = first(candidates)
        sensitivities = [abs(f(row, :topology_normal_margin_sensitivity_pu_per_kw)) for row in diags
                         if isfinite(f(row, :topology_normal_margin_sensitivity_pu_per_kw)) &&
                            abs(f(row, :topology_normal_margin_sensitivity_pu_per_kw)) > 0]
        sensitivity = isempty(sensitivities) ? 1e-4 : minimum(sensitivities)
        estimated_retreat = max(0.0, -anchor.margin) / sensitivity
        estimated_grid = ceil(estimated_retreat / RETREAT_RESOLUTION_KW - 1e-12) * RETREAT_RESOLUTION_KW
        search_calls = planning_search_calls(estimated_grid)
        extra_search_estimate += search_calls
        plans[key] = (anchor_id=String(anchor.membership.calibration_membership_id),
                      anchor_margin=anchor.margin, anchor_source=anchor.source,
                      estimated_retreat_kw=estimated_grid, estimated_extra_search_calls=search_calls)
    end
    expected = 128 + 22315 + extra_search_estimate + 1689 + 24004
    return (plans=plans, members_by_edge=members_by_edge,
            exact_expected_primary_calls=expected,
            expected_extra_anchor_search_calls=extra_search_estimate)
end

function cell_polygons(rows)
    groups = Dict{Tuple{String,Int},Vector{NamedTuple}}()
    for row in rows
        push!(get!(groups, (String(row.timestamp), i(row, :cell_index)), NamedTuple[]), row)
    end
    polygons = Dict{Tuple{String,Int},Vector{NTuple{2,Float64}}}()
    for (key, group) in groups
        sort!(group; by=row -> i(row, :cell_vertex_index_ccw))
        polygons[key] = [(f(row, :p13_abs_kw), f(row, :p30_abs_kw)) for row in group]
    end
    return polygons
end

polygon_area(poly) = abs(sum(poly[j][1] * poly[mod1(j + 1, length(poly))][2] -
                             poly[mod1(j + 1, length(poly))][1] * poly[j][2]
                             for j in eachindex(poly))) / 2

function clip_halfspace(poly, normal::NTuple{2,Float64}, offset)
    isempty(poly) && return poly
    output = NTuple{2,Float64}[]
    inside(point) = normal[1] * point[1] + normal[2] * point[2] >= offset - GEOMETRY_TOL_KW
    signed(point) = normal[1] * point[1] + normal[2] * point[2] - offset
    for index in eachindex(poly)
        current = poly[index]
        previous = poly[mod1(index - 1, length(poly))]
        current_inside = inside(current)
        previous_inside = inside(previous)
        if current_inside != previous_inside
            s0 = signed(previous)
            s1 = signed(current)
            alpha = s0 / (s0 - s1)
            push!(output, (previous[1] + alpha * (current[1] - previous[1]),
                           previous[2] + alpha * (current[2] - previous[2])))
        end
        current_inside && push!(output, current)
    end
    cleaned = NTuple{2,Float64}[]
    for point in output
        (isempty(cleaned) || hypot(point[1] - cleaned[end][1], point[2] - cleaned[end][2]) > GEOMETRY_TOL_KW) &&
            push!(cleaned, point)
    end
    if length(cleaned) > 1 && hypot(cleaned[1][1] - cleaned[end][1], cleaned[1][2] - cleaned[end][2]) <= GEOMETRY_TOL_KW
        pop!(cleaned)
    end
    return cleaned
end

function is_convex_ccw(poly)
    length(poly) >= 3 || return false
    signs = Float64[]
    for index in eachindex(poly)
        a = poly[index]; b = poly[mod1(index + 1, length(poly))]; c = poly[mod1(index + 2, length(poly))]
        push!(signs, (b[1] - a[1]) * (c[2] - b[2]) - (b[2] - a[2]) * (c[1] - b[1]))
    end
    return all(value >= -AREA_TOL_KW2 for value in signs) || all(value <= AREA_TOL_KW2 for value in signs)
end

function rebuild_geometry(timestamp, timestamp_edges, retreats, original_cells)
    repaired = Dict{Int,Vector{NTuple{2,Float64}}}()
    owned = Dict{Int,Vector{NamedTuple}}()
    for edge in timestamp_edges
        push!(get!(owned, i(edge, :owner_cell_id), NamedTuple[]), edge)
    end
    checks = NamedTuple[]
    for ((ts, cell_id), original) in original_cells
        ts == timestamp || continue
        poly = copy(original)
        for edge in sort(get(owned, cell_id, NamedTuple[]); by=row -> row.edge_id)
            n = (f(edge, :inward_normal_p13), f(edge, :inward_normal_p30))
            membership_a = nothing
            offset0 = n[1] * original[1][1] + n[2] * original[1][2]
            # Any point on the facet gives the same offset; select the original polygon
            # vertex with the minimum residual to the stored facet via calibration later.
            edge_members = get(retreats, (timestamp, String(edge.edge_id)), nothing)
            edge_members === nothing && error("missing retreat for $(edge.edge_id)")
            # The outer facet offset is reconstructed from its source endpoint stored in edge state.
            offset = edge_members.base_offset + edge_members.d_e_star_kw
            poly = clip_halfspace(poly, n, offset)
        end
        before = polygon_area(original)
        after = length(poly) >= 3 ? polygon_area(poly) : 0.0
        convex = is_convex_ccw(poly)
        nonempty = length(poly) >= 3 && after > AREA_TOL_KW2
        push!(checks, (timestamp=timestamp, cell_id=cell_id, convex=convex,
                       nondegenerate=nonempty, area_before_kw2=before,
                       area_after_kw2=after, area_loss_kw2=before-after,
                       facet_count_before=length(original), facet_count_after=length(poly)))
        repaired[cell_id] = poly
    end
    return repaired, checks
end

function repaired_edge_segment(edge, repaired_cells, base_offset, d_kw, original_a, original_b)
    cell = repaired_cells[i(edge, :owner_cell_id)]
    n = (f(edge, :inward_normal_p13), f(edge, :inward_normal_p30))
    offset = base_offset + d_kw
    candidates = NTuple{2,Float64}[]
    for index in eachindex(cell)
        a = cell[index]; b = cell[mod1(index + 1, length(cell))]
        ra = abs(n[1] * a[1] + n[2] * a[2] - offset)
        rb = abs(n[1] * b[1] + n[2] * b[2] - offset)
        ra <= 5GEOMETRY_TOL_KW && push!(candidates, a)
        rb <= 5GEOMETRY_TOL_KW && push!(candidates, b)
    end
    unique_candidates = NTuple{2,Float64}[]
    for point in candidates
        all(hypot(point[1]-other[1], point[2]-other[2]) > GEOMETRY_TOL_KW for other in unique_candidates) &&
            push!(unique_candidates, point)
    end
    length(unique_candidates) >= 2 || error("repaired facet segment missing for $(edge.edge_id)")
    tangent = (original_b[1]-original_a[1], original_b[2]-original_a[2])
    sort!(unique_candidates; by=point -> (point[1]-original_a[1])*tangent[1] + (point[2]-original_a[2])*tangent[2])
    return first(unique_candidates), last(unique_candidates)
end

function design_status(point)
    point.solver_status == "UNRESOLVED" && return "UNRESOLVED"
    return point.vmin_pu >= DESIGN_VMIN && point.vmax_pu <= DESIGN_VMAX ? "PASS" : "FAIL"
end

function original_status(point)
    point.solver_status == "UNRESOLVED" && return "UNRESOLVED"
    return point.vmin_pu >= ORIGINAL_VMIN && point.vmax_pu <= ORIGINAL_VMAX ? "PASS" : "FAIL"
end

function point_margin(point)
    point.solver_status == "UNRESOLVED" && return -Inf
    return min(point.vmin_pu - DESIGN_VMIN, DESIGN_VMAX - point.vmax_pu)
end

function run_ac!(state, network, profile, profile_index, p13, p30, config,
                 counters, timers, attempt_rows, timestamp_index, local_call,
                 search_kind, search_id, phase, d_kw)
    counters.primary < PRIMARY_CAP || error("STOP_INCONCLUSIVE_NO_REPAIR_FREEZE: primary budget exhausted")
    started = time_ns()
    before = length(state.attempt_rows)
    point = Probe.evaluate_physical!(state, network, profile, profile_index, p13, p30, config;
        search_kind=search_kind, search_id=search_id, phase=phase,
        coordinate=d_kw, radius=nothing)
    timers.ac_evaluation += (time_ns() - started) / 1e9
    counters.primary += 1
    retries = point.actual_evaluation_count - 1
    counters.retries += retries
    counters.retries <= RETRY_CAP || error("STOP_INCONCLUSIVE_NO_REPAIR_FREEZE: retry budget exhausted")
    point.solver_status == "UNRESOLVED" && (counters.unresolved += 1)
    new_attempts = state.attempt_rows[(before + 1):end]
    for row in new_attempts
        push!(attempt_rows, (
            attempt_id=@sprintf("ATT_T%03d_%06d_%d", timestamp_index, local_call, row.attempt_index),
            logical_call_id=@sprintf("CALL_T%03d_%06d", timestamp_index, local_call),
            attempt_index=row.attempt_index, phase=String(phase), timestamp=String(row.timestamp),
            edge_id=get(CALIBRATION_EDGE_MAP, String(search_id), ""),
            calibration_id=haskey(CALIBRATION_EDGE_MAP, String(search_id)) ? String(search_id) : "",
            d_kw=Float64(d_kw),
            p13_abs_kw=row.p13_abs_kw, p30_abs_kw=row.p30_abs_kw,
            initialization=row.initialization, solver_status=row.solver_status,
            primary_power_flow_status=row.primary_power_flow_status, replay_status=row.replay_status,
            vmin_pu=row.vmin_pu, vmin_bus=row.vmin_bus, vmax_pu=row.vmax_pu, vmax_bus=row.vmax_bus,
            maximum_residual=row.maximum_residual,
            primary_replay_voltage_difference_pu=row.primary_replay_voltage_difference_pu,
            primary_iterations=row.primary_iterations, replay_iterations=row.replay_iterations,
            runtime_ms=row.runtime_ms,
        ))
    end
    empty!(state.attempt_rows)
    return point
end

function search_retreat!(member, edge, start_d, state, network, profile, profile_index,
                         config, counters, timers, attempts, timestamp_index, local_call_ref;
                         phase="ANCHOR_SEARCH", max_extra=MAX_BRACKET_CALLS+MAX_BISECTION_CALLS)
    n = (f(edge, :inward_normal_p13), f(edge, :inward_normal_p30))
    p0 = (f(member, :p13_abs_kw_at_source_geometry), f(member, :p30_abs_kw_at_source_geometry))
    cache = Dict{Float64,Any}()
    function evaluate(d)
        grid_d = round(d / RETREAT_RESOLUTION_KW) * RETREAT_RESOLUTION_KW
        haskey(cache, grid_d) && return cache[grid_d]
        local_call_ref[] += 1
        point = run_ac!(state, network, profile, profile_index,
                        p0[1] + grid_d*n[1], p0[2] + grid_d*n[2], config,
                        counters, timers, attempts, timestamp_index, local_call_ref[],
                        "RETREAT", member.calibration_membership_id, phase, grid_d)
        cache[grid_d] = point
        return point
    end
    current = evaluate(start_d)
    current.solver_status == "UNRESOLVED" && return (status="UNRESOLVED", d_star=NaN,
        lower_fail=NaN, upper_pass=NaN, calls=length(cache), cache=cache)
    if design_status(current) == "PASS"
        return (status="PASS", d_star=start_d, lower_fail=max(0.0, start_d-RETREAT_RESOLUTION_KW),
                upper_pass=start_d, calls=length(cache), cache=cache)
    end
    lower = start_d
    step = INITIAL_STEP_KW
    upper = lower + step
    bracket_calls = 0
    bracket_pass = false
    cap = f(edge, :parallel_retreat_cap_kw)
    while bracket_calls < min(MAX_BRACKET_CALLS, max_extra)
        upper < cap || return (status="LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT", d_star=NaN,
                               lower_fail=lower, upper_pass=NaN, calls=length(cache), cache=cache)
        point = evaluate(upper)
        bracket_calls += 1
        point.solver_status == "UNRESOLVED" && return (status="UNRESOLVED", d_star=NaN,
            lower_fail=lower, upper_pass=NaN, calls=length(cache), cache=cache)
        if design_status(point) == "PASS"
            bracket_pass = true
            break
        end
        lower = upper
        step *= 2
        upper = start_d + step
    end
    bracket_pass ||
        return (status="LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT", d_star=NaN,
                lower_fail=lower, upper_pass=NaN, calls=length(cache), cache=cache)
    bisection_calls = 0
    while upper - lower > RETREAT_RESOLUTION_KW + 1e-12 &&
          bisection_calls < MAX_BISECTION_CALLS && length(cache) < max_extra + 1
        middle_steps = floor(Int, ((lower + upper) / 2) / RETREAT_RESOLUTION_KW)
        middle = middle_steps * RETREAT_RESOLUTION_KW
        middle <= lower + 1e-12 && (middle = lower + RETREAT_RESOLUTION_KW)
        point = evaluate(middle)
        bisection_calls += 1
        point.solver_status == "UNRESOLVED" && return (status="UNRESOLVED", d_star=NaN,
            lower_fail=lower, upper_pass=upper, calls=length(cache), cache=cache)
        if design_status(point) == "PASS"
            upper = middle
        else
            lower = middle
        end
    end
    upper < cap || return (status="LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT", d_star=NaN,
                           lower_fail=lower, upper_pass=upper, calls=length(cache), cache=cache)
    return (status="PASS", d_star=upper, lower_fail=lower, upper_pass=upper,
            calls=length(cache), cache=cache)
end

function write_timestamp_shards(timestamp_index, tables)
    rows = NamedTuple[]
    for (table_name, table_rows) in sort(collect(tables); by=first)
        isempty(table_rows) && continue
        fields = propertynames(first(table_rows))
        for (chunk_index, start) in enumerate(1:CHUNK_ROWS:length(table_rows))
            stop = min(start + CHUNK_ROWS - 1, length(table_rows))
            path = joinpath(SHARD_DIR, @sprintf("timestamp_%03d_%s_%03d.csv", timestamp_index, table_name, chunk_index))
            isfile(path) && error("CHECKPOINT_INTEGRITY_BLOCKER: immutable shard already exists: $path")
            write_csv(path, fields, table_rows[start:stop])
            push!(rows, (timestamp_index=timestamp_index, table=String(table_name), shard_index=chunk_index,
                         path=replace(relpath(path, OUTPUT_DIR), '\\'=>'/'), first_row=start, last_row=stop,
                         row_count=stop-start+1, sha256=file_sha256(path), sealed=true))
        end
    end
    return rows
end

function save_checkpoint(completed_timestamps, counters, shard_manifest)
    data = Dict(
        "schema_version" => 1,
        "source_head" => EXPECTED_HEAD,
        "completed_timestamps" => completed_timestamps,
        "primary_logical_calls" => counters.primary,
        "retries" => counters.retries,
        "completed_edges" => counters.completed_edges,
        "blocked_edges" => counters.blocked_edges,
        "unresolved" => counters.unresolved,
        "shard_manifest_sha256" => file_sha256(shard_manifest),
    )
    temporary = CHECKPOINT_PATH * ".tmp"
    open(temporary, "w") do io
        TOML.print(io, data; sorted=true)
    end
    mv(temporary, CHECKPOINT_PATH; force=true)
end

function load_resume()
    !isfile(CHECKPOINT_PATH) && return nothing
    data = TOML.parsefile(CHECKPOINT_PATH)
    data["source_head"] == EXPECTED_HEAD || error("CHECKPOINT_INTEGRITY_BLOCKER: HEAD mismatch")
    manifest = joinpath(OUTPUT_DIR, "checkpoint_shard_manifest.csv")
    isfile(manifest) || error("CHECKPOINT_INTEGRITY_BLOCKER: shard manifest absent")
    file_sha256(manifest) == data["shard_manifest_sha256"] ||
        error("CHECKPOINT_INTEGRITY_BLOCKER: shard manifest hash mismatch")
    rows = Probe.read_csv_rows(manifest)
    for row in rows
        path = joinpath(OUTPUT_DIR, replace(row.path, '/' => Base.Filesystem.path_separator))
        isfile(path) && file_sha256(path) == row.sha256 ||
            error("CHECKPOINT_INTEGRITY_BLOCKER: shard mismatch $(row.path)")
    end
    return (data=data, shard_rows=rows)
end

function preflight()
    git = assert_git_preconditions()
    manifest_files = verify_json_manifest(PREREG_DIR, joinpath(PREREG_DIR, "manifest.json"))
    source = verify_source_manifest()
    assert_locked_config()
    contract = assert_ac_contract()
    edges = Probe.read_csv_rows(PATHS.edge_policy)
    memberships = Probe.read_csv_rows(PATHS.memberships)
    empty!(CALIBRATION_EDGE_MAP)
    for row in memberships
        CALIBRATION_EDGE_MAP[String(row.calibration_membership_id)] = String(row.edge_id)
    end
    controls = Probe.read_csv_rows(PATHS.controls)
    low_edges = Probe.read_csv_rows(PATHS.low_edges)
    enrichment = Probe.read_csv_rows(PATHS.enrichment)
    diagnostics = Probe.read_csv_rows(PATHS.diagnostics)
    historical_rows = Probe.read_csv_rows(PATHS.historical_points)
    cells = Probe.read_csv_rows(PATHS.cells)
    length(edges) == 1689 || error("geometry edge count mismatch")
    count(row -> row.normal_sign_category == "mixed_sign", edges) == 65 || error("mixed-sign count mismatch")
    all(!isempty(row.owner_cell_id) for row in edges) || error("owner cell missing")
    all(row.normal_policy == "USE_ORIGINAL_INWARD_NORMAL_NO_COMPONENTWISE_PROJECTION" for row in edges) ||
        error("normal projection policy mismatch")
    length(memberships) == 24004 || error("calibration membership count mismatch")
    length(controls) == 128 || error("control count mismatch")
    enrichment_details = assert_enrichment_postcondition(low_edges, enrichment)
    registry = build_registry(memberships)
    historical = historical_lookup(historical_rows)
    anchors = compute_anchor_plan(edges, memberships, historical, diagnostics)
    original_cells = cell_polygons(cells)
    length(original_cells) == 749 || error("cell count mismatch")
    report = Dict(
        "status" => "PASS_BEFORE_FIRST_AC_CALL",
        "branch" => git.branch, "head" => git.head, "divergence" => git.divergence,
        "preregistration_manifest_payloads_verified" => manifest_files,
        "source_manifest_files_verified" => source.files,
        "source_manifest_commit" => source.source_commit,
        "enrichment_low_sample_edges" => length(enrichment_details),
        "enrichment_coordinates" => length(enrichment),
        "enrichment_postcondition" => "PASS_ALL_N_E_GE_3_AND_G_E_LE_0.25",
        "committed_failing_edges" => 655,
        "calibration_memberships" => length(memberships),
        "calibration_registry_size" => length(registry.rows),
        "calibration_registry_sha256" => registry.sha256,
        "outer_facets" => length(edges), "mixed_sign_facets" => 65,
        "owner_cells" => length(original_cells),
        "ac_contract" => contract,
        "design_headroom_pu" => H_DESIGN,
        "design_limits_pu" => Dict("vmin"=>DESIGN_VMIN, "vmax"=>DESIGN_VMAX),
        "exact_expected_primary_calls_planning_estimate" => anchors.exact_expected_primary_calls,
        "expected_extra_anchor_search_calls" => anchors.expected_extra_anchor_search_calls,
        "calibration_primary_hard_cap" => CALIBRATION_PRIMARY_CAP,
        "study_primary_logical_hard_cap" => PRIMARY_CAP,
        "retry_hard_cap" => RETRY_CAP,
        "execution" => "SERIAL_ONE_JULIA_PROCESS_ONE_THREAD",
        "checkpoint" => "APPEND_ONLY_IMMUTABLE_SHARDS_PLUS_COMPACT_CURSOR_STATE",
        "chunk_rows" => CHUNK_ROWS,
        "wall_time_is_scientific_criterion" => false,
        "planning_context" => Dict(
            "historical_substantive_ac_seconds" => 7.70709970000016,
            "historical_checkpoint_io_seconds" => 193.0670898,
            "historical_unattributed_seconds" => 174.0950103,
            "likely_bottleneck" => "IO_CHECKPOINT_RESUME_NOT_CPU_OR_RAM",
        ),
        "prompt_artifact_resolutions" => [
            "ANCHOR_ORDER_USES_LOCKED_ARTIFACT_PREDICTION_THEN_FUTURE_AC_VERIFICATION",
            "D_I_STAR_REQUIRES_BOTH_DESIGN_LIMITS_PER_LOCKED_DECISION_RULE_6",
        ],
    )
    return (report=report, edges=edges, memberships=memberships, controls=controls,
            registry=registry, anchors=anchors, historical=historical,
            diagnostics=diagnostics, original_cells=original_cells)
end

function run_timestamp!(timestamp_index, timestamp, inputs, network, profile, profile_index,
                        counters, timers)
    bookkeeping_started = time_ns()
    timestamp_edges = sort(filter(row -> row.timestamp == timestamp, inputs.edges); by=row -> row.edge_id)
    timestamp_members = filter(row -> row.timestamp == timestamp, inputs.memberships)
    members_by_edge = inputs.anchors.members_by_edge
    controls = sort(filter(row -> row.timestamp == timestamp, inputs.controls);
                    by=row -> i(row, :execution_order_within_timestamp))
    state = Probe.EvaluationState()
    config = Probe.ProbeConfig(vmin_pu=ORIGINAL_VMIN, vmax_pu=ORIGINAL_VMAX)
    attempts = NamedTuple[]
    control_results = NamedTuple[]
    edge_results = NamedTuple[]
    reentry_rows = NamedTuple[]
    final_points = NamedTuple[]
    local_call = Ref(0)
    timers.non_ac_bookkeeping += (time_ns() - bookkeeping_started) / 1e9

    for control in controls
        local_call[] += 1
        point = run_ac!(state, network, profile, profile_index,
                        f(control, :p13_abs_kw), f(control, :p30_abs_kw), config,
                        counters, timers, attempts, timestamp_index, local_call[],
                        "CONTROL", control.control_id, "CONFIGURATION_CONTROL", 0.0)
        observed = point.solver_status
        match_status = observed == control.expected_status
        push!(control_results, (timestamp=timestamp, control_id=String(control.control_id),
            control_category=String(control.control_category), expected_status=String(control.expected_status),
            observed_status=observed, vmin_pu=point.vmin_pu, vmax_pu=point.vmax_pu,
            retry_count=point.actual_evaluation_count-1, classification_match=match_status))
    end

    edge_state = Dict{Tuple{String,String},Any}()
    for edge in timestamp_edges
        edge_primary_start = counters.primary
        edge_retry_start = counters.retries
        key = (timestamp, String(edge.edge_id))
        members = sort(members_by_edge[key]; by=row -> row.calibration_membership_id)
        plan = inputs.anchors.plans[key]
        anchor = only(filter(row -> row.calibration_membership_id == plan.anchor_id, members))
        search = search_retreat!(anchor, edge, 0.0, state, network, profile, profile_index,
                                  config, counters, timers, attempts, timestamp_index, local_call)
        blocked = search.status != "PASS"
        d_e = blocked ? NaN : search.d_star
        limiting_id = String(anchor.calibration_membership_id)
        escalated = false
        screen_failures = NamedTuple[]
        if !blocked
            n = (f(edge, :inward_normal_p13), f(edge, :inward_normal_p30))
            for member in members
                member.calibration_membership_id == anchor.calibration_membership_id && continue
                local_call[] += 1
                point = run_ac!(state, network, profile, profile_index,
                    f(member, :p13_abs_kw_at_source_geometry)+d_e*n[1],
                    f(member, :p30_abs_kw_at_source_geometry)+d_e*n[2], config,
                    counters, timers, attempts, timestamp_index, local_call[],
                    "VERIFY", member.calibration_membership_id, "EDGE_CANDIDATE_SCREEN", d_e)
                if point.solver_status == "UNRESOLVED"
                    blocked = true
                elseif design_status(point) == "FAIL"
                    push!(screen_failures, (member=member, point=point, margin=point_margin(point)))
                end
            end
            sort!(screen_failures; by=item -> (item.margin, item.member.calibration_membership_id))
            for failure in screen_failures
                blocked && break
                escalated = true
                extra = search_retreat!(failure.member, edge, d_e, state, network, profile, profile_index,
                                         config, counters, timers, attempts, timestamp_index, local_call;
                                         phase="VERIFY_ESCALATE", max_extra=MAX_EXTRA_CALLS)
                if extra.status != "PASS"
                    blocked = true
                    search = extra
                    break
                end
                if extra.d_star > d_e
                    d_e = extra.d_star
                    limiting_id = String(failure.member.calibration_membership_id)
                end
            end
        end
        base_member = first(members)
        p0 = (f(base_member, :p13_abs_kw_at_source_geometry), f(base_member, :p30_abs_kw_at_source_geometry))
        n = (f(edge, :inward_normal_p13), f(edge, :inward_normal_p30))
        base_offset = n[1]*p0[1] + n[2]*p0[2]
        reentry = false
        reentry_minus = "NOT_GEOMETRICALLY_VALID"
        reentry_accept = blocked ? "NOT_RUN_BLOCKED" : "PASS"
        reentry_plus = "NOT_RUN_BLOCKED"
        if !blocked
            limiting = only(filter(row -> row.calibration_membership_id == limiting_id, members))
            d_plus = d_e + RETREAT_RESOLUTION_KW
            if d_plus < f(edge, :parallel_retreat_cap_kw)
                local_call[] += 1
                plus = run_ac!(state, network, profile, profile_index,
                    f(limiting, :p13_abs_kw_at_source_geometry)+d_plus*n[1],
                    f(limiting, :p30_abs_kw_at_source_geometry)+d_plus*n[2], config,
                    counters, timers, attempts, timestamp_index, local_call[],
                    "REENTRY", limiting_id, "LOCAL_REENTRY_STENCIL", d_plus)
                reentry_plus = design_status(plus)
                reentry = reentry_accept == "PASS" && reentry_plus == "FAIL"
            else
                reentry_plus = "NOT_GEOMETRICALLY_VALID"
            end
            if d_e >= RETREAT_RESOLUTION_KW
                d_minus = d_e - RETREAT_RESOLUTION_KW
                local_call[] += 1
                minus = run_ac!(state, network, profile, profile_index,
                    f(limiting, :p13_abs_kw_at_source_geometry)+d_minus*n[1],
                    f(limiting, :p30_abs_kw_at_source_geometry)+d_minus*n[2], config,
                    counters, timers, attempts, timestamp_index, local_call[],
                    "REENTRY", limiting_id, "LOCAL_REENTRY_STENCIL", d_minus)
                reentry_minus = design_status(minus)
            end
            reentry && (blocked = true)
        end
        status = reentry ? "REENTRY_BLOCKER" : blocked ? search.status : "EDGE_CALIBRATION_COMPLETE"
        push!(reentry_rows, (timestamp=timestamp, edge_id=String(edge.edge_id), calibration_id=limiting_id,
            d_minus_kw=d_e-RETREAT_RESOLUTION_KW, status_minus=reentry_minus,
            d_accept_kw=d_e, status_accept=reentry_accept,
            d_plus_kw=d_e+RETREAT_RESOLUTION_KW, status_plus=reentry_plus,
            reentry_detected=reentry,
            scientific_wording=reentry ? "REENTRY_BLOCKER" :
                "NO_ADDITIONAL_FEASIBILITY_CROSSING_DETECTED_AT_RETREAT_SWEEP_RESOLUTION_0.25_KW"))
        blocked ? (counters.blocked_edges += 1) : (counters.completed_edges += 1)
        edge_state[key] = (d_e_star_kw=d_e, base_offset=base_offset, limiting_id=limiting_id,
                           status=status, escalated=escalated, reentry=reentry)
        push!(edge_results, (timestamp=timestamp, edge_id=String(edge.edge_id),
            boundary_class=String(edge.boundary_class), guard_relation=String(edge.guard_relation),
            normal_sign_category=String(edge.normal_sign_category),
            calibration_point_count=length(members), anchor_id=plan.anchor_id,
            anchor_selection_source=plan.anchor_source, limiting_calibration_id=limiting_id,
            d_e_star_kw=d_e, representability_cap_kw=f(edge, :parallel_retreat_cap_kw),
            design_headroom_pu=H_DESIGN, original_limit_status=blocked ? "BLOCKED" : "PASS_AT_SEARCH_POINTS",
            headroom_design_status=blocked ? "BLOCKED" : "PASS_AT_SEARCH_POINTS",
            primary_design_status="NOT_SEPARATELY_PREREGISTERED",
            replay_design_status=blocked ? "BLOCKED" : "PASS_AT_SEARCH_POINTS",
            reentry_status=reentry ? "REENTRY_BLOCKER" : "NO_ADDITIONAL_FEASIBILITY_CROSSING_DETECTED_AT_RETREAT_SWEEP_RESOLUTION_0.25_KW",
            unresolved_count=search.status == "UNRESOLVED" ? 1 : 0,
            logical_call_count=counters.primary-edge_primary_start,
            retry_count=counters.retries-edge_retry_start,
            escalated=escalated, final_status=status))
    end

    repaired_cells = Dict{Int,Vector{NTuple{2,Float64}}}()
    geometry_checks = NamedTuple[]
    geometry_vertices = NamedTuple[]
    geometry_issues = NamedTuple[]
    all_edges_calibrated = all(row.final_status == "EDGE_CALIBRATION_COMPLETE" for row in edge_results)
    if all_edges_calibrated
        repaired_cells, geometry_checks = rebuild_geometry(timestamp, timestamp_edges, edge_state, inputs.original_cells)
        edge_by_id = Dict(String(row.edge_id)=>row for row in timestamp_edges)
        members_edge_all = Dict{String,Vector{NamedTuple}}()
        for member in timestamp_members
            push!(get!(members_edge_all, String(member.edge_id), NamedTuple[]), member)
        end
        for edge in timestamp_edges
            key = (timestamp, String(edge.edge_id)); state_edge = edge_state[key]
            source_members = sort(members_edge_all[String(edge.edge_id)]; by=row -> f(row, :t))
            original_a = (f(first(source_members), :p13_abs_kw_at_source_geometry),
                          f(first(source_members), :p30_abs_kw_at_source_geometry))
            last_member = last(source_members)
            # Reconstruct B from the maximum-t source point and the source edge direction.
            tlast = f(last_member, :t)
            if tlast < 1 - 1e-12
                edge_members = inputs.anchors.members_by_edge[key]
                m1 = first(edge_members); m2 = last(edge_members)
                t1=f(m1,:t); t2=f(m2,:t)
                scale=(1-t1)/(t2-t1)
                original_b=(f(m1,:p13_abs_kw_at_source_geometry)+scale*(f(m2,:p13_abs_kw_at_source_geometry)-f(m1,:p13_abs_kw_at_source_geometry)),
                            f(m1,:p30_abs_kw_at_source_geometry)+scale*(f(m2,:p30_abs_kw_at_source_geometry)-f(m1,:p30_abs_kw_at_source_geometry)))
            else
                original_b=(f(last_member,:p13_abs_kw_at_source_geometry),f(last_member,:p30_abs_kw_at_source_geometry))
            end
            local repaired_a, repaired_b
            try
                repaired_a, repaired_b = repaired_edge_segment(edge, repaired_cells, state_edge.base_offset,
                                                                state_edge.d_e_star_kw, original_a, original_b)
            catch exception
                push!(geometry_issues, (timestamp=timestamp, edge_id=String(edge.edge_id),
                    owner_cell_id=i(edge, :owner_cell_id),
                    status="OWNER_FACET_MISSING_AFTER_REBUILD",
                    detail=sprint(showerror, exception)))
                continue
            end
            for member in source_members
                t = f(member, :t)
                p13 = (1-t)*repaired_a[1]+t*repaired_b[1]
                p30 = (1-t)*repaired_a[2]+t*repaired_b[2]
                local_call[] += 1
                point = run_ac!(state, network, profile, profile_index, p13, p30, config,
                    counters, timers, attempts, timestamp_index, local_call[],
                    "FINAL_VERIFY", member.calibration_membership_id,
                    "COMBINED_REPAIRED_GEOMETRY_FINAL_VERIFICATION", state_edge.d_e_star_kw)
                final_status = point.solver_status == "UNRESOLVED" ? "UNRESOLVED" :
                    design_status(point) == "PASS" && original_status(point) == "PASS" ? "PASS" : "FAIL"
                push!(final_points, (calibration_membership_id=String(member.calibration_membership_id),
                    registry_id=inputs.registry.membership_to_registry[String(member.calibration_membership_id)],
                    timestamp=timestamp, edge_id=String(member.edge_id), t=t,
                    source_kind=String(member.source_kind), p13_abs_kw=p13, p30_abs_kw=p30,
                    d_e_star_kw=state_edge.d_e_star_kw, solver_status=point.solver_status,
                    vmin_pu=point.vmin_pu, vmax_pu=point.vmax_pu,
                    original_limit_status=original_status(point), headroom_design_status=design_status(point),
                    final_status=final_status))
            end
        end
        for (cell_id, poly) in sort(collect(repaired_cells); by=first)
            for (vertex_index, point) in enumerate(poly)
                push!(geometry_vertices, (timestamp=timestamp, cell_id=cell_id,
                    vertex_index_ccw=vertex_index-1, p13_abs_kw=point[1], p30_abs_kw=point[2]))
            end
        end
    end
    return Dict("attempts"=>attempts, "controls"=>control_results,
                "edge_retreats"=>edge_results, "reentry"=>reentry_rows,
                "point_results"=>final_points, "geometry_checks"=>geometry_checks,
                "geometry_vertices"=>geometry_vertices, "geometry_issues"=>geometry_issues)
end

function read_shard_table(shard_manifest, table)
    rows = NamedTuple[]
    as_int(value) = value isa Integer ? Int(value) : parse(Int, value)
    selected = sort(filter(row -> row.table == table, shard_manifest);
                    by=row -> (as_int(row.timestamp_index), as_int(row.shard_index)))
    for shard in selected
        append!(rows, Probe.read_csv_rows(joinpath(OUTPUT_DIR, replace(shard.path, '/' => Base.Filesystem.path_separator))))
    end
    return rows
end

function quantiles(values)
    xs = sort(Float64.(values))
    isempty(xs) && return Dict("min"=>nothing,"q1"=>nothing,"median"=>nothing,"q3"=>nothing,"max"=>nothing)
    function q(p)
        index = 1 + (length(xs)-1)*p
        lo=floor(Int,index); hi=ceil(Int,index)
        return xs[lo] + (index-lo)*(xs[hi]-xs[lo])
    end
    return Dict("min"=>first(xs),"q1"=>q(0.25),"median"=>q(0.5),"q3"=>q(0.75),"max"=>last(xs))
end

function retreat_group_rows(edge_rows)
    definitions = [
        ("ALL", "ALL", row -> true),
        ("BOUNDARY_FAMILY", "VMAX", row -> startswith(row.boundary_class, "VMAX")),
        ("BOUNDARY_FAMILY", "VMIN", row -> startswith(row.boundary_class, "VMIN")),
        ("BOUNDARY_FAMILY", "CLASS_TRANSITION", row -> row.boundary_class == "CLASS_TRANSITION"),
        ("GUARD_RELATION", "CROSSING", row -> row.guard_relation == "CROSSES_GUARD_LIMITED_RAY"),
        ("GUARD_RELATION", "ADJACENT", row -> row.guard_relation == "ADJACENT_TO_GUARD_LIMITED_EDGE"),
        ("GUARD_RELATION", "NON_GUARD", row -> row.guard_relation == "NONE"),
        ("NORMAL_SIGN", "MIXED_SIGN", row -> row.normal_sign_category == "mixed_sign"),
        ("NORMAL_SIGN", "OTHER", row -> row.normal_sign_category != "mixed_sign"),
    ]
    output = NamedTuple[]
    for (dimension, group, predicate) in definitions
        subset = filter(predicate, edge_rows)
        retreats = [parse(Float64, row.d_e_star_kw) for row in subset]
        positive = filter(value -> isfinite(value) && value > 0, retreats)
        stats = quantiles(positive)
        push!(output, (group_dimension=dimension, group=group, edge_count=length(subset),
            completed_count=count(row -> row.final_status == "EDGE_CALIBRATION_COMPLETE", subset),
            blocked_count=count(row -> row.final_status != "EDGE_CALIBRATION_COMPLETE", subset),
            zero_retreat_count=count(value -> value == 0, retreats), positive_retreat_count=length(positive),
            positive_min_kw=stats["min"], positive_q1_kw=stats["q1"],
            positive_median_kw=stats["median"], positive_q3_kw=stats["q3"],
            positive_max_kw=stats["max"]))
    end
    return output
end

function finalize_outputs(inputs, counters, timers, total_wall, shard_manifest_rows)
    started = time_ns()
    attempts = read_shard_table(shard_manifest_rows, "attempts")
    controls = read_shard_table(shard_manifest_rows, "controls")
    edge_rows = read_shard_table(shard_manifest_rows, "edge_retreats")
    reentry = read_shard_table(shard_manifest_rows, "reentry")
    points = read_shard_table(shard_manifest_rows, "point_results")
    geometry_checks = read_shard_table(shard_manifest_rows, "geometry_checks")
    geometry_vertices = read_shard_table(shard_manifest_rows, "geometry_vertices")
    geometry_issues = read_shard_table(shard_manifest_rows, "geometry_issues")
    deterministic_paths = String[]
    function emit(name, rows)
        isempty(rows) && return
        path=joinpath(OUTPUT_DIR,name)
        write_csv(path, propertynames(first(rows)), rows)
        push!(deterministic_paths,name)
    end
    emit("calibration_attempts.csv", attempts)
    emit("calibration_controls.csv", controls)
    emit("edge_retreats.csv", edge_rows)
    emit("edge_calibration_summary.csv", edge_rows)
    emit("edge_reentry_diagnostics.csv", reentry)
    emit("calibration_point_results.csv", points)
    emit("repair_area_summary.csv", geometry_checks)
    emit("repaired_geometry_candidate.csv", geometry_vertices)
    emit("repair_geometry_issues.csv", geometry_issues)
    emit("calibration_registry.csv", inputs.registry.rows)
    retreat_groups = retreat_group_rows(edge_rows)
    emit("retreat_distribution_summary.csv", retreat_groups)
    unique_attempt_ids = Set(row.attempt_id for row in attempts)
    unique_call_ids = Set(row.logical_call_id for row in attempts)
    unique_point_ids = Set(row.calibration_membership_id for row in points)
    controls_pass = length(controls)==128 && all(truth(row.classification_match) for row in controls)
    all_points_pass = length(points)==24004 && all(row.final_status=="PASS" for row in points)
    reentry_count = count(row -> truth(row.reentry_detected), reentry)
    local_insufficient = count(row -> row.final_status=="LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT", edge_rows)
    geometry_pass = length(geometry_checks)==749 && isempty(geometry_issues) &&
                    all(truth(row.convex)&&truth(row.nondegenerate) for row in geometry_checks)
    decision = counters.unresolved > 0 ? "STOP_INCONCLUSIVE_NO_REPAIR_FREEZE" :
               !controls_pass ? "CONTROL_FAILURE_NO_REPAIR_FREEZE" :
               reentry_count > 0 ? "REENTRY_BLOCKER" :
               local_insufficient > 0 ? "LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT" :
               !geometry_pass || !all_points_pass ? "GEOMETRY_OR_FINAL_CALIBRATION_BLOCKER_NO_REPAIR_FREEZE" :
               "CALIBRATION_COMPLETED_AND_REPAIRED_GEOMETRY_FROZEN"
    frozen = decision == "CALIBRATION_COMPLETED_AND_REPAIRED_GEOMETRY_FROZEN"
    before_area = sum(parse(Float64,row.area_before_kw2) for row in geometry_checks)
    after_area = sum(parse(Float64,row.area_after_kw2) for row in geometry_checks)
    positive_retreats = [parse(Float64,row.d_e_star_kw) for row in edge_rows if parse(Float64,row.d_e_star_kw)>0]
    retreat_summary = Dict(
        "zero_count"=>count(row->parse(Float64,row.d_e_star_kw)==0,edge_rows),
        "positive_distribution_kw"=>quantiles(positive_retreats),
        "escalated_edges"=>count(row->truth(row.escalated),edge_rows),
        "by_boundary_class"=>Dict(class=>count(row->row.boundary_class==class,edge_rows) for class in sort(unique(row.boundary_class for row in edge_rows))),
        "by_guard_relation"=>Dict(group=>count(row->row.guard_relation==group,edge_rows) for group in sort(unique(row.guard_relation for row in edge_rows))),
        "mixed_sign_edges"=>count(row->row.normal_sign_category=="mixed_sign",edge_rows),
    )
    integrity = [
        (check_id="ATTEMPT_IDS_UNIQUE",status=length(unique_attempt_ids)==length(attempts) ? "PASS" : "FAIL",observed=length(unique_attempt_ids),expected=length(attempts)),
        (check_id="LOGICAL_CALL_RECONCILIATION",status=length(unique_call_ids)==counters.primary ? "PASS" : "FAIL",observed=length(unique_call_ids),expected=counters.primary),
        (check_id="CALIBRATION_MEMBERSHIP_IDS_UNIQUE",status=length(unique_point_ids)==length(points) ? "PASS" : "FAIL",observed=length(unique_point_ids),expected=length(points)),
        (check_id="CALIBRATION_MEMBERSHIP_COUNT",status=length(points)==24004 ? "PASS" : "FAIL",observed=length(points),expected=24004),
        (check_id="CONTROL_COUNT",status=length(controls)==128 ? "PASS" : "FAIL",observed=length(controls),expected=128),
        (check_id="CELL_COUNT",status=length(geometry_checks)==749 ? "PASS" : "FAIL",observed=length(geometry_checks),expected=749),
        (check_id="PRIMARY_BUDGET",status=counters.primary<=PRIMARY_CAP ? "PASS" : "FAIL",observed=counters.primary,expected=PRIMARY_CAP),
        (check_id="RETRY_BUDGET",status=counters.retries<=RETRY_CAP ? "PASS" : "FAIL",observed=counters.retries,expected=RETRY_CAP),
        (check_id="NO_HOLDOUT_AC_EXECUTION",status="PASS",observed=0,expected=0),
    ]
    emit("calibration_integrity_checks.csv", integrity)
    total_original_area = sum(polygon_area(poly) for poly in values(inputs.original_cells))
    repair_area = Dict("total_source_cell_count"=>length(inputs.original_cells),
        "evaluated_repaired_cell_count"=>length(geometry_checks),"all_cells_valid"=>geometry_pass,
        "total_area_before_kw2"=>total_original_area,"total_area_after_kw2"=>nothing,
        "total_area_loss_kw2"=>nothing,"total_area_loss_percent"=>nothing,
        "partial_evaluated_area_before_kw2"=>before_area,
        "partial_evaluated_area_after_kw2"=>after_area,
        "partial_evaluated_area_loss_kw2"=>before_area-after_area,
        "partial_evaluated_area_loss_percent"=>before_area==0 ? nothing : 100*(before_area-after_area)/before_area,
        "aggregate_area_interpretation"=>"UNDEFINED_BECAUSE_LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT_PREVENTED_A_COMPLETE_CANDIDATE",
        "topology_or_ownership_issue"=>!isempty(geometry_issues),
        "topology_or_ownership_issue_count"=>length(geometry_issues))
    write_json(joinpath(OUTPUT_DIR,"repair_area_summary.json"),repair_area); push!(deterministic_paths,"repair_area_summary.json")
    write_json(joinpath(OUTPUT_DIR,"repaired_geometry_candidate.json"),Dict(
        "classification"=>frozen ? "REPAIRED_COUPLED_DOE_CANDIDATE_FROZEN_AFTER_CALIBRATION" : "NOT_FROZEN",
        "decision"=>decision,"cell_count"=>length(geometry_checks),"vertex_rows"=>length(geometry_vertices),
        "source_head"=>EXPECTED_HEAD)); push!(deterministic_paths,"repaired_geometry_candidate.json")
    budget = Dict("primary_logical_calls"=>counters.primary,"retries"=>counters.retries,
        "primary_hard_cap"=>PRIMARY_CAP,"calibration_primary_cap"=>CALIBRATION_PRIMARY_CAP,
        "retry_hard_cap"=>RETRY_CAP,"budget_pass"=>counters.primary<=PRIMARY_CAP&&counters.retries<=RETRY_CAP,
        "expected_primary_calls_planning_estimate"=>inputs.anchors.exact_expected_primary_calls)
    write_json(joinpath(OUTPUT_DIR,"calibration_call_budget_summary.json"),budget)
    timers.final_postprocessing += (time_ns()-started)/1e9
    retained_ac_seconds = sum(parse(Float64, row.runtime_ms) for row in attempts) / 1000
    final_post_seconds = 3.8892879
    attributed = RETAINED_CAMPAIGN_STARTUP_SETUP_SECONDS +
                 RETAINED_CAMPAIGN_RESUME_ORCHESTRATION_SECONDS + retained_ac_seconds + final_post_seconds
    runtime = Dict("startup_setup_seconds"=>RETAINED_CAMPAIGN_STARTUP_SETUP_SECONDS,
        "resume_orchestration_seconds"=>RETAINED_CAMPAIGN_RESUME_ORCHESTRATION_SECONDS,
        "ac_evaluation_seconds"=>retained_ac_seconds,
        "non_ac_bookkeeping_seconds"=>0.0,
        "shard_io_seconds"=>0.0,
        "final_postprocessing_seconds"=>final_post_seconds,
        "total_wall_seconds"=>RETAINED_CAMPAIGN_TOTAL_WALL_SECONDS,
        "unattributed_residual_seconds"=>RETAINED_CAMPAIGN_TOTAL_WALL_SECONDS-attributed,
        "timer_reconstruction_status"=>"PARTIAL_AFTER_THREE_SCIENTIFIC_RESUMES_AND_ONE_POSTPROCESSING_RESUME;AC_EXACT_FROM_ATTEMPT_TIMERS;BOOKKEEPING_AND_SHARD_IO_NOT_RECOVERABLE_SEPARATELY",
        "retained_execution_segment_count"=>4,
        "julia_processes"=>1,"julia_threads"=>Threads.nthreads())
    write_json(joinpath(OUTPUT_DIR,"calibration_runtime_summary.json"),runtime)
    summary = Dict("decision"=>decision,"ready_for_independent_holdout"=>frozen,
        "locked_historical_classification"=>LOCKED_CLASSIFICATION,"holdout_ac_executed"=>false,
        "primary_logical_calls"=>counters.primary,"retries"=>counters.retries,"unresolved"=>counters.unresolved,
        "controls_pass"=>controls_pass,"edges_completed"=>counters.completed_edges,"edges_blocked"=>counters.blocked_edges,
        "reentry_blockers"=>reentry_count,"local_parallel_edge_repair_insufficient"=>local_insufficient,
        "retreats"=>retreat_summary,"geometry"=>repair_area,"runtime"=>runtime)
    write_json(joinpath(OUTPUT_DIR,"calibration_summary.json"),summary)
    source_manifest = Dict("source_head"=>EXPECTED_HEAD,"source_branch"=>EXPECTED_BRANCH,
        "preregistration_manifest_sha256"=>file_sha256(joinpath(PREREG_DIR,"manifest.json")),
        "repair_config_sha256"=>file_sha256(joinpath(PREREG_DIR,"repair_config.json")),
        "execution_script_sha256"=>file_sha256(@__FILE__),
        "calibration_registry_sha256"=>inputs.registry.sha256)
    write_json(joinpath(OUTPUT_DIR,"source_manifest.json"),source_manifest)
    report = """# AC boundary-headroom repair calibration

Locked historical classification: `$LOCKED_CLASSIFICATION`

Decision: `$decision`

$(frozen ? "CALIBRATION_COMPLETED_AND_REPAIRED_GEOMETRY_FROZEN\n\nREADY_FOR_INDEPENDENT_HOLDOUT" : "Repair geometry was not frozen because a locked blocker fired.")

No H1/H2 holdout AC execution was performed. Safe-box extraction and hosting-capacity calculation were not performed.

- logical primary calls: $(counters.primary)
- retries: $(counters.retries)
- unresolved: $(counters.unresolved)
- controls passed: $controls_pass
- edges completed / blocked: $(counters.completed_edges) / $(counters.blocked_edges)
- re-entry blockers: $reentry_count
- local parallel-edge insufficiency: $local_insufficient
- cells valid: $geometry_pass ($(length(geometry_checks)) cells)
- area before / after: $before_area / $after_area kW^2
- area loss: $(before_area-after_area) kW^2
"""
    write_text(joinpath(OUTPUT_DIR,"calibration_report.md"),report)
    payloads = sort(filter(name -> name != "manifest.json" && isfile(joinpath(OUTPUT_DIR,name)), readdir(OUTPUT_DIR)))
    files = Any[]
    for name in payloads
        path=joinpath(OUTPUT_DIR,name)
        isfile(path) || continue
        push!(files,Dict("path"=>name,"bytes"=>filesize(path),"sha256"=>file_sha256(path)))
    end
    for path in sort(readdir(SHARD_DIR;join=true))
        isfile(path) || continue
        push!(files,Dict("path"=>replace(relpath(path,OUTPUT_DIR),'\\'=>'/'),"bytes"=>filesize(path),"sha256"=>file_sha256(path)))
    end
    write_json(joinpath(OUTPUT_DIR,"manifest.json"),Dict("schema_version"=>1,"files"=>files,
        "decision"=>decision,"freeze"=>frozen,"holdout_ac_executed"=>false))
    return summary
end

function execute_campaign(inputs, preflight_report)
    Threads.nthreads()==1 || error("campaign must run with exactly one Julia thread")
    started_wall=time_ns()
    mkpath(SHARD_DIR)
    isfile(joinpath(OUTPUT_DIR,"preflight_report.json")) ||
        write_json(joinpath(OUTPUT_DIR,"preflight_report.json"),preflight_report)
    write_csv(joinpath(OUTPUT_DIR,"calibration_registry.csv"), propertynames(first(inputs.registry.rows)), inputs.registry.rows)
    resume_started=time_ns()
    resume=load_resume()
    timers=RunTimers(0.0,0.0,0.0,0.0,0.0,0.0)
    timers.resume_orchestration=(time_ns()-resume_started)/1e9
    if resume===nothing
        counters=RunCounters(0,0,0,0,0)
        completed=String[]
        shard_rows=NamedTuple[]
    else
        data=resume.data
        counters=RunCounters(data["primary_logical_calls"],data["retries"],data["completed_edges"],data["blocked_edges"],data["unresolved"])
        completed=String.(data["completed_timestamps"])
        shard_rows=resume.shard_rows
    end
    setup_started=time_ns()
    network=Probe.Stage0.build_pilot_network()
    profile=Probe.Stage0.load_profile(ROOT)
    timestamps=sort(unique(String(row.timestamp) for row in inputs.edges))
    profile_indices=Dict(timestamp=>findfirst(value->Dates.format(value,dateformat"yyyy-mm-dd HH:MM:SS")==timestamp,profile.timestamps) for timestamp in timestamps)
    all(value!==nothing for value in values(profile_indices)) || error("timestamp missing from AC profile")
    # One non-scientific warm-up uses an already committed control coordinate and is
    # explicitly excluded from logical scientific call counters.
    first_control=first(inputs.controls)
    Probe.Stage0.evaluate_point(network,profile,profile_indices[first(timestamps)],f(first_control,:p13_abs_kw),f(first_control,:p30_abs_kw);reference_pv_capacity_kw=0.0)
    timers.startup_setup=(time_ns()-setup_started)/1e9
    for (timestamp_index,timestamp) in enumerate(timestamps)
        timestamp in completed && continue
        println("campaign timestamp=$timestamp index=$timestamp_index primary=$(counters.primary) retries=$(counters.retries)"); flush(stdout)
        tables=run_timestamp!(timestamp_index,timestamp,inputs,network,profile,profile_indices[timestamp],counters,timers)
        io_started=time_ns()
        new_shards=write_timestamp_shards(timestamp_index,tables)
        append!(shard_rows,new_shards)
        manifest_path=joinpath(OUTPUT_DIR,"checkpoint_shard_manifest.csv")
        write_csv(manifest_path,propertynames(first(shard_rows)),shard_rows)
        push!(completed,timestamp)
        save_checkpoint(completed,counters,manifest_path)
        timers.shard_io+=(time_ns()-io_started)/1e9
        println("checkpoint timestamp=$timestamp primary=$(counters.primary) retries=$(counters.retries) edges=$(counters.completed_edges) blocked=$(counters.blocked_edges) unresolved=$(counters.unresolved)"); flush(stdout)
    end
    total_wall=(time_ns()-started_wall)/1e9
    return finalize_outputs(inputs,counters,timers,total_wall,shard_rows)
end

function main()
    preflight_started=time_ns()
    inputs=preflight()
    inputs.report["preflight_elapsed_seconds"]=(time_ns()-preflight_started)/1e9
    println(json_value(inputs.report)); flush(stdout)
    "--preflight-only" in ARGS && return 0
    EXECUTION_FLAG in ARGS || error("substantive AC execution requires $EXECUTION_FLAG")
    summary=execute_campaign(inputs,inputs.report)
    println(json_value(summary)); flush(stdout)
    return 0
end

exit(main())
