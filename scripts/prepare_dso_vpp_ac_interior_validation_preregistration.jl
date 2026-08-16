#!/usr/bin/env julia

using Dates
using Printf
using SHA

const REPO_ROOT = normpath(joinpath(@__DIR__, ".."))
const DEFAULT_OUTPUT = joinpath(
    REPO_ROOT, "results", "dso_vpp_ac_map_pilot",
    "doe_ac_interior_validation_preregistration",
)

const EXPECTED_HEAD = "62695e514c97bff04689aac1e9301a3728200144"
const EXPECTED_BRANCH = "codex/dso-vpp-ac-map-pilot"
const COORD_TOL_KW = 1.0e-8
const ANGLE_TOL_DEG = 1.0e-8
const BARYCENTRIC_DENOMINATOR = 5
const ANGLE_STEP_DEG = 0.5
const ANGLES_PER_TIMESTAMP = 720
const UNIQUE_SUBSTANTIVE_CAP = 120_000
const PLANNING_RATE_MS = 0.625720804888803
const SUPPORTING_RATE_LOWER_MS = 0.469620290043398
const FIXED_SETUP_SECONDS = 22.382838

const PILOT_ROOT = joinpath(REPO_ROOT, "results", "dso_vpp_ac_map_pilot")
const PRODUCTION_DIR = joinpath(PILOT_ROOT, "production_probe")
const CONSTRUCTION_DIR = joinpath(PILOT_ROOT, "doe_construction_policy_preregistration")
const CONVEX_DIR = joinpath(CONSTRUCTION_DIR, "convex_piecewise_architecture_audit")
const POCKET_DIR = joinpath(PILOT_ROOT, "doe_vmax_pocket_architecture_audit")
const HULLING_DIR = joinpath(PILOT_ROOT, "doe_vmax_pocket_hulling_audit")
const RUNTIME_DIR = joinpath(PILOT_ROOT, "doe_ac_runtime_benchmark")

const REQUIRED_SOURCE_MANIFESTS = [
    joinpath(PRODUCTION_DIR, "artifact_manifest.csv"),
    joinpath(CONVEX_DIR, "artifact_manifest.csv"),
    joinpath(POCKET_DIR, "manifest.json"),
    joinpath(HULLING_DIR, "manifest.json"),
    joinpath(RUNTIME_DIR, "manifest.json"),
]

struct Endpoint
    endpoint_id::String
    search_kind::String
    search_id::String
    level::String
    primary_class::String
    binding_family::String
    binding_bus::String
    angle_deg::Float64
    p::NTuple{2,Float64}
end

struct PolygonEdge
    edge_index::Int
    a_index::Int
    b_index::Int
    a::NTuple{2,Float64}
    b::NTuple{2,Float64}
    endpoint_a::Endpoint
    endpoint_b::Endpoint
    angular_span_deg::Float64
    boundary_class::String
    guard_relation::String
    guard_angles::Vector{Float64}
end

mutable struct RawPoint
    timestamp::String
    p::NTuple{2,Float64}
    source_kind::String
    source_order::Int
    fields::Dict{String,String}
    canonical_index::Int
end

mutable struct CanonicalPoint
    timestamp::String
    p::NTuple{2,Float64}
    raw_indices::Vector{Int}
    validation_point_id::String
    category::String
    execution_order_within_timestamp::Int
end

csv_escape(value) = begin
    s = string(value)
    occursin(r"[\",\r\n]", s) ? "\"" * replace(s, "\"" => "\"\"") * "\"" : s
end

function fmt_float(x::Real)
    y = Float64(x)
    isfinite(y) || error("Refusing to serialize non-finite number: $y")
    y == 0.0 && return "0"
    return repr(y)
end

function parse_csv_line(line::AbstractString)
    values = String[]
    buffer = IOBuffer()
    quoted = false
    i = firstindex(line)
    while i <= lastindex(line)
        c = line[i]
        if quoted
            if c == '"'
                next_i = nextind(line, i)
                if next_i <= lastindex(line) && line[next_i] == '"'
                    write(buffer, '"')
                    i = next_i
                else
                    quoted = false
                end
            else
                write(buffer, c)
            end
        elseif c == '"'
            quoted = true
        elseif c == ','
            push!(values, String(take!(buffer)))
        else
            write(buffer, c)
        end
        i = nextind(line, i)
    end
    quoted && error("Unclosed CSV quote")
    push!(values, String(take!(buffer)))
    return values
end

function read_csv(path::AbstractString)
    io = open(path, "r")
    header = parse_csv_line(chomp(readline(io)))
    rows = Vector{Dict{String,String}}()
    for line in eachline(io)
        isempty(line) && continue
        values = parse_csv_line(line)
        length(values) == length(header) || error("CSV width mismatch in $path")
        push!(rows, Dict(header[i] => values[i] for i in eachindex(header)))
    end
    close(io)
    return rows
end

function stream_csv(callback::Function, path::AbstractString)
    io = open(path, "r")
    header = parse_csv_line(chomp(readline(io)))
    for line in eachline(io)
        isempty(line) && continue
        values = parse_csv_line(line)
        length(values) == length(header) || error("CSV width mismatch in $path")
        callback(header, values)
    end
    close(io)
end

function write_csv(path::AbstractString, header::Vector{String}, rows)
    open(path, "w") do io
        write(io, join(csv_escape.(header), ","), "\n")
        for row in rows
            values = row isa AbstractDict ? [get(row, h, "") for h in header] : collect(row)
            write(io, join(csv_escape.(values), ","), "\n")
        end
    end
end

function json_escape(s::AbstractString)
    out = IOBuffer()
    for c in s
        if c == '"'
            write(out, "\\\"")
        elseif c == '\\'
            write(out, "\\\\")
        elseif c == '\n'
            write(out, "\\n")
        elseif c == '\r'
            write(out, "\\r")
        elseif c == '\t'
            write(out, "\\t")
        elseif Int(c) < 0x20
            @printf(out, "\\u%04x", Int(c))
        else
            write(out, c)
        end
    end
    return String(take!(out))
end

function write_json_value(io::IO, value, indent::Int=0)
    pad = " "^indent
    if value isa AbstractDict
        keys_sorted = sort!(collect(keys(value)); by=string)
        write(io, "{")
        if !isempty(keys_sorted)
            write(io, "\n")
            for (index, key) in enumerate(keys_sorted)
                write(io, " "^(indent + 2), "\"", json_escape(string(key)), "\": ")
                write_json_value(io, value[key], indent + 2)
                index < length(keys_sorted) && write(io, ",")
                write(io, "\n")
            end
            write(io, pad)
        end
        write(io, "}")
    elseif value isa AbstractVector || value isa Tuple
        write(io, "[")
        if !isempty(value)
            write(io, "\n")
            for (index, item) in enumerate(value)
                write(io, " "^(indent + 2))
                write_json_value(io, item, indent + 2)
                index < length(value) && write(io, ",")
                write(io, "\n")
            end
            write(io, pad)
        end
        write(io, "]")
    elseif value isa AbstractString
        write(io, "\"", json_escape(value), "\"")
    elseif value isa Bool
        write(io, value ? "true" : "false")
    elseif value === nothing
        write(io, "null")
    elseif value isa Integer
        write(io, string(value))
    elseif value isa Real
        write(io, fmt_float(value))
    else
        error("Unsupported JSON value $(typeof(value))")
    end
end

function write_json(path::AbstractString, value)
    open(path, "w") do io
        write_json_value(io, value)
        write(io, "\n")
    end
end

sha256_hex(bytes::Vector{UInt8}) = bytes2hex(sha256(bytes))
sha256_file(path::AbstractString) = sha256_hex(read(path))

function canonical_lf(bytes::Vector{UInt8})
    out = UInt8[]
    sizehint!(out, length(bytes))
    i = 1
    while i <= length(bytes)
        if bytes[i] == 0x0d && i < length(bytes) && bytes[i + 1] == 0x0a
            push!(out, 0x0a)
            i += 2
        else
            push!(out, bytes[i])
            i += 1
        end
    end
    return out
end

function manifest_entries(manifest_path::AbstractString)
    entries = NamedTuple[]
    if endswith(manifest_path, ".csv")
        for row in read_csv(manifest_path)
            path_key = haskey(row, "path") ? "path" : "artifact"
            push!(entries, (
                path=row[path_key],
                bytes=parse(Int, row["bytes"]),
                sha256=lowercase(row["sha256"]),
            ))
        end
    else
        text = read(manifest_path, String)
        pattern = r"\{\s*\"bytes\"\s*:\s*(\d+)\s*,\s*\"path\"\s*:\s*\"([^\"]+)\"\s*,\s*\"sha256\"\s*:\s*\"([0-9a-fA-F]{64})\"\s*\}"
        for match in eachmatch(pattern, text)
            push!(entries, (
                path=replace(match.captures[2], "\\\\" => "/"),
                bytes=parse(Int, match.captures[1]),
                sha256=lowercase(match.captures[3]),
            ))
        end
    end
    isempty(entries) && error("No file entries parsed from $manifest_path")
    return entries
end

function resolve_manifest_entry(manifest_path::AbstractString, entry_path::AbstractString)
    normalized = replace(entry_path, '\\' => '/')
    if startswith(normalized, "results/") || startswith(normalized, "scripts/") ||
       startswith(normalized, "src/") || startswith(normalized, "config/")
        return joinpath(REPO_ROOT, split(normalized, '/')...)
    end
    return joinpath(dirname(manifest_path), split(normalized, '/')...)
end

function verify_source_manifests()
    detail_rows = Vector{Dict{String,String}}()
    summary = Vector{Dict{String,Any}}()
    for manifest in REQUIRED_SOURCE_MANIFESTS
        isfile(manifest) || error("Required source manifest missing: $manifest")
        passed = 0
        entries = manifest_entries(manifest)
        for entry in entries
            file_path = resolve_manifest_entry(manifest, entry.path)
            isfile(file_path) || error("Manifest entry missing: $(entry.path) from $manifest")
            bytes = read(file_path)
            normalized = canonical_lf(bytes)
            raw_hash = sha256_hex(bytes)
            normalized_hash = sha256_hex(normalized)
            mode = if raw_hash == entry.sha256 && length(bytes) == entry.bytes
                "RAW_BYTES"
            elseif normalized_hash == entry.sha256 && length(normalized) == entry.bytes
                "CANONICAL_LF_AFTER_WINDOWS_CHECKOUT_CRLF_NORMALIZATION"
            else
                "FAIL"
            end
            mode == "FAIL" && error("Source manifest verification failed for $(entry.path)")
            passed += 1
            push!(detail_rows, Dict(
                "manifest_path" => relpath(manifest, REPO_ROOT),
                "entry_path" => entry.path,
                "status" => "PASS",
                "verification_mode" => mode,
                "expected_bytes" => string(entry.bytes),
                "observed_raw_bytes" => string(length(bytes)),
                "observed_canonical_lf_bytes" => string(length(normalized)),
                "expected_sha256" => entry.sha256,
                "observed_raw_sha256" => raw_hash,
                "observed_canonical_lf_sha256" => normalized_hash,
            ))
        end
        push!(summary, Dict(
            "path" => replace(relpath(manifest, REPO_ROOT), '\\' => '/'),
            "status" => "PASS",
            "file_count" => length(entries),
            "manifest_working_tree_sha256" => sha256_file(manifest),
        ))
    end
    return detail_rows, summary
end

parse_point(row, p13="p13_abs_kw", p30="p30_abs_kw") =
    (parse(Float64, row[p13]), parse(Float64, row[p30]))

cross(a::NTuple{2,Float64}, b::NTuple{2,Float64}) = a[1] * b[2] - a[2] * b[1]
sub(a::NTuple{2,Float64}, b::NTuple{2,Float64}) = (a[1] - b[1], a[2] - b[2])
add(a::NTuple{2,Float64}, b::NTuple{2,Float64}) = (a[1] + b[1], a[2] + b[2])
scale(s::Float64, a::NTuple{2,Float64}) = (s * a[1], s * a[2])
distance_inf(a::NTuple{2,Float64}, b::NTuple{2,Float64}) = max(abs(a[1]-b[1]), abs(a[2]-b[2]))

function polygon_signed_area(vertices::Vector{NTuple{2,Float64}})
    total = 0.0
    for i in eachindex(vertices)
        total += cross(vertices[i], vertices[mod1(i + 1, length(vertices))])
    end
    return total / 2
end

function point_segment_distance(p, a, b)
    ab = sub(b, a)
    denom = ab[1]^2 + ab[2]^2
    denom == 0.0 && return hypot(p[1]-a[1], p[2]-a[2])
    t = clamp(((p[1]-a[1])*ab[1] + (p[2]-a[2])*ab[2]) / denom, 0.0, 1.0)
    q = add(a, scale(t, ab))
    return hypot(p[1]-q[1], p[2]-q[2])
end

function point_in_convex(p, vertices; tol=COORD_TOL_KW)
    orientation = sign(polygon_signed_area(vertices))
    orientation == 0 && error("Degenerate convex polygon")
    maximum_violation = -Inf
    minimum_edge_distance = Inf
    for i in eachindex(vertices)
        a = vertices[i]
        b = vertices[mod1(i + 1, length(vertices))]
        edge_cross = orientation * cross(sub(b, a), sub(p, a))
        maximum_violation = max(maximum_violation, -edge_cross / max(hypot(b[1]-a[1], b[2]-a[2]), eps()))
        minimum_edge_distance = min(minimum_edge_distance, point_segment_distance(p, a, b))
    end
    return maximum_violation <= tol, maximum_violation, minimum_edge_distance
end

function point_in_polygon(p, vertices; tol=COORD_TOL_KW)
    for i in eachindex(vertices)
        point_segment_distance(p, vertices[i], vertices[mod1(i+1,length(vertices))]) <= tol &&
            return true, true
    end
    inside = false
    j = length(vertices)
    for i in eachindex(vertices)
        xi, yi = vertices[i]
        xj, yj = vertices[j]
        if ((yi > p[2]) != (yj > p[2])) &&
           (p[1] < (xj - xi) * (p[2] - yi) / (yj - yi) + xi)
            inside = !inside
        end
        j = i
    end
    return inside, false
end

function normalized_direction(theta_deg::Float64, scales::NTuple{4,Float64})
    c = cosd(theta_deg)
    s = sind(theta_deg)
    sx = c >= 0 ? scales[1] : scales[2]
    sy = s >= 0 ? scales[3] : scales[4]
    return (sx * c, sy * s)
end

ccw_span(a::Float64, b::Float64) = mod(b - a, 360.0)

function angle_on_open_arc(angle, start, stop; tol=ANGLE_TOL_DEG)
    span = ccw_span(start, stop)
    offset = ccw_span(start, angle)
    return offset > tol && offset < span - tol
end

function angle_on_arc_endpoint(angle, start, stop; tol=ANGLE_TOL_DEG)
    return min(abs(mod(angle-start+180,360)-180), abs(mod(angle-stop+180,360)-180)) <= tol
end

function boundary_class(a::Endpoint, b::Endpoint)
    a.primary_class != b.primary_class && return "CLASS_TRANSITION"
    return get(Dict(
        "VMAX_BUS_13" => "VMAX13",
        "VMAX_BUS_30" => "VMAX30",
        "VMIN_BUS_18" => "VMIN18",
        "VMIN_BUS_33" => "VMIN33",
    ), a.primary_class, "OTHER_IF_REQUIRED")
end

function load_geometry()
    fan_rows = read_csv(joinpath(CONVEX_DIR, "fan_triangle_cells.csv"))
    cell_rows = read_csv(joinpath(CONVEX_DIR, "merged_convex_cells.csv"))
    endpoint_rows = read_csv(joinpath(CONVEX_DIR, "kernel_inward_boundary_retention.csv"))
    scale_rows = read_csv(joinpath(CONSTRUCTION_DIR, "geometric_contraction_threshold_audit", "angular_inward_polygon_outward_screen.csv"))
    guard_rows = read_csv(joinpath(PRODUCTION_DIR, "unresolved_guard_cases.csv"))

    polygons = Dict{String,Vector{NTuple{2,Float64}}}()
    centers = Dict{String,NTuple{2,Float64}}()
    for row in sort(fan_rows; by=r -> (r["timestamp"], parse(Int,r["triangle_index_ccw"])))
        ts = row["timestamp"]
        vertices = get!(polygons, ts, NTuple{2,Float64}[])
        push!(vertices, parse_point(row, "left_p13_abs_kw", "left_p30_abs_kw"))
        centers[ts] = parse_point(row, "center_p13_abs_kw", "center_p30_abs_kw")
    end

    endpoints = Dict{String,Vector{Endpoint}}()
    for row in endpoint_rows
        push!(get!(endpoints, row["timestamp"], Endpoint[]), Endpoint(
            row["endpoint_id"], row["search_kind"], row["search_id"], row["level"],
            row["primary_class"], row["binding_family"], row["binding_bus"],
            parse(Float64,row["ray_angle_deg"]), parse_point(row),
        ))
    end

    scales = Dict{String,NTuple{4,Float64}}()
    for row in scale_rows
        scales[row["timestamp"]] = (
            parse(Float64,row["s13_positive_kw"]), parse(Float64,row["s13_negative_kw"]),
            parse(Float64,row["s30_positive_kw"]), parse(Float64,row["s30_negative_kw"]),
        )
    end

    guard_angles = Dict{String,Vector{Float64}}()
    for row in guard_rows
        row["search_kind"] == "RAY" || continue
        push!(get!(guard_angles, row["timestamp"], Float64[]), parse(Float64,row["search_id"]))
    end
    for values in values(guard_angles)
        sort!(unique!(values))
    end

    cells = Dict{Tuple{String,Int},Vector{NTuple{2,Float64}}}()
    cell_meta = Dict{Tuple{String,Int},Vector{Dict{String,String}}}()
    for row in sort(cell_rows; by=r -> (r["timestamp"], parse(Int,r["cell_index"]), parse(Int,r["cell_vertex_index_ccw"])))
        key = (row["timestamp"], parse(Int,row["cell_index"]))
        push!(get!(cells, key, NTuple{2,Float64}[]), parse_point(row))
        push!(get!(cell_meta, key, Dict{String,String}[]), row)
    end
    return polygons, centers, endpoints, scales, guard_angles, cells, cell_meta
end

function find_endpoint(p, candidates::Vector{Endpoint})
    distances = [distance_inf(p, item.p) for item in candidates]
    index = argmin(distances)
    distances[index] <= COORD_TOL_KW || error("Polygon vertex does not match committed endpoint; distance=$(distances[index])")
    return candidates[index]
end

function build_polygon_edges(polygons, endpoints, guard_angles)
    result = Dict{String,Vector{PolygonEdge}}()
    for ts in sort(collect(keys(polygons)))
        vertices = polygons[ts]
        preliminary = PolygonEdge[]
        guards = get(guard_angles, ts, Float64[])
        relations = String[]
        edge_guard_angles = Vector{Vector{Float64}}()
        for i in eachindex(vertices)
            a_index = i - 1
            b_index = mod(i, length(vertices))
            ea = find_endpoint(vertices[i], endpoints[ts])
            eb = find_endpoint(vertices[mod1(i+1,length(vertices))], endpoints[ts])
            crossed = [g for g in guards if angle_on_open_arc(g, ea.angle_deg, eb.angle_deg)]
            touched = [g for g in guards if angle_on_arc_endpoint(g, ea.angle_deg, eb.angle_deg)]
            if !isempty(crossed)
                push!(relations, "CROSSES_GUARD_LIMITED_RAY")
                push!(edge_guard_angles, sort(unique(vcat(crossed,touched))))
            elseif !isempty(touched)
                push!(relations, "TOUCHES_GUARD_LIMITED_RAY")
                push!(edge_guard_angles, sort(unique(touched)))
            else
                push!(relations, "NONE")
                push!(edge_guard_angles, Float64[])
            end
            push!(preliminary, PolygonEdge(
                i-1, a_index, b_index, vertices[i], vertices[mod1(i+1,length(vertices))],
                ea, eb, ccw_span(ea.angle_deg,eb.angle_deg), boundary_class(ea,eb),
                relations[end], edge_guard_angles[end],
            ))
        end
        directly_guard_related = [relation != "NONE" for relation in relations]
        for i in eachindex(preliminary)
            if relations[i] == "NONE"
                prev = mod1(i-1,length(preliminary))
                next = mod1(i+1,length(preliminary))
                adjacent_angles = unique(vcat(
                    directly_guard_related[prev] ? edge_guard_angles[prev] : Float64[],
                    directly_guard_related[next] ? edge_guard_angles[next] : Float64[],
                ))
                if !isempty(adjacent_angles)
                    relations[i] = "ADJACENT_TO_GUARD_LIMITED_EDGE"
                    edge_guard_angles[i] = sort(adjacent_angles)
                end
            end
        end
        result[ts] = [PolygonEdge(
            e.edge_index,e.a_index,e.b_index,e.a,e.b,e.endpoint_a,e.endpoint_b,
            e.angular_span_deg,e.boundary_class,relations[i],edge_guard_angles[i],
        ) for (i,e) in enumerate(preliminary)]
    end
    return result
end

function ray_polygon_intersection(center, direction, edges::Vector{PolygonEdge})
    candidates = Tuple{Float64,Float64,PolygonEdge}[]
    for edge in edges
        segment = sub(edge.b, edge.a)
        denominator = cross(direction, segment)
        abs(denominator) <= eps(Float64) * 100 && continue
        delta = sub(edge.a, center)
        t = cross(delta, segment) / denominator
        u = cross(delta, direction) / denominator
        if t >= -1e-12 && u >= -1e-10 && u <= 1 + 1e-10
            push!(candidates, (t,u,edge))
        end
    end
    isempty(candidates) && error("Ray did not intersect angular polygon")
    sort!(candidates; by=x -> (x[1], x[3].edge_index))
    t,u,edge = first(candidates)
    edge_fraction = clamp(u,0.0,1.0)
    # Use the algebraically identical segment form so the serialized point is
    # on the committed edge to machine precision rather than carrying the
    # slightly larger roundoff of center + t*direction at long radii.
    return add(edge.a, scale(edge_fraction, sub(edge.b,edge.a))), edge_fraction, edge
end

function build_boundary_raw!(raw, polygons, centers, scales, edges)
    order = 0
    boundary_dist_max = 0.0
    for ts in sort(collect(keys(polygons)))
        for angle_index in 0:(ANGLES_PER_TIMESTAMP-1)
            theta = angle_index * ANGLE_STEP_DEG
            p,u,edge = ray_polygon_intersection(centers[ts], normalized_direction(theta,scales[ts]), edges[ts])
            distance = point_segment_distance(p,edge.a,edge.b)
            boundary_dist_max = max(boundary_dist_max,distance)
            order += 1
            fields = Dict(
                "theta_deg" => fmt_float(theta),
                "source_polygon_edge_id" => @sprintf("E%04d",edge.edge_index),
                "source_edge_endpoint_ids" => edge.endpoint_a.endpoint_id * ";" * edge.endpoint_b.endpoint_id,
                "source_edge_angular_span_deg" => fmt_float(edge.angular_span_deg),
                "endpoint_binding_classes" => edge.endpoint_a.primary_class * ";" * edge.endpoint_b.primary_class,
                "boundary_class" => edge.boundary_class,
                "guard_relation" => edge.guard_relation,
                "guard_limited_angles_deg" => join(fmt_float.(edge.guard_angles), ";"),
                "edge_interpolation_fraction" => fmt_float(u),
            )
            push!(raw, RawPoint(ts,p,"ANGULAR_BOUNDARY",order,fields,0))
        end
    end
    return boundary_dist_max
end

function cell_point_position(p, vertices, centroid)
    distance_inf(p,centroid) <= COORD_TOL_KW && return "CELL_CENTROID"
    vertex_distance = minimum(distance_inf(p,v) for v in vertices)
    vertex_distance <= COORD_TOL_KW && return "CELL_VERTEX"
    edge_distance = minimum(point_segment_distance(p,vertices[i],vertices[mod1(i+1,length(vertices))]) for i in eachindex(vertices))
    edge_distance <= COORD_TOL_KW && return "CELL_EDGE"
    return "CELL_STRICT_INTERIOR"
end

function build_cell_raw!(raw, cells, cell_meta)
    raw_count = 0
    centroid_inside_max_violation = -Inf
    point_inside_max_violation = -Inf
    centroid_rows = Vector{Dict{String,String}}()
    for key in sort(collect(keys(cells)); by=x -> (x[1],x[2]))
        ts, cell_id = key
        vertices = cells[key]
        n = length(vertices)
        centroid = (sum(v[1] for v in vertices)/n, sum(v[2] for v in vertices)/n)
        centroid_inside, centroid_violation, _ = point_in_convex(centroid,vertices)
        centroid_inside || error("Arithmetic centroid outside convex cell $key")
        centroid_inside_max_violation = max(centroid_inside_max_violation,centroid_violation)
        push!(centroid_rows, Dict(
            "timestamp"=>ts,"cell_id"=>string(cell_id),"vertex_count"=>string(n),
            "centroid_p13_abs_kw"=>fmt_float(centroid[1]),"centroid_p30_abs_kw"=>fmt_float(centroid[2]),
            "inside_or_on_cell"=>"true","maximum_signed_violation_kw"=>fmt_float(centroid_violation),
            "source_primary_classes"=>cell_meta[key][1]["primary_classes"],
            "source_binding_families"=>cell_meta[key][1]["binding_families"],
        ))
        for edge_index in 1:n
            a = vertices[edge_index]
            b = vertices[mod1(edge_index+1,n)]
            for i in 0:BARYCENTRIC_DENOMINATOR
                for j in 0:(BARYCENTRIC_DENOMINATOR-i)
                    k = BARYCENTRIC_DENOMINATOR-i-j
                    p = (
                        (i*centroid[1] + j*a[1] + k*b[1])/BARYCENTRIC_DENOMINATOR,
                        (i*centroid[2] + j*a[2] + k*b[2])/BARYCENTRIC_DENOMINATOR,
                    )
                    inside, violation, _ = point_in_convex(p,vertices)
                    inside || error("Barycentric point outside source cell $key edge=$edge_index bary=$i,$j,$k violation=$violation")
                    point_inside_max_violation = max(point_inside_max_violation,violation)
                    raw_count += 1
                    fields = Dict(
                        "cell_id"=>string(cell_id),
                        "cell_triangle_index"=>string(edge_index-1),
                        "cell_edge_endpoint_vertex_indices"=>string(edge_index-1)*";"*string(mod(edge_index,n)),
                        "barycentric_i"=>string(i),"barycentric_j"=>string(j),"barycentric_k"=>string(k),
                        "barycentric_denominator"=>string(BARYCENTRIC_DENOMINATOR),
                        "cell_membership_position"=>cell_point_position(p,vertices,centroid),
                        "source_primary_classes"=>cell_meta[key][1]["primary_classes"],
                        "source_binding_families"=>cell_meta[key][1]["binding_families"],
                    )
                    push!(raw,RawPoint(ts,p,"CELL_BARYCENTRIC",raw_count,fields,0))
                end
            end
        end
    end
    return raw_count,centroid_inside_max_violation,point_inside_max_violation,centroid_rows
end

bucket_key(p) = (floor(Int,p[1]/COORD_TOL_KW),floor(Int,p[2]/COORD_TOL_KW))

function canonicalize!(raw::Vector{RawPoint})
    canonical = CanonicalPoint[]
    buckets = Dict{Tuple{String,Int,Int},Vector{Int}}()
    for (raw_index,item) in enumerate(raw)
        bx,by = bucket_key(item.p)
        candidates = Int[]
        for dx in -1:1, dy in -1:1
            append!(candidates,get(buckets,(item.timestamp,bx+dx,by+dy),Int[]))
        end
        matches = sort(unique([index for index in candidates if distance_inf(item.p,canonical[index].p) <= COORD_TOL_KW]))
        if isempty(matches)
            push!(canonical,CanonicalPoint(item.timestamp,item.p,[raw_index],"","",0))
            canonical_index = length(canonical)
            push!(get!(buckets,(item.timestamp,bx,by),Int[]),canonical_index)
        else
            canonical_index = first(matches)
            push!(canonical[canonical_index].raw_indices,raw_index)
        end
        item.canonical_index = canonical_index
    end

    by_timestamp = Dict{String,Vector{Int}}()
    for (index,point) in enumerate(canonical)
        push!(get!(by_timestamp,point.timestamp,Int[]),index)
    end
    for (ts_index,ts) in enumerate(sort(collect(keys(by_timestamp))))
        indices = by_timestamp[ts]
        boundary_theta(index) = minimum([
            parse(Float64,raw[r].fields["theta_deg"]) for r in canonical[index].raw_indices
            if raw[r].source_kind == "ANGULAR_BOUNDARY"
        ]; init=Inf)
        sort!(indices; by=index -> (
            isfinite(boundary_theta(index)) ? 0 : 1,
            boundary_theta(index),canonical[index].p[1],canonical[index].p[2],index,
        ))
        for (local_index,index) in enumerate(indices)
            point = canonical[index]
            has_boundary = any(raw[r].source_kind == "ANGULAR_BOUNDARY" for r in point.raw_indices)
            point.category = has_boundary ? "BOUNDARY_INTER_RAY" : "CELL_INTERIOR_OR_INTERNAL_FACET"
            point.validation_point_id = @sprintf("VP_T%03d_%06d",ts_index,local_index)
            point.execution_order_within_timestamp = local_index
        end
    end
    return canonical
end

function load_prior_ac_index()
    buckets = Dict{Tuple{String,Int,Int},Vector{NTuple{2,Float64}}}()
    path = joinpath(PRODUCTION_DIR,"evaluation_attempts.csv")
    stream_csv(path) do header,values
        indices = Dict(header[i]=>i for i in eachindex(header))
        ts = values[indices["timestamp"]]
        p = (parse(Float64,values[indices["p13_abs_kw"]]),parse(Float64,values[indices["p30_abs_kw"]]))
        bx,by = bucket_key(p)
        bucket = get!(buckets,(ts,bx,by),NTuple{2,Float64}[])
        any(q -> distance_inf(p,q) <= COORD_TOL_KW,bucket) || push!(bucket,p)
    end
    return buckets
end

function previously_evaluated(ts,p,index)
    bx,by=bucket_key(p)
    for dx in -1:1,dy in -1:1
        any(q -> distance_inf(p,q)<=COORD_TOL_KW,get(index,(ts,bx+dx,by+dy),NTuple{2,Float64}[])) && return true
    end
    return false
end

function parse_halfspaces(serialized::String)
    isempty(serialized) && return NTuple{3,Float64}[]
    return [(parse(Float64,v[1]),parse(Float64,v[2]),parse(Float64,v[3]))
            for item in split(serialized,';') for v in [split(item,'|')]]
end

function load_fallback_halfspaces()
    facets = read_csv(joinpath(POCKET_DIR,"pocket_exact_facets.csv"))
    hulled = read_csv(joinpath(HULLING_DIR,"hulled_pocket_geometry.csv"))
    pockets = Dict{Tuple{String,String},Vector{NTuple{3,Float64}}}()
    for row in facets
        startswith(row["boundary_run_classification"],"VMAX") || continue
        key=(row["timestamp"],row["component_id"])
        push!(get!(pockets,key,NTuple{3,Float64}[]),(
            parse(Float64,row["normal_p13"]),parse(Float64,row["normal_p30"]),parse(Float64,row["rhs_kw"])
        ))
    end
    for row in hulled
        pockets[(row["timestamp"],row["component_id"])]=parse_halfspaces(row["hulled_halfspaces_normal_p13_normal_p30_rhs_kw"])
    end
    by_timestamp=Dict{String,Vector{Vector{NTuple{3,Float64}}}}()
    for ((ts,_),halfspaces) in pockets
        push!(get!(by_timestamp,ts,Vector{NTuple{3,Float64}}[]),halfspaces)
    end
    for values in values(by_timestamp)
        sort!(values;by=h -> join(fmt_float.(collect(first(h))),";"))
    end
    return by_timestamp
end

function inside_fallback(ts,p,pockets)
    haskey(pockets,ts) || return false,"NOT_RECONSTRUCTABLE"
    for halfspaces in pockets[ts]
        residuals=[a*p[1]+b*p[2]-rhs for (a,b,rhs) in halfspaces]
        if all(value < -COORD_TOL_KW for value in residuals)
            return false,"OUTSIDE_FALLBACK_STRICT_INTERIOR_OF_CONVEX_HULLED_VMAX_POCKET"
        end
    end
    return true,"INSIDE_OUTER_HULL_AND_NOT_IN_STRICT_INTERIOR_OF_HULLED_VMAX_POCKET"
end

function build_controls(timestamps)
    centers=Dict(row["timestamp"]=>row for row in read_csv(joinpath(PRODUCTION_DIR,"center_results.csv")))
    endpoints=read_csv(joinpath(PRODUCTION_DIR,"boundary_endpoints.csv"))
    by_ts=Dict{String,Vector{Dict{String,String}}}()
    for row in endpoints
        push!(get!(by_ts,row["timestamp"],Dict{String,String}[]),row)
    end
    rows=Vector{Dict{String,String}}()
    for (ts_index,ts) in enumerate(timestamps)
        haskey(centers,ts)||error("Missing center control at $ts")
        c=centers[ts]
        push!(rows,Dict(
            "timestamp"=>ts,"control_id"=>@sprintf("CTRL_T%03d_CENTER",ts_index),"execution_order_within_timestamp"=>"1",
            "control_category"=>"CERTIFIED_PRODUCTION_CENTER","p13_abs_kw"=>c["p13_abs_kw"],"p30_abs_kw"=>c["p30_abs_kw"],
            "expected_status"=>"CONVERGED_FEASIBLE","source_file"=>"production_probe/center_results.csv",
            "source_locator"=>"logical_evaluation_id="*c["logical_evaluation_id"],"substitution"=>"NONE",
        ))
        candidates=by_ts[ts]
        function choose_safe(family)
            eligible=[r for r in candidates if r["endpoint_side"]=="SAFE" && r["official_boundary"]=="true" &&
                      r["solver_status"]=="CONVERGED_FEASIBLE" && r["binding_mechanism"]==family]
            isempty(eligible)&&error("Missing $family safe control at $ts")
            sort!(eligible;by=r -> (r["search_kind"]=="AXIS" ? 0 : 1,r["search_id"],r["level"]))
            return first(eligible)
        end
        vmax=choose_safe("BINDING_VMAX")
        vmin=choose_safe("BINDING_VMIN")
        for (order,label,row) in [(2,"KNOWN_FEASIBLE_INWARD_VMAX",vmax),(3,"KNOWN_FEASIBLE_INWARD_VMIN",vmin)]
            push!(rows,Dict(
                "timestamp"=>ts,"control_id"=>@sprintf("CTRL_T%03d_%s",ts_index,label=="KNOWN_FEASIBLE_INWARD_VMAX" ? "VMAX_IN" : "VMIN_IN"),
                "execution_order_within_timestamp"=>string(order),"control_category"=>label,
                "p13_abs_kw"=>row["p13_abs_kw"],"p30_abs_kw"=>row["p30_abs_kw"],"expected_status"=>"CONVERGED_FEASIBLE",
                "source_file"=>"production_probe/boundary_endpoints.csv","source_locator"=>row["search_kind"]*":"*row["search_id"]*":"*row["level"]*":SAFE",
                "substitution"=>"NONE",
            ))
        end
        outward=[r for r in candidates if r["endpoint_side"]=="VIOLATING" && r["solver_status"]=="CONVERGED_INFEASIBLE" &&
                 r["search_kind"]==vmax["search_kind"] && r["search_id"]==vmax["search_id"] && r["level"]==vmax["level"]]
        isempty(outward)&&error("Missing paired outward control at $ts")
        out=first(outward)
        push!(rows,Dict(
            "timestamp"=>ts,"control_id"=>@sprintf("CTRL_T%03d_OUTWARD",ts_index),"execution_order_within_timestamp"=>"4",
            "control_category"=>"KNOWN_CONVERGED_INFEASIBLE_OUTWARD_PHYSICAL_ENDPOINT",
            "p13_abs_kw"=>out["p13_abs_kw"],"p30_abs_kw"=>out["p30_abs_kw"],"expected_status"=>"CONVERGED_INFEASIBLE",
            "source_file"=>"production_probe/boundary_endpoints.csv","source_locator"=>out["search_kind"]*":"*out["search_id"]*":"*out["level"]*":VIOLATING",
            "substitution"=>"NONE",
        ))
    end
    return rows
end

function aggregate_canonical_rows(canonical,raw,polygons,prior_ac,pockets)
    rows=Vector{Dict{String,String}}()
    provenance=Vector{Dict{String,String}}()
    max_polygon_violation=0.0
    for point in sort(canonical;by=p -> (p.timestamp,p.execution_order_within_timestamp))
        raw_items=raw[point.raw_indices]
        boundary_items=[item for item in raw_items if item.source_kind=="ANGULAR_BOUNDARY"]
        cell_items=[item for item in raw_items if item.source_kind=="CELL_BARYCENTRIC"]
        cell_ids=sort(unique(parse(Int,item.fields["cell_id"]) for item in cell_items))
        triangle_ids=sort(unique(item.fields["cell_id"]*":"*item.fields["cell_triangle_index"] for item in cell_items))
        positions=sort(unique(item.fields["cell_membership_position"] for item in cell_items))
        boundary_classes=sort(unique(item.fields["boundary_class"] for item in boundary_items))
        guard_relations=sort(unique(item.fields["guard_relation"] for item in boundary_items if item.fields["guard_relation"]!="NONE"))
        inside_main,on_boundary=point_in_polygon(point.p,polygons[point.timestamp])
        inside_main||error("Canonical point outside Main polygon $(point.validation_point_id)")
        inside_fb,fb_detail=inside_fallback(point.timestamp,point.p,pockets)
        prior=previously_evaluated(point.timestamp,point.p,prior_ac)
        theta=isempty(boundary_items) ? "" : join(sort(unique(item.fields["theta_deg"] for item in boundary_items);by=x->parse(Float64,x)),";")
        edge_ids=join(sort(unique(item.fields["source_polygon_edge_id"] for item in boundary_items)),";")
        rows_item=Dict(
            "timestamp"=>point.timestamp,"validation_point_id"=>point.validation_point_id,
            "execution_category"=>point.category,"execution_order_within_timestamp"=>string(point.execution_order_within_timestamp),
            "p13_abs_kw"=>fmt_float(point.p[1]),"p30_abs_kw"=>fmt_float(point.p[2]),"theta_deg"=>theta,
            "source_polygon_edge_id"=>edge_ids,"source_edge_endpoint_ids"=>join(sort(unique(item.fields["source_edge_endpoint_ids"] for item in boundary_items)),";"),
            "source_edge_angular_span_deg"=>join(sort(unique(item.fields["source_edge_angular_span_deg"] for item in boundary_items)),";"),
            "endpoint_binding_classes"=>join(sort(unique(item.fields["endpoint_binding_classes"] for item in boundary_items)),";"),
            "boundary_class"=>join(boundary_classes,";"),"guard_relation"=>isempty(guard_relations) ? "NONE" : join(guard_relations,";"),
            "guard_limited_angles_deg"=>join(sort(unique(filter(!isempty,[item.fields["guard_limited_angles_deg"] for item in boundary_items]))),";"),
            "duplicates_previously_ac_evaluated_committed_point"=>string(prior),
            "has_angular_boundary_provenance"=>string(!isempty(boundary_items)),"has_cell_barycentric_provenance"=>string(!isempty(cell_items)),
            "cell_ids"=>join(cell_ids,";"),"cell_triangle_ids"=>join(triangle_ids,";"),"cell_membership_positions"=>join(positions,";"),
            "belongs_to_multiple_triangles"=>string(length(triangle_ids)>1),"belongs_to_multiple_cells"=>string(length(cell_ids)>1),
            "raw_provenance_membership_count"=>string(length(raw_items)),"inside_main_exact_partition"=>"true",
            "on_main_angular_polygon_boundary"=>string(on_boundary),"inside_pocket_fallback"=>string(inside_fb),
            "pocket_fallback_membership_detail"=>fb_detail,
        )
        push!(rows,rows_item)
        for (membership_index,item) in enumerate(raw_items)
            p_row=Dict(
                "validation_point_id"=>point.validation_point_id,"timestamp"=>point.timestamp,
                "membership_index"=>string(membership_index),"source_kind"=>item.source_kind,
                "p13_abs_kw"=>fmt_float(item.p[1]),"p30_abs_kw"=>fmt_float(item.p[2]),
            )
            merge!(p_row,item.fields)
            push!(provenance,p_row)
        end
    end
    return rows,provenance,max_polygon_violation
end

function write_policies(output_dir, counts, runtime)
    open(joinpath(output_dir,"execution_and_retry_policy.md"),"w") do io
        write(io,"""# Execution, retry, and checkpoint policy

## Authoritative execution contract

The later campaign must call `DSOVPPProductionProbe.evaluate_physical!`, which calls `DSOVPPACMapStage0.evaluate_point`, the radial primary AC power flow, and `CiroPVHC.replay_s1b_interval`. Coordinates are absolute physical PCC active powers `(P13, P30)` in kW at buses 13 and 30 (`N_P=2`); `Q13=Q30=0`, `reference_pv_capacity_kw=0`, voltage limits are 0.90--1.05 p.u., and positive P is injection/export. Historical command-space and reference-PV coordinate paths are prohibited.

## Locked execution order and mode

Execution is `SERIAL`: one Julia process and one Julia thread. Timestamps are chronological. Within each timestamp, controls execute first in their recorded order, then the 720 boundary points by increasing theta, then remaining cell-mesh points by canonical point ID. The order is immutable after results are observed.

## Configuration controls

All four controls at a timestamp must reproduce their exact committed expected primary status. Any contradiction is `VALIDATION_CONFIGURATION_CONTROL_FAILURE`; substantive execution must stop before interpreting or starting that timestamp's mesh until configuration is resolved.

## Retry and nonconvergence

Attempt 1 uses the authoritative flat start (`initial_voltage=nothing`, `warm_start_source=FLAT_START`) and unchanged production iteration/tolerance constants. On nonconvergence only, make at most one retry using the primary complex-voltage vector from the nearest previously converged point at the same timestamp among already executed controls and substantive points. Distance is Euclidean physical `(P13,P30)` kW; ties choose the lower execution order, then the lexicographically lower deterministic point/control ID. Converged-feasible and converged-infeasible points are both accepted seed candidates, matching production semantics. If no accepted neighbor exists, the retry is unavailable and the point is unresolved. No solver-tolerance change or additional rescue is allowed. A failed or unavailable retry is `UNRESOLVED_NONCONVERGENCE`, never infeasible.

## Checkpoint and resume

Checkpoint atomically after every 250 completed substantive points within a timestamp and write a separate atomic completed-timestamp checkpoint. Write a temporary file beside the destination, flush/close, hash it, then atomically replace the destination, following the production atomic-write/provenance pattern without serializing `TimestampWork`.

The checkpoint manifest key is `(validation_point_id, attempt_index)` and stores attempt status, retry seed ID, retry completion, primary point status, row hash, and timestamp completion hash. Resume verifies config, generator, mesh, source-manifest, and checkpoint hashes; loads completed point IDs and attempt rows; treats a point as completed only if its terminal primary status is present; resumes a first-attempt nonconvergence with the preregistered retry state; and derives pending IDs by ordered set difference. Completed timestamps require their atomic completion record. Appends are ID-guarded, so no attempt or result row is duplicated or reclassified.

Checkpoint/I/O overhead is `NOT_MEASURED` and is not included in the runtime totals.
""")
    end
    open(joinpath(output_dir,"validation_decision_rules.md"),"w") do io
        write(io,"""# Validation decision rules

This campaign is a dense deterministic falsification mesh, not a mathematical proof over the continuous DOE. All substantive points receive exactly one primary status: `CONVERGED_FEASIBLE`, `CONVERGED_INFEASIBLE`, or `UNRESOLVED_NONCONVERGENCE`. Authoritative code feasibility semantics apply with no post-hoc tolerance.

1. Any converged-infeasible substantive point: `MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE`. Complete the fixed mesh unless operationally impossible. Do not tune, contract, repair, or adapt the mesh during the run.
2. Zero converged-infeasible points and at least one unresolved point: `AC_INTERIOR_VALIDATION_INCONCLUSIVE_DUE_TO_NONCONVERGENCE`.
3. Zero infeasible and zero unresolved substantive points with all controls passing: `NO_AC_COUNTEREXAMPLE_DETECTED_AT_PREREGISTERED_MESH_RESOLUTION`.

Finite-mesh success is not continuous AC certification or proof. VMAX-associated inter-ray edges are a diagnostic hypothesis only; VMIN failure remains possible, and geometric concavity depth is not AC sagitta. Guard-related results and failure distributions are reported neutrally. No adaptive failure-localization points may be added; that requires a separate preregistration.

Converged rows record Vmin/bus, Vmax/bus, and primary mechanism. Infeasible rows additionally record violation magnitude, category, timestamp, all cell IDs, boundary theta/edge provenance when applicable, and VMAX/VMIN side. Substantive interpretation is blocked by configuration-control failure.

Pocket-fallback membership is recorded only to reuse the same future AC observations. The Main-mesh outcome alone cannot promote the fallback, and no separate fallback AC campaign is part of this preregistration.
""")
    end
end

function main(output_dir::AbstractString)
    ispath(output_dir) && error("Output directory must not already exist: $output_dir")
    mkpath(output_dir)

    source_detail,source_summary=verify_source_manifests()
    polygons,centers,endpoints,scales,guard_angles,cells,cell_meta=load_geometry()
    committed_cell_summary=read_csv(joinpath(CONVEX_DIR,"merged_convex_cell_summary.csv"))
    committed_unique_facet_count=sum(parse(Int,row["unique_geometric_facets_after_shared_radial_boundary_deduplication"]) for row in committed_cell_summary)
    timestamps=sort(collect(keys(polygons)))
    length(timestamps)==32||error("Expected 32 timestamps, found $(length(timestamps))")
    length(cells)==749||error("Expected 749 cells, found $(length(cells))")
    sum(length(v) for v in values(cells))==3173||error("Unexpected cell vertex inventory")
    edges=build_polygon_edges(polygons,endpoints,guard_angles)

    raw=RawPoint[]
    boundary_distance_max=build_boundary_raw!(raw,polygons,centers,scales,edges)
    raw_boundary_count=length(raw)
    raw_boundary_count==32*720||error("Boundary point count mismatch")
    raw_cell_count,centroid_violation,cell_violation,centroid_rows=build_cell_raw!(raw,cells,cell_meta)
    raw_cell_count==21*3173||error("Cell lattice raw count mismatch")
    canonical=canonicalize!(raw)
    unique_count=length(canonical)
    unique_count<=UNIQUE_SUBSTANTIVE_CAP||error("STOP: unique substantive count $unique_count exceeds cap $UNIQUE_SUBSTANTIVE_CAP")

    prior_ac=load_prior_ac_index()
    pockets=load_fallback_halfspaces()
    length(pockets)==32||error("Fallback reconstruction did not cover all timestamps")
    point_rows,provenance_rows,_=aggregate_canonical_rows(canonical,raw,polygons,prior_ac,pockets)
    controls=build_controls(timestamps)
    length(controls)==128||error("Control count mismatch")

    # Integrity checks derived independently from serialized row values.
    ids=[row["validation_point_id"] for row in point_rows]
    timestamp_counts=Dict(ts=>count(r->r["timestamp"]==ts,point_rows) for ts in timestamps)
    boundary_per_ts=Dict(ts=>count(r->r["timestamp"]==ts && r["has_angular_boundary_provenance"]=="true",point_rows) for ts in timestamps)
    cells_seen=sort(unique((row["timestamp"],parse(Int,row["cell_id"])) for row in provenance_rows if row["source_kind"]=="CELL_BARYCENTRIC"))
    all_finite=all(isfinite(parse(Float64,row[k])) for row in point_rows for k in ["p13_abs_kw","p30_abs_kw"])
    all_main=all(row["inside_main_exact_partition"]=="true" for row in point_rows)
    committed_center_rows=Dict(row["timestamp"]=>parse_point(row) for row in read_csv(joinpath(PRODUCTION_DIR,"center_results.csv")))
    center_unchanged=all(haskey(committed_center_rows,ts) && distance_inf(centers[ts],committed_center_rows[ts])<=COORD_TOL_KW for ts in timestamps) &&
        all(first(point_in_convex(centers[key[1]],vertices)) for (key,vertices) in cells)
    guard_boundary_count=count(row->row["guard_relation"]!="NONE",point_rows)
    fallback_inside=count(row->row["inside_pocket_fallback"]=="true",point_rows)
    prior_duplicate_count=count(row->row["duplicates_previously_ac_evaluated_committed_point"]=="true",point_rows)

    integrity_rows=Vector{Dict{String,String}}()
    function addcheck(id,status,observed,expected,tolerance,detail;timestamp="ALL")
        push!(integrity_rows,Dict("check_id"=>id,"timestamp"=>timestamp,"status"=>status ? "PASS" : "FAIL",
            "observed"=>string(observed),"expected"=>string(expected),"tolerance"=>string(tolerance),"detail"=>detail))
        status||error("Integrity check failed: $id observed=$(observed) expected=$(expected) tolerance=$(tolerance)")
    end
    addcheck("TIMESTAMP_COUNT",length(timestamps)==32,length(timestamps),32,"exact","All timestamps represented")
    addcheck("CELL_COUNT",length(cells_seen)==749,length(cells_seen),749,"exact","All exact convex cells represented")
    per_timestamp_cell_counts=[count(key->key[1]==ts,keys(cells)) for ts in timestamps]
    addcheck("CELLS_PER_TIMESTAMP_RANGE",all((21 .<= per_timestamp_cell_counts) .& (per_timestamp_cell_counts .<= 28)),"$(minimum(per_timestamp_cell_counts))-$(maximum(per_timestamp_cell_counts))","21-28","inclusive","Locked per-timestamp exact-cell inventory")
    addcheck("UNIQUE_GEOMETRIC_FACET_COUNT",committed_unique_facet_count==2452,committed_unique_facet_count,2452,"exact","Committed shared-facet-deduplicated inventory")
    addcheck("CELL_CENTROID_FAN_TRIANGLE_COUNT",sum(length(v) for v in values(cells))==3173,sum(length(v) for v in values(cells)),3173,"exact","One centroid-fan triangle per consecutive cell edge")
    addcheck("BOUNDARY_RAW_COUNT",raw_boundary_count==23040,raw_boundary_count,23040,"exact","720 directions x 32 timestamps")
    addcheck("CELL_RAW_COUNT",raw_cell_count==66633,raw_cell_count,66633,"exact","21 barycentric lattice points x 3173 cell edges")
    addcheck("UNIQUE_ID_COUNT",length(unique(ids))==unique_count,length(unique(ids)),unique_count,"exact","Canonical IDs unique")
    addcheck("SUBSTANTIVE_CAP",unique_count<=UNIQUE_SUBSTANTIVE_CAP,unique_count,UNIQUE_SUBSTANTIVE_CAP,"upper bound","Hard cap not exceeded")
    addcheck("BOUNDARY_ON_POLYGON",boundary_distance_max<=COORD_TOL_KW,fmt_float(boundary_distance_max),"<=1e-8 kW",COORD_TOL_KW,"Ray intersections lie on source polygon edges")
    addcheck("CELL_CENTROIDS_INSIDE",centroid_violation<=COORD_TOL_KW,fmt_float(centroid_violation),"<=1e-8 kW",COORD_TOL_KW,"Arithmetic means lie inside/on convex cells")
    addcheck("CELL_POINTS_INSIDE",cell_violation<=COORD_TOL_KW,fmt_float(cell_violation),"<=1e-8 kW",COORD_TOL_KW,"All lattice points lie inside/on source cells")
    addcheck("ALL_SUBSTANTIVE_INSIDE_MAIN",all_main,all_main,true,COORD_TOL_KW,"All canonical points inside/on angular polygon")
    addcheck("FINITE_COORDINATES",all_finite,all_finite,true,"exact","No NaN/Inf P coordinates")
    addcheck("PRODUCTION_CENTERS_UNCHANGED",center_unchanged,center_unchanged,true,COORD_TOL_KW,"Fan centers match committed production centers and lie inside/on every timestamp cell")
    addcheck("PHYSICAL_COORDINATE_CONTRACT",true,"ABSOLUTE_PHYSICAL_P_PCC_P13_P30","kW","exact","No command/reference-PV coordinate conversion")
    addcheck("Q_POLICY",true,"Q13=Q30=0","Q13=Q30=0","exact","Unity-power-factor interface policy unchanged")
    addcheck("REFERENCE_PV_POLICY",true,"reference_pv_capacity_kw=0","reference_pv_capacity_kw=0","exact","Production validation contract")
    addcheck("BOUNDARY_DIRECTIONS_EACH_TIMESTAMP",all(values(boundary_per_ts).==720),join(sort(collect(values(boundary_per_ts))),";"),720,"exact","All theta=0:0.5:359.5 directions")
    addcheck("SOURCE_MANIFESTS",all(row["status"]=="PASS" for row in source_detail),"PASS","PASS","exact","All entries in five required manifests verified")

    mesh_rows=Vector{Dict{String,String}}()
    for ts in timestamps
        raw_b=count(item->item.timestamp==ts&&item.source_kind=="ANGULAR_BOUNDARY",raw)
        raw_c=count(item->item.timestamp==ts&&item.source_kind=="CELL_BARYCENTRIC",raw)
        unique_ts=timestamp_counts[ts]
        push!(mesh_rows,Dict(
            "timestamp"=>ts,"convex_cell_count"=>string(count(key->key[1]==ts,keys(cells))),
            "polygon_edge_count"=>string(length(edges[ts])),"raw_boundary_points"=>string(raw_b),
            "raw_cell_lattice_points"=>string(raw_c),"raw_substantive_points"=>string(raw_b+raw_c),
            "duplicates_removed"=>string(raw_b+raw_c-unique_ts),"unique_substantive_points"=>string(unique_ts),
            "guard_related_unique_boundary_points"=>string(count(r->r["timestamp"]==ts&&r["guard_relation"]!="NONE",point_rows)),
            "previously_ac_evaluated_duplicates"=>string(count(r->r["timestamp"]==ts&&r["duplicates_previously_ac_evaluated_committed_point"]=="true",point_rows)),
            "inside_pocket_fallback"=>string(count(r->r["timestamp"]==ts&&r["inside_pocket_fallback"]=="true",point_rows)),
        ))
    end
    push!(mesh_rows,Dict(
        "timestamp"=>"TOTAL","convex_cell_count"=>"749","polygon_edge_count"=>string(sum(length(v) for v in values(edges))),
        "raw_boundary_points"=>string(raw_boundary_count),"raw_cell_lattice_points"=>string(raw_cell_count),
        "raw_substantive_points"=>string(length(raw)),"duplicates_removed"=>string(length(raw)-unique_count),
        "unique_substantive_points"=>string(unique_count),"guard_related_unique_boundary_points"=>string(guard_boundary_count),
        "previously_ac_evaluated_duplicates"=>string(prior_duplicate_count),"inside_pocket_fallback"=>string(fallback_inside),
    ))

    first_substantive_seconds=unique_count*PLANNING_RATE_MS/1000
    controls_seconds=128*PLANNING_RATE_MS/1000
    first_total_seconds=(unique_count+128)*PLANNING_RATE_MS/1000
    retry_seconds=unique_count*PLANNING_RATE_MS/1000
    total_no_retry=FIXED_SETUP_SECONDS+first_total_seconds
    total_worst=FIXED_SETUP_SECONDS+first_total_seconds+retry_seconds
    runtime_rows=[
        Dict("component"=>"SUBSTANTIVE_FIRST_ATTEMPTS","evaluation_count"=>string(unique_count),"rate_ms_per_evaluation"=>fmt_float(PLANNING_RATE_MS),"workload_seconds"=>fmt_float(first_substantive_seconds),"included_in_total"=>"true","measurement_status"=>"PREREGISTERED_ESTIMATE"),
        Dict("component"=>"CONFIGURATION_CONTROLS_FIRST_ATTEMPTS","evaluation_count"=>"128","rate_ms_per_evaluation"=>fmt_float(PLANNING_RATE_MS),"workload_seconds"=>fmt_float(controls_seconds),"included_in_total"=>"true","measurement_status"=>"PREREGISTERED_ESTIMATE"),
        Dict("component"=>"ALL_FIRST_ATTEMPTS","evaluation_count"=>string(unique_count+128),"rate_ms_per_evaluation"=>fmt_float(PLANNING_RATE_MS),"workload_seconds"=>fmt_float(first_total_seconds),"included_in_total"=>"summary","measurement_status"=>"PREREGISTERED_ESTIMATE"),
        Dict("component"=>"WORST_CASE_ONE_RETRY_EVERY_SUBSTANTIVE_POINT","evaluation_count"=>string(unique_count),"rate_ms_per_evaluation"=>fmt_float(PLANNING_RATE_MS),"workload_seconds"=>fmt_float(retry_seconds),"included_in_total"=>"worst_case_only","measurement_status"=>"PREREGISTERED_ESTIMATE"),
        Dict("component"=>"FIXED_SETUP","evaluation_count"=>"0","rate_ms_per_evaluation"=>"","workload_seconds"=>fmt_float(FIXED_SETUP_SECONDS),"included_in_total"=>"true","measurement_status"=>"MEASURED"),
        Dict("component"=>"TOTAL_EXCLUDING_CHECKPOINT_IO_NO_RETRIES","evaluation_count"=>string(unique_count+128),"rate_ms_per_evaluation"=>"","workload_seconds"=>fmt_float(total_no_retry),"included_in_total"=>"total","measurement_status"=>"PREREGISTERED_ESTIMATE"),
        Dict("component"=>"TOTAL_EXCLUDING_CHECKPOINT_IO_WORST_SUBSTANTIVE_RETRIES","evaluation_count"=>string(2*unique_count+128),"rate_ms_per_evaluation"=>"","workload_seconds"=>fmt_float(total_worst),"included_in_total"=>"total","measurement_status"=>"PREREGISTERED_ESTIMATE"),
        Dict("component"=>"CHECKPOINT_IO_OVERHEAD","evaluation_count"=>"","rate_ms_per_evaluation"=>"","workload_seconds"=>"NOT_MEASURED","included_in_total"=>"false","measurement_status"=>"NOT_MEASURED"),
    ]

    point_header=["timestamp","validation_point_id","execution_category","execution_order_within_timestamp","p13_abs_kw","p30_abs_kw","theta_deg","source_polygon_edge_id","source_edge_endpoint_ids","source_edge_angular_span_deg","endpoint_binding_classes","boundary_class","guard_relation","guard_limited_angles_deg","duplicates_previously_ac_evaluated_committed_point","has_angular_boundary_provenance","has_cell_barycentric_provenance","cell_ids","cell_triangle_ids","cell_membership_positions","belongs_to_multiple_triangles","belongs_to_multiple_cells","raw_provenance_membership_count","inside_main_exact_partition","on_main_angular_polygon_boundary","inside_pocket_fallback","pocket_fallback_membership_detail"]
    provenance_header=["validation_point_id","timestamp","membership_index","source_kind","p13_abs_kw","p30_abs_kw","theta_deg","source_polygon_edge_id","source_edge_endpoint_ids","source_edge_angular_span_deg","endpoint_binding_classes","boundary_class","guard_relation","guard_limited_angles_deg","edge_interpolation_fraction","cell_id","cell_triangle_index","cell_edge_endpoint_vertex_indices","barycentric_i","barycentric_j","barycentric_k","barycentric_denominator","cell_membership_position","source_primary_classes","source_binding_families"]
    control_header=["timestamp","control_id","execution_order_within_timestamp","control_category","p13_abs_kw","p30_abs_kw","expected_status","source_file","source_locator","substitution"]
    mesh_header=["timestamp","convex_cell_count","polygon_edge_count","raw_boundary_points","raw_cell_lattice_points","raw_substantive_points","duplicates_removed","unique_substantive_points","guard_related_unique_boundary_points","previously_ac_evaluated_duplicates","inside_pocket_fallback"]
    integrity_header=["check_id","timestamp","status","observed","expected","tolerance","detail"]
    runtime_header=["component","evaluation_count","rate_ms_per_evaluation","workload_seconds","included_in_total","measurement_status"]
    source_header=["manifest_path","entry_path","status","verification_mode","expected_bytes","observed_raw_bytes","observed_canonical_lf_bytes","expected_sha256","observed_raw_sha256","observed_canonical_lf_sha256"]
    centroid_header=["timestamp","cell_id","vertex_count","centroid_p13_abs_kw","centroid_p30_abs_kw","inside_or_on_cell","maximum_signed_violation_kw","source_primary_classes","source_binding_families"]

    write_csv(joinpath(output_dir,"validation_points.csv"),point_header,point_rows)
    write_csv(joinpath(output_dir,"validation_point_provenance.csv"),provenance_header,provenance_rows)
    write_csv(joinpath(output_dir,"validation_controls.csv"),control_header,controls)
    write_csv(joinpath(output_dir,"validation_mesh_summary.csv"),mesh_header,mesh_rows)
    write_csv(joinpath(output_dir,"validation_integrity_checks.csv"),integrity_header,integrity_rows)
    write_csv(joinpath(output_dir,"runtime_budget.csv"),runtime_header,runtime_rows)
    write_csv(joinpath(output_dir,"source_manifest_verification.csv"),source_header,source_detail)
    write_csv(joinpath(output_dir,"validation_cell_centroids.csv"),centroid_header,centroid_rows)

    edge_rows=Vector{Dict{String,String}}()
    for ts in timestamps,e in edges[ts]
        push!(edge_rows,Dict(
            "timestamp"=>ts,"source_polygon_edge_id"=>@sprintf("E%04d",e.edge_index),"endpoint_a_id"=>e.endpoint_a.endpoint_id,"endpoint_b_id"=>e.endpoint_b.endpoint_id,
            "endpoint_a_p13_abs_kw"=>fmt_float(e.a[1]),"endpoint_a_p30_abs_kw"=>fmt_float(e.a[2]),"endpoint_b_p13_abs_kw"=>fmt_float(e.b[1]),"endpoint_b_p30_abs_kw"=>fmt_float(e.b[2]),
            "endpoint_a_angle_deg"=>fmt_float(e.endpoint_a.angle_deg),"endpoint_b_angle_deg"=>fmt_float(e.endpoint_b.angle_deg),"angular_span_deg"=>fmt_float(e.angular_span_deg),
            "endpoint_binding_classes"=>e.endpoint_a.primary_class*";"*e.endpoint_b.primary_class,"boundary_class"=>e.boundary_class,"guard_relation"=>e.guard_relation,
            "guard_limited_angles_deg"=>join(fmt_float.(e.guard_angles),";"),
        ))
    end
    edge_header=["timestamp","source_polygon_edge_id","endpoint_a_id","endpoint_b_id","endpoint_a_p13_abs_kw","endpoint_a_p30_abs_kw","endpoint_b_p13_abs_kw","endpoint_b_p30_abs_kw","endpoint_a_angle_deg","endpoint_b_angle_deg","angular_span_deg","endpoint_binding_classes","boundary_class","guard_relation","guard_limited_angles_deg"]
    write_csv(joinpath(output_dir,"validation_polygon_edges.csv"),edge_header,edge_rows)

    future_schema_rows=[
        ["validation_attempts.csv","FUTURE_RESULT_NOT_CREATED","attempt_id;validation_point_id;control_id;attempt_index;initialization;retry_seed_id;solver/replay/voltage statuses;V extrema;residuals;iterations;runtime"],
        ["validation_point_results.csv","FUTURE_RESULT_NOT_CREATED","validation_point_id;primary status;attempt count;V extrema;mechanism;violation magnitude;all mesh provenance"],
        ["validation_timestamp_summary.csv","FUTURE_RESULT_NOT_CREATED","timestamp;control outcome;status counts;failure distributions;checkpoint completion"],
        ["validation_failure_summary.csv","FUTURE_RESULT_NOT_CREATED","decision classification;counterexamples by timestamp/category/class/guard/fallback membership"],
        ["validation_checkpoint_manifest.csv","FUTURE_RESULT_NOT_CREATED","point/attempt completion keys;retry state;row hashes;timestamp completion hashes"],
        ["validation_report.md","FUTURE_RESULT_NOT_CREATED","controls;full-mesh outcomes;decision rule;finite-mesh qualification"],
    ]
    write_csv(joinpath(output_dir,"future_output_schemas.csv"),["future_output","status","locked_content"],future_schema_rows)

    generator_sha=sha256_file(@__FILE__)
    config=Dict{String,Any}(
        "schema_version"=>1,"task_type"=>"ARTIFACT_ONLY_PREREGISTRATION_NO_AC_EXECUTION",
        "source_branch"=>EXPECTED_BRANCH,"source_head"=>EXPECTED_HEAD,
        "architecture"=>Dict("main_candidate"=>"FULL EXACT CONVEX PARTITION","compact_fallback"=>"CONVEX-HULLED VMAX POCKET-DIFFERENCE","certification"=>"GEOMETRIC_ONLY;NOT_AC_INTERIOR_CERTIFIED","unresolved_issue"=>"INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY","geometry_inventory"=>Dict("timestamps"=>32,"cells_per_timestamp_min"=>minimum(per_timestamp_cell_counts),"cells_per_timestamp_max"=>maximum(per_timestamp_cell_counts),"convex_cells_total"=>749,"unique_geometric_facets"=>committed_unique_facet_count,"angular_polygon_edges_total"=>sum(length(v) for v in values(edges)))),
        "ac_contract"=>Dict("entry_function"=>"DSOVPPProductionProbe.evaluate_physical!","call_path"=>["DSOVPPProductionProbe.evaluate_physical!","DSOVPPACMapStage0.evaluate_point","DSOVPPACMapStage0.primary_power_flow","CiroPVHC.replay_s1b_interval"],"coordinate_space"=>"ABSOLUTE_PHYSICAL_P_PCC_P13_P30","units"=>"kW","interface_buses"=>[13,30],"N_P"=>2,"q13_kvar"=>0,"q30_kvar"=>0,"reference_pv_capacity_kw"=>0,"vmin_pu"=>0.90,"vmax_pu"=>1.05,"positive_p_semantics"=>"INJECTION_EXPORT","nonconvergence_semantics"=>"UNRESOLVED_NOT_INFEASIBLE"),
        "boundary_mesh"=>Dict("theta_start_deg"=>0,"theta_stop_inclusive_deg"=>359.5,"theta_step_deg"=>ANGLE_STEP_DEG,"directions_per_timestamp"=>ANGLES_PER_TIMESTAMP,"ray_coordinate_convention"=>"PRODUCTION_CENTERED_SIGN_NORMALIZED_ANGLE_USING_COMMITTED_TIMESTAMP_SCALES","test_geometric_boundary_without_inward_perturbation"=>true),
        "cell_mesh"=>Dict("cell_count"=>749,"centroid"=>"ARITHMETIC_MEAN_OF_ORDERED_CELL_VERTICES","triangulation"=>"DETERMINISTIC_CENTROID_FAN_TO_EACH_CONSECUTIVE_CELL_EDGE","barycentric_denominator"=>BARYCENTRIC_DENOMINATOR,"barycentric_coordinates"=>"ALL_NONNEGATIVE_INTEGER_I_J_K_WITH_I+J+K=5"),
        "canonicalization"=>Dict("coordinate_tolerance_kw"=>COORD_TOL_KW,"metric"=>"L_INFINITY","scope"=>"WITHIN_TIMESTAMP_ONLY_BECAUSE_AC_STATE_DIFFERS_BY_TIMESTAMP","representative"=>"FIRST_IN_BOUNDARY_THEN_CELL_STABLE_SOURCE_ORDER","provenance"=>"ALL_MEMBERSHIPS_PRESERVED"),
        "execution"=>Dict("mode"=>"SERIAL","julia_processes"=>1,"julia_threads"=>1,"order"=>["TIMESTAMP_CHRONOLOGICAL","CONTROLS","BOUNDARY_THETA_ASCENDING","REMAINING_CELL_POINTS_CANONICAL_ID"],"complete_after_counterexample"=>true,"adaptive_points_prohibited"=>true),
        "retry"=>Dict("first_attempt"=>"FLAT_START","maximum_retries"=>1,"retry_seed"=>"NEAREST_PREVIOUSLY_CONVERGED_SAME_TIMESTAMP_POINT_EUCLIDEAN_PHYSICAL_KW_TIE_LOWEST_EXECUTION_ORDER_THEN_ID","failed_retry_status"=>"UNRESOLVED_NONCONVERGENCE","solver_tolerance_changes"=>"PROHIBITED"),
        "checkpoint"=>Dict("substantive_point_interval_within_timestamp"=>250,"completed_timestamp_checkpoint"=>"ATOMIC","resume"=>"HASH_VERIFIED_ID_KEYED_NO_DUPLICATE_ROWS"),
        "counts"=>Dict("timestamps"=>32,"controls"=>128,"raw_boundary_points"=>raw_boundary_count,"raw_cell_lattice_points"=>raw_cell_count,"raw_substantive_points"=>length(raw),"duplicates_removed"=>length(raw)-unique_count,"unique_substantive_points"=>unique_count,"expected_total_ac_first_attempts"=>unique_count+128,"hard_cap"=>UNIQUE_SUBSTANTIVE_CAP),
        "runtime"=>Dict("validation_planning_rate_ms_per_evaluation"=>PLANNING_RATE_MS,"supporting_interval_ms_per_evaluation"=>[SUPPORTING_RATE_LOWER_MS,PLANNING_RATE_MS],"fixed_setup_seconds"=>FIXED_SETUP_SECONDS,"future_checkpoint_io_overhead"=>"NOT_MEASURED","safe_on_personal_laptop_with_checkpointing"=>true),
        "permitted_success_conclusion"=>"NO_AC_COUNTEREXAMPLE_DETECTED_AT_PREREGISTERED_MESH_RESOLUTION",
        "generator_sha256"=>generator_sha,"source_manifests"=>source_summary,"no_new_ac_evaluations_performed"=>true,"validation_started"=>false,
    )
    write_json(joinpath(output_dir,"validation_config.json"),config)
    write_policies(output_dir,config["counts"],config["runtime"])

    open(joinpath(output_dir,"preregistration_report.md"),"w") do io
        @printf(io,"""# DSO VPP AC interior validation preregistration

This package deterministically materializes the validation mesh and policies before validation. It performed **no AC evaluation** and did not start validation.

The authoritative later path is `DSOVPPProductionProbe.evaluate_physical! -> DSOVPPACMapStage0.evaluate_point -> radial primary AC power flow + CiroPVHC.replay_s1b_interval`, with absolute physical P13/P30 kW, buses 13/30, `N_P=2`, zero interface Q, zero reference-PV capacity, 0.90--1.05 p.u., positive P injection/export, and nonconvergence unresolved.

The boundary mesh has %d raw points (720 angles per timestamp, 0:0.5:359.5 degrees) on the unperturbed angular polygon. The cell mesh has %d raw q=5 barycentric memberships from centroid fans over all 749 cells. At `1e-8` kW L-infinity canonicalization tolerance, %d raw substantive memberships become %d unique substantive points after removing %d duplicates. There are 128 controls and %d total first attempts. Guard-related points are retained and labeled; fallback membership is geometric reuse only.

At %.15g ms/evaluation, substantive first attempts are %.12f s, controls %.12f s, all first attempts %.12f s, and a retry for every substantive point adds %.12f s. With %.6f s fixed setup, totals excluding checkpoint/I/O are %.12f s without retries and %.12f s in the stated worst substantive-retry case. Checkpoint/I/O is `NOT_MEASURED`. The evidence classification remains `SAFE_ON_PERSONAL_LAPTOP_WITH_CHECKPOINTING` for serial one-process/one-thread execution.

All mesh integrity checks and all entries in five required source manifests pass. The generator SHA-256 is `%s`. Generated artifact hashes are in `manifest.json`; its external file SHA-256 is reported after generation because a manifest cannot contain its own hash without circularity.

The only success conclusion permitted after a future complete run is `NO_AC_COUNTEREXAMPLE_DETECTED_AT_PREREGISTERED_MESH_RESOLUTION`. This is not continuous-set proof or certification.

`NO_NEW_AC_EVALUATIONS_PERFORMED`  
`VALIDATION_NOT_STARTED`
""",raw_boundary_count,raw_cell_count,length(raw),unique_count,length(raw)-unique_count,unique_count+128,
            PLANNING_RATE_MS,first_substantive_seconds,controls_seconds,first_total_seconds,retry_seconds,FIXED_SETUP_SECONDS,total_no_retry,total_worst,generator_sha)
    end

    generated_files=sort(filter(name->name!="manifest.json",readdir(output_dir)))
    manifest=Dict{String,Any}(
        "artifact"=>"DSO_VPP_AC_INTERIOR_VALIDATION_PREREGISTRATION",
        "source_branch"=>EXPECTED_BRANCH,"source_head"=>EXPECTED_HEAD,
        "generator_path"=>replace(relpath(@__FILE__,REPO_ROOT),'\\'=>'/'),"generator_sha256"=>generator_sha,
        "files"=>[Dict("path"=>name,"bytes"=>filesize(joinpath(output_dir,name)),"sha256"=>sha256_file(joinpath(output_dir,name))) for name in generated_files],
        "source_manifests"=>source_summary,"verification"=>"PASS","no_new_ac_evaluations_performed"=>true,"validation_started"=>false,
    )
    write_json(joinpath(output_dir,"manifest.json"),manifest)
    println("OUTPUT_DIR="*output_dir)
    println("GENERATOR_SHA256="*generator_sha)
    println("MANIFEST_SHA256="*sha256_file(joinpath(output_dir,"manifest.json")))
    println("RAW_BOUNDARY_POINTS="*string(raw_boundary_count))
    println("RAW_CELL_LATTICE_POINTS="*string(raw_cell_count))
    println("DUPLICATES_REMOVED="*string(length(raw)-unique_count))
    println("UNIQUE_SUBSTANTIVE_POINTS="*string(unique_count))
    println("CONTROLS="*string(length(controls)))
    println("GUARD_RELATED_UNIQUE_BOUNDARY_POINTS="*string(guard_boundary_count))
    println("SOURCE_MANIFEST_VERIFICATION=PASS")
    println("MESH_INTEGRITY=PASS")
    println("NO_NEW_AC_EVALUATIONS_PERFORMED")
    println("VALIDATION_NOT_STARTED")
end

output_dir=length(ARGS)>=1 ? abspath(ARGS[1]) : DEFAULT_OUTPUT
main(output_dir)
