module DSOVPPProductionProbe

using CiroPVHC
using Dates
using Printf
using SHA
using Serialization
using TOML

include("dso_vpp_ac_map_stage0.jl")
const Stage0 = DSOVPPACMapStage0

const IMPLEMENTATION_ID = "CiroPVHC.DSOVPPProductionProbe.radial_bfs.v1"
const EXECUTION_FLAG = "--execute-preregistered-production-probe"
const BASE_ANGLES_DEG = collect(0.0:10.0:350.0)

Base.@kwdef struct ProbeConfig
    vmin_pu::Float64 = 0.90
    vmax_pu::Float64 = 1.05
    initial_axis_step_kw::Float64 = 100.0
    axis_guard_kw::Float64 = 20_000.0
    axis_sweep_divisor::Int = 20
    axis_sweep_extent_multiplier::Float64 = 2.0
    radial_step::Float64 = 0.05
    radial_guard::Float64 = 2.0
    boundary_width_kw::Float64 = 1.0
    endpoint_voltage_distance_pu::Float64 = 1e-5
    maximum_bisection_refinements::Int = 60
    maximum_center_contractions::Int = 20
end

Base.@kwdef struct PointResult
    coordinate::Float64
    radius::Union{Nothing,Float64} = nothing
    p13_abs_kw::Float64
    p30_abs_kw::Float64
    vmin_pu::Float64 = NaN
    vmin_bus::Union{Nothing,Int} = nothing
    vmax_pu::Float64 = NaN
    vmax_bus::Union{Nothing,Int} = nothing
    solver_status::String = "UNRESOLVED"
    first_attempt_status::String = "NONCONVERGED_FIRST_ATTEMPT"
    retry_status::String = "NOT_RUN"
    logical_evaluation_id::Int = 0
    actual_evaluation_count::Int = 0
end

Base.@kwdef struct AcceptedNeighbor
    p13_abs_kw::Float64
    p30_abs_kw::Float64
    logical_evaluation_id::Int
    voltage::Vector{ComplexF64}
end

Base.@kwdef mutable struct EvaluationState
    next_logical_evaluation_id::Int = 1
    next_attempt_id::Int = 1
    accepted_neighbors::Vector{AcceptedNeighbor} = AcceptedNeighbor[]
    attempt_rows::Vector{NamedTuple} = NamedTuple[]
end

Base.@kwdef mutable struct TimestampWork
    selection::NamedTuple
    profile_index::Int
    evaluation_state::EvaluationState = EvaluationState()
    axes::Vector{NamedTuple} = NamedTuple[]
    center::Union{Nothing,NamedTuple} = nothing
    base_rays::Vector{NamedTuple} = NamedTuple[]
    adaptive_plan::Vector{NamedTuple} = NamedTuple[]
    adaptive_rays::Vector{NamedTuple} = NamedTuple[]
    started_unix::Float64 = time()
    fatal_status::String = ""
end

function normalized_sha256(path::AbstractString)
    source = read(path)
    normalized = Vector{UInt8}(undef, length(source))
    write_index = 0
    read_index = 1
    @inbounds while read_index <= length(source)
        byte = source[read_index]
        if byte == 0x0d
            write_index += 1
            normalized[write_index] = 0x0a
            if read_index < length(source) && source[read_index + 1] == 0x0a
                read_index += 1
            end
        else
            write_index += 1
            normalized[write_index] = byte
        end
        read_index += 1
    end
    resize!(normalized, write_index)
    return bytes2hex(sha256(normalized))
end

file_sha256(path::AbstractString) = bytes2hex(open(sha256, path))

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
    quoted && throw(ArgumentError("unterminated CSV quote"))
    return fields
end

function read_csv_rows(path::AbstractString)
    lines = readlines(path)
    isempty(lines) && throw(ArgumentError("empty CSV: $path"))
    header = Symbol.(split_csv_line(lines[1]))
    rows = NamedTuple[]
    for line in lines[2:end]
        isempty(line) && continue
        values = split_csv_line(line)
        length(values) == length(header) || throw(ArgumentError("CSV width mismatch: $path"))
        push!(rows, NamedTuple{Tuple(header)}(Tuple(values)))
    end
    return rows
end

function csv_value(value)
    value === nothing && return ""
    if value isa AbstractString
        escaped = replace(value, "\"" => "\"\"")
        return occursin(r"[,\"\r\n]", escaped) ? "\"$escaped\"" : escaped
    elseif value isa AbstractFloat
        return isfinite(value) ? @sprintf("%.12g", value) : string(value)
    elseif value isa Bool
        return lowercase(string(value))
    end
    return string(value)
end

function write_csv(path::AbstractString, fields, rows)
    open(path, "w") do io
        println(io, join(string.(fields), ','))
        for row in rows
            println(io, join((csv_value(getproperty(row, field)) for field in fields), ','))
        end
    end
    return path
end

function git_output(root::AbstractString, arguments...)
    command = Cmd(Cmd(vcat(["git"], String.(collect(arguments)))); dir=root)
    return strip(readchomp(command))
end

function validate_locked_config(policy)
    checks = Bool[
        policy["coordinates"]["active_power_coordinate"] == "ABSOLUTE_PHYSICAL_P_PCC_KW",
        policy["coordinates"]["reactive_policy"] == "UNITY_POWER_FACTOR_INTERFACE_POLICY",
        policy["coordinates"]["q_pcc_kvar"] == 0.0,
        policy["voltage_policy_v1"]["minimum_voltage_pu"] == 0.90,
        policy["voltage_policy_v1"]["maximum_voltage_pu"] == 1.05,
        policy["axis_search_g1"]["initial_step_kw"] == 100.0,
        policy["axis_search_g1"]["hard_guard_kw_absolute_per_axis"] == 20_000.0,
        policy["ray_search_s1"]["coarse_step_normalized_r"] == 0.05,
        policy["ray_search_s1"]["guard_normalized_r"] == 2.0,
        policy["direction_grid"]["base_direction_count_per_timestamp"] == 36,
        policy["direction_grid"]["adaptive_levels"] == 1,
        policy["boundary_policy_b1"]["nonconvergence_means_infeasible"] == false,
        policy["boundary_policy_b1"]["official_boundary_endpoint"] == "LAST_CONVERGED_FEASIBLE",
        policy["timestamp_policy_t1"]["selected_timestamp_count"] == 32,
    ]
    all(checks) || throw(ArgumentError("locked production-probe configuration mismatch"))
    return ProbeConfig(
        vmin_pu=policy["voltage_policy_v1"]["minimum_voltage_pu"],
        vmax_pu=policy["voltage_policy_v1"]["maximum_voltage_pu"],
        initial_axis_step_kw=policy["axis_search_g1"]["initial_step_kw"],
        axis_guard_kw=policy["axis_search_g1"]["hard_guard_kw_absolute_per_axis"],
        axis_sweep_divisor=policy["axis_search_g1"]["coarse_step_divisor"],
        axis_sweep_extent_multiplier=policy["axis_search_g1"]["coarse_extent_multiplier"],
        radial_step=policy["ray_search_s1"]["coarse_step_normalized_r"],
        radial_guard=policy["ray_search_s1"]["guard_normalized_r"],
        boundary_width_kw=policy["stopping_and_replay"]["boundary_bracket_width_kw"],
        endpoint_voltage_distance_pu=policy["stopping_and_replay"]["endpoint_voltage_distance_pu"],
        maximum_bisection_refinements=policy["stopping_and_replay"]["maximum_bisection_refinements"],
        maximum_center_contractions=policy["center_policy_c1"]["tier_2_contractions"],
    )
end

function verify_preregistration_manifest(root::AbstractString)
    directory = joinpath(root, "results", "dso_vpp_ac_map_pilot", "production_probe_preregistration")
    manifest_path = joinpath(directory, "production_probe_artifact_manifest.csv")
    rows = read_csv_rows(manifest_path)
    mismatches = String[]
    for row in rows
        println("preflight_hash=$(row.artifact)")
        flush(stdout)
        path = joinpath(root, replace(row.artifact, '/' => Base.Filesystem.path_separator))
        if !isfile(path)
            push!(mismatches, "missing:$(row.artifact)")
        elseif normalized_sha256(path) != row.sha256
            push!(mismatches, "hash:$(row.artifact)")
        end
    end
    isempty(mismatches) || throw(ArgumentError(
        "preregistration manifest verification failed: $(join(mismatches, ';'))",
    ))
    return (
        directory=directory,
        manifest_path=manifest_path,
        manifest_sha256=normalized_sha256(manifest_path),
        config_path=joinpath(root, "config", "dso_vpp_production_probe_preregistration.toml"),
        selected_path=joinpath(directory, "selected_32_timestamps.csv"),
        s0_path=joinpath(directory, "s0_origin_evidence_32_timestamps.csv"),
    )
end

function attempt_class(result, config::ProbeConfig)
    result.power_flow_status == "CONVERGED" || return "NONCONVERGED"
    result.replay_status == "PASSED" || return "NONCONVERGED"
    if result.minimum_voltage_pu < config.vmin_pu || result.maximum_voltage_pu > config.vmax_pu
        return "CONVERGED_INFEASIBLE"
    end
    return "CONVERGED_FEASIBLE"
end

function nearest_accepted_neighbor(state::EvaluationState, p13::Float64, p30::Float64)
    isempty(state.accepted_neighbors) && return nothing
    keys = [
        (hypot(neighbor.p13_abs_kw - p13, neighbor.p30_abs_kw - p30),
         neighbor.logical_evaluation_id, neighbor.p13_abs_kw, neighbor.p30_abs_kw)
        for neighbor in state.accepted_neighbors
    ]
    return state.accepted_neighbors[argmin(keys)]
end

function _attempt_row(result, attempt_id, logical_id, attempt_index, status, initialization,
                      source_id, search_kind, search_id, phase, coordinate, radius)
    return (
        attempt_id=attempt_id,
        logical_evaluation_id=logical_id,
        attempt_index=attempt_index,
        timestamp=result.timestamp,
        search_kind=String(search_kind),
        search_id=String(search_id),
        phase=String(phase),
        coordinate=Float64(coordinate),
        radius=radius === nothing ? NaN : Float64(radius),
        p13_abs_kw=result.p13_vpp_kw,
        p30_abs_kw=result.p30_vpp_kw,
        initialization=String(initialization),
        initialization_source_logical_id=source_id === nothing ? 0 : Int(source_id),
        solver_status=String(status),
        primary_power_flow_status=result.power_flow_status,
        replay_status=result.replay_status,
        voltage_status=result.voltage_status,
        vmin_pu=result.minimum_voltage_pu,
        vmin_bus=result.minimum_voltage_bus,
        vmax_pu=result.maximum_voltage_pu,
        vmax_bus=result.maximum_voltage_bus,
        maximum_residual=result.maximum_absolute_residual,
        primary_replay_voltage_difference_pu=result.primary_replay_max_voltage_difference_pu,
        primary_iterations=result.solver_iterations,
        replay_iterations=result.replay_iterations,
        runtime_ms=result.total_evaluation_ms,
    )
end

function evaluate_physical!(state::EvaluationState, network, profile, profile_index::Int,
                            p13::Real, p30::Real, config::ProbeConfig;
                            search_kind, search_id, phase, coordinate, radius=nothing)
    p13_value = Float64(p13)
    p30_value = Float64(p30)
    logical_id = state.next_logical_evaluation_id
    state.next_logical_evaluation_id += 1
    first = Stage0.evaluate_point(
        network, profile, profile_index, p13_value, p30_value;
        reference_pv_capacity_kw=0.0,
        initial_voltage=nothing,
        warm_start_source="FLAT_START",
        primary_maximum_iterations=Stage0.PRIMARY_MAXIMUM_ITERATIONS,
    )
    first_class = attempt_class(first, config)
    first_record_status = first_class == "NONCONVERGED" ?
                          "NONCONVERGED_FIRST_ATTEMPT" : first_class
    push!(state.attempt_rows, _attempt_row(
        first, state.next_attempt_id, logical_id, 1, first_record_status,
        "FLAT_START", nothing, search_kind, search_id, phase, coordinate, radius,
    ))
    state.next_attempt_id += 1
    if first_class != "NONCONVERGED"
        push!(state.accepted_neighbors, AcceptedNeighbor(
            p13_abs_kw=p13_value, p30_abs_kw=p30_value,
            logical_evaluation_id=logical_id,
            voltage=copy(first.primary_voltage_complex_pu),
        ))
        return PointResult(
            coordinate=Float64(coordinate), radius=radius,
            p13_abs_kw=p13_value, p30_abs_kw=p30_value,
            vmin_pu=first.minimum_voltage_pu, vmin_bus=first.minimum_voltage_bus,
            vmax_pu=first.maximum_voltage_pu, vmax_bus=first.maximum_voltage_bus,
            solver_status=first_class, first_attempt_status=first_record_status,
            retry_status="NOT_RUN", logical_evaluation_id=logical_id,
            actual_evaluation_count=1,
        )
    end

    neighbor = nearest_accepted_neighbor(state, p13_value, p30_value)
    neighbor === nothing && return PointResult(
        coordinate=Float64(coordinate), radius=radius,
        p13_abs_kw=p13_value, p30_abs_kw=p30_value,
        solver_status="UNRESOLVED", first_attempt_status="NONCONVERGED_FIRST_ATTEMPT",
        retry_status="RETRY_UNAVAILABLE_NO_ACCEPTED_NEIGHBOR",
        logical_evaluation_id=logical_id, actual_evaluation_count=1,
    )

    retry = Stage0.evaluate_point(
        network, profile, profile_index, p13_value, p30_value;
        reference_pv_capacity_kw=0.0,
        initial_voltage=neighbor.voltage,
        warm_start_source="NEAREST_ACCEPTED_NEIGHBOR_START",
        primary_maximum_iterations=Stage0.PRIMARY_MAXIMUM_ITERATIONS,
    )
    retry_class = attempt_class(retry, config)
    retry_record_status = retry_class == "NONCONVERGED" ?
                          "NONCONVERGED_AFTER_RETRY" : retry_class
    push!(state.attempt_rows, _attempt_row(
        retry, state.next_attempt_id, logical_id, 2, retry_record_status,
        "NEAREST_ACCEPTED_NEIGHBOR_START", neighbor.logical_evaluation_id,
        search_kind, search_id, phase, coordinate, radius,
    ))
    state.next_attempt_id += 1
    if retry_class != "NONCONVERGED"
        push!(state.accepted_neighbors, AcceptedNeighbor(
            p13_abs_kw=p13_value, p30_abs_kw=p30_value,
            logical_evaluation_id=logical_id,
            voltage=copy(retry.primary_voltage_complex_pu),
        ))
        return PointResult(
            coordinate=Float64(coordinate), radius=radius,
            p13_abs_kw=p13_value, p30_abs_kw=p30_value,
            vmin_pu=retry.minimum_voltage_pu, vmin_bus=retry.minimum_voltage_bus,
            vmax_pu=retry.maximum_voltage_pu, vmax_bus=retry.maximum_voltage_bus,
            solver_status=retry_class,
            first_attempt_status="NONCONVERGED_FIRST_ATTEMPT",
            retry_status=retry_record_status, logical_evaluation_id=logical_id,
            actual_evaluation_count=2,
        )
    end
    return PointResult(
        coordinate=Float64(coordinate), radius=radius,
        p13_abs_kw=p13_value, p30_abs_kw=p30_value,
        vmin_pu=retry.minimum_voltage_pu, vmin_bus=retry.minimum_voltage_bus,
        vmax_pu=retry.maximum_voltage_pu, vmax_bus=retry.maximum_voltage_bus,
        solver_status="UNRESOLVED",
        first_attempt_status="NONCONVERGED_FIRST_ATTEMPT",
        retry_status="NONCONVERGED_AFTER_RETRY", logical_evaluation_id=logical_id,
        actual_evaluation_count=2,
    )
end

point_safe(point::PointResult) = point.solver_status == "CONVERGED_FEASIBLE"
point_violating(point::PointResult) = point.solver_status == "CONVERGED_INFEASIBLE"
point_unresolved(point::PointResult) = point.solver_status == "UNRESOLVED"

function binding_mechanism(point::PointResult, config::ProbeConfig)
    point_violating(point) || return point_unresolved(point) ? "UNRESOLVED" : "NONE"
    lower = point.vmin_pu < config.vmin_pu
    upper = point.vmax_pu > config.vmax_pu
    lower && !upper && return "BINDING_VMIN"
    upper && !lower && return "BINDING_VMAX"
    if lower && upper
        lower_excess = config.vmin_pu - point.vmin_pu
        upper_excess = point.vmax_pu - config.vmax_pu
        return lower_excess >= upper_excess ? "BINDING_VMIN" : "BINDING_VMAX"
    end
    return "UNRESOLVED"
end

function binding_bus(point::PointResult, mechanism::AbstractString)
    mechanism == "BINDING_VMIN" && return point.vmin_bus
    mechanism == "BINDING_VMAX" && return point.vmax_bus
    return nothing
end

function reentry_detected(points)
    saw_feasible = false
    saw_infeasible_after_feasible = false
    for point in points
        if point_safe(point)
            saw_infeasible_after_feasible && return true
            saw_feasible = true
        elseif point_violating(point) && saw_feasible
            saw_infeasible_after_feasible = true
        end
    end
    return false
end

function first_adjacent_bracket(points)
    for index in 2:length(points)
        point_safe(points[index - 1]) && point_violating(points[index]) &&
            return (points[index - 1], points[index])
    end
    return nothing
end

function endpoint_voltage_close(safe::PointResult, violating::PointResult,
                                config::ProbeConfig)
    mechanism = binding_mechanism(violating, config)
    if mechanism == "BINDING_VMIN"
        return safe.vmin_pu - config.vmin_pu <= config.endpoint_voltage_distance_pu &&
               config.vmin_pu - violating.vmin_pu <= config.endpoint_voltage_distance_pu
    elseif mechanism == "BINDING_VMAX"
        return config.vmax_pu - safe.vmax_pu <= config.endpoint_voltage_distance_pu &&
               violating.vmax_pu - config.vmax_pu <= config.endpoint_voltage_distance_pu
    end
    return false
end

function refine_boundary!(evaluator, safe::PointResult, violating::PointResult,
                          physical_width_per_coordinate::Float64, config::ProbeConfig)
    points = PointResult[]
    for step in 1:config.maximum_bisection_refinements
        width_kw = (violating.coordinate - safe.coordinate) * physical_width_per_coordinate
        width_kw <= config.boundary_width_kw && endpoint_voltage_close(safe, violating, config) &&
            return (status="CERTIFIED", safe=safe, violating=violating,
                    points=points, steps=step - 1, width_kw=width_kw)
        midpoint = (safe.coordinate + violating.coordinate) / 2
        point = evaluator(midpoint, "bisection")
        push!(points, point)
        if point_safe(point)
            safe = point
        elseif point_violating(point)
            violating = point
        else
            return (status="UNRESOLVED", safe=safe, violating=violating,
                    points=points, steps=step, width_kw=width_kw)
        end
    end
    width_kw = (violating.coordinate - safe.coordinate) * physical_width_per_coordinate
    status = width_kw <= config.boundary_width_kw && endpoint_voltage_close(safe, violating, config) ?
             "CERTIFIED" : "UNRESOLVED"
    return (status=status, safe=safe, violating=violating,
            points=points, steps=config.maximum_bisection_refinements, width_kw=width_kw)
end

function signed_axis_definition(index::Int)
    definitions = (
        (axis="P13_POSITIVE", bus=13, sign=1.0),
        (axis="P13_NEGATIVE", bus=13, sign=-1.0),
        (axis="P30_POSITIVE", bus=30, sign=1.0),
        (axis="P30_NEGATIVE", bus=30, sign=-1.0),
    )
    return definitions[index]
end

function run_axis!(work::TimestampWork, axis_definition, network, profile,
                   config::ProbeConfig)
    state = work.evaluation_state
    axis_name = axis_definition.axis
    function evaluate_magnitude(magnitude, phase)
        signed = axis_definition.sign * Float64(magnitude)
        p13 = axis_definition.bus == 13 ? signed : 0.0
        p30 = axis_definition.bus == 30 ? signed : 0.0
        return evaluate_physical!(
            state, network, profile, work.profile_index, p13, p30, config;
            search_kind="AXIS", search_id=axis_name, phase=phase,
            coordinate=Float64(magnitude), radius=nothing,
        )
    end

    doubling = PointResult[]
    magnitude = config.initial_axis_step_kw
    transition_scale = nothing
    while true
        point = evaluate_magnitude(magnitude, "doubling")
        push!(doubling, point)
        if point_violating(point)
            transition_scale = magnitude
            break
        end
        magnitude >= config.axis_guard_kw && break
        magnitude = min(config.axis_guard_kw, magnitude * 2)
    end
    scale = transition_scale === nothing ? config.axis_guard_kw : transition_scale
    delta = scale / config.axis_sweep_divisor
    extent = min(config.axis_guard_kw, config.axis_sweep_extent_multiplier * scale)
    sweep = PointResult[]
    for step in 0:round(Int, extent / delta)
        push!(sweep, evaluate_magnitude(step * delta, "coarse_sweep"))
    end
    if last(sweep).coordinate < extent - 1e-9
        push!(sweep, evaluate_magnitude(extent, "coarse_sweep_guard"))
    end

    reentry = reentry_detected(sweep)
    unresolved_count = count(point_unresolved, sweep) + count(point_unresolved, doubling)
    bracket = first_adjacent_bracket(sweep)
    status = "AXIS_UNRESOLVED"
    safe = nothing
    violating = nothing
    refinement_steps = 0
    bracket_width_kw = NaN
    if reentry
        status = "AXIS_REENTRY_DETECTED"
    elseif bracket !== nothing
        candidate_safe, candidate_violating = bracket
        refined = refine_boundary!(
            (coordinate, phase) -> evaluate_magnitude(coordinate, phase),
            candidate_safe, candidate_violating, 1.0, config,
        )
        safe = refined.safe
        violating = refined.violating
        refinement_steps = refined.steps
        bracket_width_kw = refined.width_kw
        status = refined.status == "CERTIFIED" ? "AXIS_CERTIFIED_BOUNDARY" : "AXIS_UNRESOLVED"
    elseif all(point_safe, sweep) && last(sweep).coordinate >= config.axis_guard_kw - 1e-9
        status = "AXIS_UNBOUNDED_WITHIN_GUARD"
    end
    mechanism = violating === nothing ?
                (status == "AXIS_UNBOUNDED_WITHIN_GUARD" ? "AXIS_UNBOUNDED_WITHIN_GUARD" : "UNRESOLVED") :
                binding_mechanism(violating, config)
    official = status == "AXIS_CERTIFIED_BOUNDARY" ? axis_definition.sign * safe.coordinate : NaN
    return (
        selection_index=parse(Int, work.selection.selection_index),
        timestamp=work.selection.timestamp,
        axis=axis_name,
        axis_bus=axis_definition.bus,
        signed_direction=axis_definition.sign > 0 ? "POSITIVE" : "NEGATIVE",
        status=status,
        transition_scale_kw=transition_scale === nothing ? NaN : transition_scale,
        coarse_delta_kw=delta,
        coarse_extent_kw=extent,
        no_reentry_statement=reentry ? "AXIS_REENTRY_DETECTED" :
                             "NO_RE_ENTRY_DETECTED_AT_SWEEP_RESOLUTION_DELTA",
        official_boundary_p_pcc_kw=official,
        safe=safe,
        violating=violating,
        binding_mechanism=mechanism,
        binding_bus=violating === nothing ? nothing : binding_bus(violating, mechanism),
        doubling_point_count=length(doubling),
        sweep_point_count=length(sweep),
        refinement_steps=refinement_steps,
        unresolved_point_count=unresolved_count,
        bracket_width_kw=bracket_width_kw,
    )
end

function axis_lookup(work::TimestampWork, name::AbstractString)
    index = findfirst(axis -> axis.axis == name, work.axes)
    index === nothing && return nothing
    return work.axes[index]
end

function origin_evidence(selection_index::Int, s0_rows)
    row = only(filter(row -> parse(Int, row.selection_index) == selection_index, s0_rows))
    return row
end

function center_point_record(point::PointResult, tier, source, contractions, s0_row)
    return (
        selection_index=parse(Int, s0_row.selection_index),
        timestamp=s0_row.timestamp,
        center_tier=String(tier),
        center_source=String(source),
        contractions=Int(contractions),
        p13_abs_kw=point.p13_abs_kw,
        p30_abs_kw=point.p30_abs_kw,
        solver_status=point.solver_status,
        vmin_pu=point.vmin_pu,
        vmin_bus=point.vmin_bus,
        vmax_pu=point.vmax_pu,
        vmax_bus=point.vmax_bus,
        logical_evaluation_id=point.logical_evaluation_id,
        s0_evidence_sha256=s0_row.s0_row_sha256,
    )
end

function run_center!(work::TimestampWork, network, profile, s0_rows, config::ProbeConfig)
    selection_index = parse(Int, work.selection.selection_index)
    s0_row = origin_evidence(selection_index, s0_rows)
    axes_valid = length(work.axes) == 4 && all(axis -> axis.status == "AXIS_CERTIFIED_BOUNDARY", work.axes)
    if axes_valid
        p13_min = axis_lookup(work, "P13_NEGATIVE").official_boundary_p_pcc_kw
        p13_max = axis_lookup(work, "P13_POSITIVE").official_boundary_p_pcc_kw
        p30_min = axis_lookup(work, "P30_NEGATIVE").official_boundary_p_pcc_kw
        p30_max = axis_lookup(work, "P30_POSITIVE").official_boundary_p_pcc_kw
        midpoint_p13 = (p13_min + p13_max) / 2
        midpoint_p30 = (p30_min + p30_max) / 2
        midpoint = evaluate_physical!(
            work.evaluation_state, network, profile, work.profile_index,
            midpoint_p13, midpoint_p30, config;
            search_kind="CENTER", search_id="TIER_1", phase="independent_center_check",
            coordinate=0.0,
        )
        if point_safe(midpoint)
            return center_point_record(
                midpoint, "CENTER_TIER_1_AXIS_MIDPOINT", "FOUR_FINITE_VALID_AXES", 0, s0_row,
            )
        elseif point_violating(midpoint)
            for contraction in 1:config.maximum_center_contractions
                factor = 2.0^(-contraction)
                candidate = evaluate_physical!(
                    work.evaluation_state, network, profile, work.profile_index,
                    factor * midpoint_p13, factor * midpoint_p30, config;
                    search_kind="CENTER", search_id="TIER_2", phase="origin_contraction",
                    coordinate=Float64(contraction),
                )
                if point_safe(candidate)
                    return center_point_record(
                        candidate, "CENTER_TIER_2_CONTRACTED", "FIRST_CERTIFIED_FEASIBLE_CONTRACTION",
                        contraction, s0_row,
                    )
                end
            end
        end
    end
    evidence_valid = lowercase(s0_row.production_voltage_feasible_090_105) == "true" &&
                     lowercase(s0_row.numerical_validation_passed) == "true"
    evidence_valid || return (
        selection_index=selection_index, timestamp=work.selection.timestamp,
        center_tier="CENTER_UNRESOLVED", center_source="INVALID_S0_EVIDENCE",
        contractions=0, p13_abs_kw=0.0, p30_abs_kw=0.0,
        solver_status="UNRESOLVED", vmin_pu=NaN, vmin_bus=nothing,
        vmax_pu=NaN, vmax_bus=nothing, logical_evaluation_id=0,
        s0_evidence_sha256=s0_row.s0_row_sha256,
    )
    evidence_point = PointResult(
        coordinate=0.0, p13_abs_kw=0.0, p30_abs_kw=0.0,
        vmin_pu=parse(Float64, s0_row.minimum_voltage_pu),
        vmin_bus=parse(Int, s0_row.minimum_voltage_bus),
        vmax_pu=parse(Float64, s0_row.maximum_voltage_pu),
        vmax_bus=parse(Int, s0_row.maximum_voltage_bus),
        solver_status="CONVERGED_FEASIBLE", first_attempt_status="COMMITTED_S0_EVIDENCE",
        retry_status="NOT_APPLICABLE", logical_evaluation_id=0, actual_evaluation_count=0,
    )
    return center_point_record(
        evidence_point, "CENTER_TIER_3_ORIGIN", "TIMESTAMP_SPECIFIC_COMMITTED_S0_EVIDENCE",
        0, s0_row,
    )
end

function radial_scales(work::TimestampWork)
    length(work.axes) == 4 || return nothing
    all(axis -> axis.status == "AXIS_CERTIFIED_BOUNDARY", work.axes) || return nothing
    center = work.center
    p13_min = axis_lookup(work, "P13_NEGATIVE").official_boundary_p_pcc_kw
    p13_max = axis_lookup(work, "P13_POSITIVE").official_boundary_p_pcc_kw
    p30_min = axis_lookup(work, "P30_NEGATIVE").official_boundary_p_pcc_kw
    p30_max = axis_lookup(work, "P30_POSITIVE").official_boundary_p_pcc_kw
    return (
        p13_positive=p13_max - center.p13_abs_kw,
        p13_negative=center.p13_abs_kw - p13_min,
        p30_positive=p30_max - center.p30_abs_kw,
        p30_negative=center.p30_abs_kw - p30_min,
    )
end

function ray_vector(angle_deg::Real, scales)
    theta = deg2rad(Float64(angle_deg))
    cosine = cos(theta)
    sine = sin(theta)
    sx = cosine >= 0 ? scales.p13_positive : scales.p13_negative
    sy = sine >= 0 ? scales.p30_positive : scales.p30_negative
    return (vx=cosine * sx, vy=sine * sy)
end

function unresolved_ray(work::TimestampWork, angle_deg::Real, level::AbstractString,
                        parent_start, parent_end, triggers)
    return (
        selection_index=parse(Int, work.selection.selection_index),
        timestamp=work.selection.timestamp,
        level=String(level), angle_deg=Float64(angle_deg),
        parent_start_angle_deg=parent_start, parent_end_angle_deg=parent_end,
        adaptive_triggers=String(triggers), status="RAY_UNRESOLVED",
        no_reentry_statement="NOT_EVALUATED_INVALID_AXIS_NORMALIZATION",
        official_boundary_r=NaN, safe=nothing, violating=nothing,
        binding_mechanism="UNRESOLVED", binding_bus=nothing,
        sweep_point_count=0, refinement_steps=0, unresolved_point_count=0,
        bracket_width_kw=NaN,
    )
end

function run_ray!(work::TimestampWork, angle_deg::Real, level::AbstractString,
                  parent_start, parent_end, triggers, network, profile,
                  config::ProbeConfig)
    scales = radial_scales(work)
    scales === nothing && return unresolved_ray(
        work, angle_deg, level, parent_start, parent_end, triggers,
    )
    vector = ray_vector(angle_deg, scales)
    center = work.center
    physical_width = hypot(vector.vx, vector.vy)
    function evaluate_radius(radius, phase)
        p13 = center.p13_abs_kw + Float64(radius) * vector.vx
        p30 = center.p30_abs_kw + Float64(radius) * vector.vy
        return evaluate_physical!(
            work.evaluation_state, network, profile, work.profile_index,
            p13, p30, config;
            search_kind="RAY", search_id=@sprintf("%.6f", angle_deg), phase=phase,
            coordinate=Float64(radius), radius=Float64(radius),
        )
    end
    sweep = PointResult[]
    step_count = round(Int, config.radial_guard / config.radial_step)
    for step in 0:step_count
        push!(sweep, evaluate_radius(step * config.radial_step, "coarse_sweep"))
    end
    reentry = reentry_detected(sweep)
    unresolved_count = count(point_unresolved, sweep)
    bracket = first_adjacent_bracket(sweep)
    status = "RAY_UNRESOLVED"
    safe = nothing
    violating = nothing
    refinement_steps = 0
    bracket_width_kw = NaN
    if reentry
        status = "RAY_REENTRY_DETECTED"
    elseif bracket !== nothing
        candidate_safe, candidate_violating = bracket
        refined = refine_boundary!(
            (coordinate, phase) -> evaluate_radius(coordinate, phase),
            candidate_safe, candidate_violating, physical_width, config,
        )
        safe = refined.safe
        violating = refined.violating
        refinement_steps = refined.steps
        bracket_width_kw = refined.width_kw
        status = refined.status == "CERTIFIED" ? "RAY_CERTIFIED_BOUNDARY" : "RAY_UNRESOLVED"
    elseif all(point_safe, sweep)
        status = "RAY_UNBOUNDED_WITHIN_GUARD"
    end
    mechanism = violating === nothing ?
                (status == "RAY_UNBOUNDED_WITHIN_GUARD" ? "RAY_UNBOUNDED_WITHIN_GUARD" : "UNRESOLVED") :
                binding_mechanism(violating, config)
    return (
        selection_index=parse(Int, work.selection.selection_index),
        timestamp=work.selection.timestamp,
        level=String(level), angle_deg=Float64(angle_deg),
        parent_start_angle_deg=parent_start, parent_end_angle_deg=parent_end,
        adaptive_triggers=String(triggers), status=status,
        no_reentry_statement=reentry ? "RAY_REENTRY_DETECTED" :
                             "NO_RE_ENTRY_DETECTED_AT_SWEEP_RESOLUTION_DELTA",
        official_boundary_r=status == "RAY_CERTIFIED_BOUNDARY" ? safe.coordinate : NaN,
        safe=safe, violating=violating, binding_mechanism=mechanism,
        binding_bus=violating === nothing ? nothing : binding_bus(violating, mechanism),
        sweep_point_count=length(sweep), refinement_steps=refinement_steps,
        unresolved_point_count=unresolved_count, bracket_width_kw=bracket_width_kw,
    )
end

function adaptive_trigger(left, right)
    reasons = String[]
    left.binding_mechanism != right.binding_mechanism &&
        push!(reasons, "BOUNDARY_MECHANISM_CHANGE")
    left.binding_bus != right.binding_bus && push!(reasons, "BINDING_BUS_CHANGE")
    if isfinite(left.official_boundary_r) && isfinite(right.official_boundary_r)
        denominator = max(abs(left.official_boundary_r), abs(right.official_boundary_r), eps())
        abs(left.official_boundary_r - right.official_boundary_r) / denominator > 0.10 &&
            push!(reasons, "NORMALIZED_RADIUS_DIFFERENCE_GT_10_PERCENT")
    end
    contaminated_statuses = Set([
        "RAY_UNRESOLVED", "RAY_REENTRY_DETECTED", "RAY_UNBOUNDED_WITHIN_GUARD",
    ])
    (left.status in contaminated_statuses || right.status in contaminated_statuses) &&
        push!(reasons, "UNRESOLVED_NONCONVERGED_REENTRY_OR_GUARD_LIMITED_ENDPOINT")
    return reasons
end

function build_adaptive_plan(base_rays)
    length(base_rays) == 36 || throw(ArgumentError("adaptive plan requires 36 base rays"))
    plan = NamedTuple[]
    for index in 1:36
        next_index = mod1(index + 1, 36)
        left = base_rays[index]
        right = base_rays[next_index]
        reasons = adaptive_trigger(left, right)
        isempty(reasons) && continue
        midpoint = mod(left.angle_deg + 5.0, 360.0)
        push!(plan, (
            angle_deg=midpoint,
            parent_start_angle_deg=left.angle_deg,
            parent_end_angle_deg=right.angle_deg,
            triggers=join(reasons, ';'),
        ))
    end
    return plan
end

function checkpoint_provenance(root, prereg, commit)
    return (
        schema_version=1,
        git_commit=commit,
        config_sha256=normalized_sha256(prereg.config_path),
        selected_timestamp_sha256=normalized_sha256(prereg.selected_path),
        s0_evidence_sha256=normalized_sha256(prereg.s0_path),
        implementation_sha256=normalized_sha256(joinpath(root, "src", "benchmark", "dso_vpp_production_probe.jl")),
    )
end

function save_serialized_atomic(path::AbstractString, value)
    mkpath(dirname(path))
    temporary = path * ".tmp"
    open(temporary, "w") do io
        serialize(io, value)
        flush(io)
    end
    mv(temporary, path; force=true)
    return path
end

function load_serialized(path::AbstractString)
    return open(deserialize, path)
end

function save_current_checkpoint(checkpoint_dir, provenance, work)
    return save_serialized_atomic(
        joinpath(checkpoint_dir, "current_timestamp.bin"),
        (provenance=provenance, work=work),
    )
end

function assert_checkpoint_provenance(observed, expected)
    observed == expected || throw(ArgumentError("checkpoint provenance/configuration mismatch"))
end

function timestamp_segment(work::TimestampWork)
    actual_evaluations = length(work.evaluation_state.attempt_rows)
    logical_evaluations = work.evaluation_state.next_logical_evaluation_id - 1
    retries = count(row -> row.attempt_index == 2, work.evaluation_state.attempt_rows)
    nonconverged = count(
        row -> row.solver_status in ("NONCONVERGED_FIRST_ATTEMPT", "NONCONVERGED_AFTER_RETRY"),
        work.evaluation_state.attempt_rows,
    )
    return (
        selection=work.selection,
        profile_index=work.profile_index,
        axes=work.axes,
        center=work.center,
        base_rays=work.base_rays,
        adaptive_plan=work.adaptive_plan,
        adaptive_rays=work.adaptive_rays,
        attempt_rows=work.evaluation_state.attempt_rows,
        runtime_seconds=time() - work.started_unix,
        logical_evaluations=logical_evaluations,
        actual_evaluations=actual_evaluations,
        retries=retries,
        nonconverged_attempts=nonconverged,
        fatal_status=work.fatal_status,
    )
end

function complete_timestamp_checkpoint(checkpoint_dir, provenance, work)
    segment = timestamp_segment(work)
    index = parse(Int, work.selection.selection_index)
    path = joinpath(checkpoint_dir, @sprintf("timestamp_%02d.bin", index))
    save_serialized_atomic(path, (provenance=provenance, segment=segment))
    current = joinpath(checkpoint_dir, "current_timestamp.bin")
    isfile(current) && rm(current; force=true)
    return path
end

function load_completed_segments(checkpoint_dir, provenance)
    segments = NamedTuple[]
    for index in 1:32
        path = joinpath(checkpoint_dir, @sprintf("timestamp_%02d.bin", index))
        isfile(path) || continue
        stored = load_serialized(path)
        assert_checkpoint_provenance(stored.provenance, provenance)
        push!(segments, stored.segment)
    end
    return segments
end

function flatten_axis_row(axis)
    safe = axis.safe
    violating = axis.violating
    return (
        selection_index=axis.selection_index, timestamp=axis.timestamp,
        axis=axis.axis, axis_bus=axis.axis_bus, signed_direction=axis.signed_direction,
        status=axis.status, transition_scale_kw=axis.transition_scale_kw,
        coarse_delta_kw=axis.coarse_delta_kw, coarse_extent_kw=axis.coarse_extent_kw,
        no_reentry_statement=axis.no_reentry_statement,
        official_boundary_p_pcc_kw=axis.official_boundary_p_pcc_kw,
        binding_mechanism=axis.binding_mechanism, binding_bus=axis.binding_bus,
        safe_coordinate=safe === nothing ? NaN : safe.coordinate,
        safe_p13_abs_kw=safe === nothing ? NaN : safe.p13_abs_kw,
        safe_p30_abs_kw=safe === nothing ? NaN : safe.p30_abs_kw,
        safe_vmin_pu=safe === nothing ? NaN : safe.vmin_pu,
        safe_vmin_bus=safe === nothing ? nothing : safe.vmin_bus,
        safe_vmax_pu=safe === nothing ? NaN : safe.vmax_pu,
        safe_vmax_bus=safe === nothing ? nothing : safe.vmax_bus,
        safe_solver_status=safe === nothing ? "" : safe.solver_status,
        violating_coordinate=violating === nothing ? NaN : violating.coordinate,
        violating_p13_abs_kw=violating === nothing ? NaN : violating.p13_abs_kw,
        violating_p30_abs_kw=violating === nothing ? NaN : violating.p30_abs_kw,
        violating_vmin_pu=violating === nothing ? NaN : violating.vmin_pu,
        violating_vmin_bus=violating === nothing ? nothing : violating.vmin_bus,
        violating_vmax_pu=violating === nothing ? NaN : violating.vmax_pu,
        violating_vmax_bus=violating === nothing ? nothing : violating.vmax_bus,
        violating_solver_status=violating === nothing ? "" : violating.solver_status,
        doubling_point_count=axis.doubling_point_count,
        sweep_point_count=axis.sweep_point_count,
        refinement_steps=axis.refinement_steps,
        unresolved_point_count=axis.unresolved_point_count,
        bracket_width_kw=axis.bracket_width_kw,
    )
end

function flatten_ray_row(ray)
    safe = ray.safe
    violating = ray.violating
    return (
        selection_index=ray.selection_index, timestamp=ray.timestamp,
        level=ray.level, angle_deg=ray.angle_deg,
        parent_start_angle_deg=ray.parent_start_angle_deg,
        parent_end_angle_deg=ray.parent_end_angle_deg,
        adaptive_triggers=ray.adaptive_triggers, status=ray.status,
        no_reentry_statement=ray.no_reentry_statement,
        official_boundary_r=ray.official_boundary_r,
        binding_mechanism=ray.binding_mechanism, binding_bus=ray.binding_bus,
        safe_r=safe === nothing ? NaN : safe.coordinate,
        safe_p13_abs_kw=safe === nothing ? NaN : safe.p13_abs_kw,
        safe_p30_abs_kw=safe === nothing ? NaN : safe.p30_abs_kw,
        safe_vmin_pu=safe === nothing ? NaN : safe.vmin_pu,
        safe_vmin_bus=safe === nothing ? nothing : safe.vmin_bus,
        safe_vmax_pu=safe === nothing ? NaN : safe.vmax_pu,
        safe_vmax_bus=safe === nothing ? nothing : safe.vmax_bus,
        safe_solver_status=safe === nothing ? "" : safe.solver_status,
        violating_r=violating === nothing ? NaN : violating.coordinate,
        violating_p13_abs_kw=violating === nothing ? NaN : violating.p13_abs_kw,
        violating_p30_abs_kw=violating === nothing ? NaN : violating.p30_abs_kw,
        violating_vmin_pu=violating === nothing ? NaN : violating.vmin_pu,
        violating_vmin_bus=violating === nothing ? nothing : violating.vmin_bus,
        violating_vmax_pu=violating === nothing ? NaN : violating.vmax_pu,
        violating_vmax_bus=violating === nothing ? nothing : violating.vmax_bus,
        violating_solver_status=violating === nothing ? "" : violating.solver_status,
        sweep_point_count=ray.sweep_point_count,
        refinement_steps=ray.refinement_steps,
        unresolved_point_count=ray.unresolved_point_count,
        bracket_width_kw=ray.bracket_width_kw,
    )
end

function endpoint_rows(segments)
    rows = NamedTuple[]
    for segment in segments
        for axis in segment.axes
            axis.status == "AXIS_CERTIFIED_BOUNDARY" || continue
            for (side, point) in (("SAFE", axis.safe), ("VIOLATING", axis.violating))
                push!(rows, (
                    selection_index=axis.selection_index, timestamp=axis.timestamp,
                    search_kind="AXIS", search_id=axis.axis, level="AXIS",
                    endpoint_side=side, coordinate=point.coordinate, radius=NaN,
                    p13_abs_kw=point.p13_abs_kw, p30_abs_kw=point.p30_abs_kw,
                    vmin_pu=point.vmin_pu, vmin_bus=point.vmin_bus,
                    vmax_pu=point.vmax_pu, vmax_bus=point.vmax_bus,
                    solver_status=point.solver_status,
                    binding_mechanism=axis.binding_mechanism,
                    binding_bus=axis.binding_bus,
                    official_boundary=(side == "SAFE"),
                ))
            end
        end
        for ray in vcat(segment.base_rays, segment.adaptive_rays)
            ray.status == "RAY_CERTIFIED_BOUNDARY" || continue
            for (side, point) in (("SAFE", ray.safe), ("VIOLATING", ray.violating))
                push!(rows, (
                    selection_index=ray.selection_index, timestamp=ray.timestamp,
                    search_kind="RAY", search_id=@sprintf("%.6f", ray.angle_deg),
                    level=ray.level, endpoint_side=side,
                    coordinate=point.coordinate, radius=point.coordinate,
                    p13_abs_kw=point.p13_abs_kw, p30_abs_kw=point.p30_abs_kw,
                    vmin_pu=point.vmin_pu, vmin_bus=point.vmin_bus,
                    vmax_pu=point.vmax_pu, vmax_bus=point.vmax_bus,
                    solver_status=point.solver_status,
                    binding_mechanism=ray.binding_mechanism,
                    binding_bus=ray.binding_bus,
                    official_boundary=(side == "SAFE"),
                ))
            end
        end
    end
    return rows
end

function quantile_sorted(sorted_values, probability)
    isempty(sorted_values) && return NaN
    position = 1 + (length(sorted_values) - 1) * Float64(probability)
    lower = floor(Int, position)
    upper = ceil(Int, position)
    lower == upper && return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction
end

function numeric_distribution_row(metric, values)
    finite_values = sort!(Float64[value for value in values if isfinite(Float64(value))])
    return (
        distribution_type="NUMERIC", metric=String(metric), category="",
        count=length(finite_values), minimum=isempty(finite_values) ? NaN : first(finite_values),
        q05=quantile_sorted(finite_values, 0.05), q25=quantile_sorted(finite_values, 0.25),
        median=quantile_sorted(finite_values, 0.50), q75=quantile_sorted(finite_values, 0.75),
        q95=quantile_sorted(finite_values, 0.95), maximum=isempty(finite_values) ? NaN : last(finite_values),
        mean=isempty(finite_values) ? NaN : sum(finite_values) / length(finite_values),
    )
end

function categorical_distribution_rows(metric, values)
    counts = Dict{String,Int}()
    for value in values
        key = string(value)
        counts[key] = get(counts, key, 0) + 1
    end
    return [(
        distribution_type="CATEGORY", metric=String(metric), category=key,
        count=counts[key], minimum=NaN, q05=NaN, q25=NaN, median=NaN,
        q75=NaN, q95=NaN, maximum=NaN, mean=NaN,
    ) for key in sort!(collect(keys(counts)))]
end

function empirical_tail_rank(values, target)
    sorted_values = sort!(Float64.(values))
    index = findfirst(==(Float64(target)), sorted_values)
    index === nothing && return 0.5
    percentile = length(sorted_values) == 1 ? 0.5 : (index - 1) / (length(sorted_values) - 1)
    return min(percentile, 1 - percentile)
end

function distribution_outputs(segments)
    axes = [axis for segment in segments for axis in segment.axes]
    centers = [segment.center for segment in segments]
    base_rays = [ray for segment in segments for ray in segment.base_rays]
    adaptive_rays = [ray for segment in segments for ray in segment.adaptive_rays]
    rows = NamedTuple[]
    for name in ("P13_POSITIVE", "P13_NEGATIVE", "P30_POSITIVE", "P30_NEGATIVE")
        values = [axis.official_boundary_p_pcc_kw for axis in axes if axis.axis == name]
        push!(rows, numeric_distribution_row("AXIS_$(name)_P_PCC_KW", values))
    end
    p13_widths = Float64[]
    p30_widths = Float64[]
    total_widths = Float64[]
    median_base_radius = Float64[]
    for segment in segments
        valid = all(axis -> axis.status == "AXIS_CERTIFIED_BOUNDARY", segment.axes)
        if valid
            p13_width = only(axis.official_boundary_p_pcc_kw for axis in segment.axes if axis.axis == "P13_POSITIVE") -
                        only(axis.official_boundary_p_pcc_kw for axis in segment.axes if axis.axis == "P13_NEGATIVE")
            p30_width = only(axis.official_boundary_p_pcc_kw for axis in segment.axes if axis.axis == "P30_POSITIVE") -
                        only(axis.official_boundary_p_pcc_kw for axis in segment.axes if axis.axis == "P30_NEGATIVE")
            push!(p13_widths, p13_width)
            push!(p30_widths, p30_width)
            push!(total_widths, p13_width + p30_width)
        else
            push!(p13_widths, NaN); push!(p30_widths, NaN); push!(total_widths, NaN)
        end
        radii = sort!([ray.official_boundary_r for ray in segment.base_rays if isfinite(ray.official_boundary_r)])
        push!(median_base_radius, quantile_sorted(radii, 0.5))
    end
    append!(rows, [
        numeric_distribution_row("P13_AXIS_WIDTH_KW", p13_widths),
        numeric_distribution_row("P30_AXIS_WIDTH_KW", p30_widths),
        numeric_distribution_row("TOTAL_AXIS_WIDTH_KW", total_widths),
        numeric_distribution_row("CENTER_P13_ABS_KW", [center.p13_abs_kw for center in centers]),
        numeric_distribution_row("CENTER_P30_ABS_KW", [center.p30_abs_kw for center in centers]),
        numeric_distribution_row("BASE_RAY_BOUNDARY_R", [ray.official_boundary_r for ray in base_rays]),
        numeric_distribution_row("ADAPTIVE_RAY_BOUNDARY_R", [ray.official_boundary_r for ray in adaptive_rays]),
        numeric_distribution_row("RETRIES_PER_TIMESTAMP", [segment.retries for segment in segments]),
        numeric_distribution_row("UNRESOLVED_PER_TIMESTAMP", [
            count(axis -> axis.status == "AXIS_UNRESOLVED", segment.axes) +
            count(ray -> ray.status == "RAY_UNRESOLVED", vcat(segment.base_rays, segment.adaptive_rays))
            for segment in segments
        ]),
        numeric_distribution_row("GUARD_LIMITED_PER_TIMESTAMP", [
            count(axis -> axis.status == "AXIS_UNBOUNDED_WITHIN_GUARD", segment.axes) +
            count(ray -> ray.status == "RAY_UNBOUNDED_WITHIN_GUARD", vcat(segment.base_rays, segment.adaptive_rays))
            for segment in segments
        ]),
        numeric_distribution_row("REENTRY_PER_TIMESTAMP", [
            count(axis -> axis.status == "AXIS_REENTRY_DETECTED", segment.axes) +
            count(ray -> ray.status == "RAY_REENTRY_DETECTED", vcat(segment.base_rays, segment.adaptive_rays))
            for segment in segments
        ]),
        numeric_distribution_row("RUNTIME_SECONDS_PER_TIMESTAMP", [segment.runtime_seconds for segment in segments]),
        numeric_distribution_row("ACTUAL_EVALUATIONS_PER_TIMESTAMP", [segment.actual_evaluations for segment in segments]),
    ])
    append!(rows, categorical_distribution_rows("CENTER_TIER", [center.center_tier for center in centers]))
    append!(rows, categorical_distribution_rows("AXIS_STATUS", [axis.status for axis in axes]))
    append!(rows, categorical_distribution_rows("BINDING_MECHANISM", [
        result.binding_mechanism for result in vcat(axes, base_rays, adaptive_rays)
    ]))
    append!(rows, categorical_distribution_rows("BINDING_BUS", [
        result.binding_bus for result in vcat(axes, base_rays, adaptive_rays)
        if result.binding_bus !== nothing
    ]))

    anchor_index = findfirst(segment -> segment.selection.timestamp == "2012-10-15 13:00:00", segments)
    anchor_index === nothing && return rows, "UNRESOLVED", "anchor missing"
    width_finite = [value for value in total_widths if isfinite(value)]
    radius_finite = [value for value in median_base_radius if isfinite(value)]
    anchor_width = total_widths[anchor_index]
    anchor_radius = median_base_radius[anchor_index]
    tails = Float64[]
    isfinite(anchor_width) && push!(tails, empirical_tail_rank(width_finite, anchor_width))
    isfinite(anchor_radius) && push!(tails, empirical_tail_rank(radius_finite, anchor_radius))
    classification = if isempty(tails)
        "UNRESOLVED"
    elseif minimum(tails) <= 0.05
        "EXTREME"
    elseif minimum(tails) <= 0.15
        "NEAR_EXTREME"
    else
        plateau_width = isfinite(anchor_width) &&
            count(value -> abs(value - anchor_width) <= 0.01 * max(abs(anchor_width), 1.0), width_finite) >= 8
        plateau_radius = isfinite(anchor_radius) &&
            count(value -> abs(value - anchor_radius) <= 0.01 * max(abs(anchor_radius), 1.0), radius_finite) >= 8
        plateau_width && plateau_radius ? "PLATEAU_REGION" : "TYPICAL"
    end
    criterion = "EXTREME if either total-axis-width or median-base-radius empirical tail rank <=5%; " *
                "NEAR_EXTREME if <=15%; otherwise PLATEAU_REGION if at least 8/32 timestamps lie " *
                "within 1% of the anchor on both metrics; otherwise TYPICAL."
    return rows, classification, criterion
end

function validate_segments(segments, provenance)
    checks = NamedTuple[]
    add(name, passed, detail) = push!(checks, (check=String(name), passed=Bool(passed), detail=String(detail)))
    add("exactly_32_timestamps", length(segments) == 32, "observed=$(length(segments))")
    timestamps = [segment.selection.timestamp for segment in segments]
    add("mandatory_anchor_exists", count(==("2012-10-15 13:00:00"), timestamps) == 1,
        "anchor_count=$(count(==("2012-10-15 13:00:00"), timestamps))")
    add("no_duplicate_timestamps", length(unique(timestamps)) == length(timestamps),
        "unique=$(length(unique(timestamps)))")
    add("four_signed_axes_each", all(segment -> length(segment.axes) == 4, segments), "required=4")
    tier1_valid = all(segments) do segment
        segment.center.center_tier != "CENTER_TIER_1_AXIS_MIDPOINT" ||
            all(axis -> axis.status == "AXIS_CERTIFIED_BOUNDARY", segment.axes)
    end
    add("tier1_uses_four_finite_valid_axes", tier1_valid, "finite-valid=AXIS_CERTIFIED_BOUNDARY")
    add("invalid_axes_excluded_from_tier1", tier1_valid, "guard/unresolved/reentry excluded")
    results = [result for segment in segments for result in vcat(segment.axes, segment.base_rays, segment.adaptive_rays)]
    binding_valid = all(results) do result
        result.binding_mechanism == "BINDING_VMIN" ?
            (result.violating !== nothing && point_violating(result.violating) &&
             result.violating.vmin_pu < 0.90 && result.binding_bus !== nothing) :
        result.binding_mechanism == "BINDING_VMAX" ?
            (result.violating !== nothing && point_violating(result.violating) &&
             result.violating.vmax_pu > 1.05 && result.binding_bus !== nothing) : true
    end
    add("binding_invariants", binding_valid, "actual converged violation and bus required")
    official_safe = all(results) do result
        certified = result.status in ("AXIS_CERTIFIED_BOUNDARY", "RAY_CERTIFIED_BOUNDARY")
        !certified || (result.safe !== nothing && point_safe(result.safe))
    end
    add("official_boundaries_are_safe_endpoints", official_safe, "last converged feasible")
    endpoints_valid = all(results) do result
        certified = result.status in ("AXIS_CERTIFIED_BOUNDARY", "RAY_CERTIFIED_BOUNDARY")
        !certified || (point_safe(result.safe) && point_violating(result.violating))
    end
    add("no_nonconverged_bisection_endpoint", endpoints_valid, "safe/violating certified")
    adaptive_valid = all(segments) do segment
        all(ray -> !isempty(ray.adaptive_triggers), segment.adaptive_rays) &&
        all(plan -> !isempty(plan.triggers), segment.adaptive_plan)
    end
    add("adaptive_angles_justified", adaptive_valid, "preregistered trigger list nonempty")
    direction_cap = all(segment -> length(segment.base_rays) == 36 &&
                                  length(segment.adaptive_rays) <= 36 &&
                                  length(segment.base_rays) + length(segment.adaptive_rays) <= 72,
                        segments)
    add("direction_count_cap", direction_cap, "36 base and <=36 adaptive")
    angles_valid = all(segments) do segment
        [ray.angle_deg for ray in segment.base_rays] == BASE_ANGLES_DEG &&
            all(ray -> mod(ray.angle_deg, 10.0) == 5.0, segment.adaptive_rays)
    end
    add("no_unpreregistered_angles", angles_valid, "base grid plus triggered midpoints only")
    add("physical_coordinate_cross_time_semantics", true,
        "summaries use P13/P30 absolute axes; normalized directions are not averaged cross-time")
    add("checkpoint_provenance_consistent", true,
        "all loaded segments matched $(provenance.config_sha256)")
    return checks, all(check.passed for check in checks)
end

function write_outputs(root, output_dir, checkpoint_dir, prereg, provenance, segments,
                       started_at, finished_at, resume_mode)
    sort!(segments; by=segment -> parse(Int, segment.selection.selection_index))
    axes = [flatten_axis_row(axis) for segment in segments for axis in segment.axes]
    centers = [segment.center for segment in segments]
    base_rays = [flatten_ray_row(ray) for segment in segments for ray in segment.base_rays]
    adaptive_rays = [flatten_ray_row(ray) for segment in segments for ray in segment.adaptive_rays]
    attempts = [row for segment in segments for row in segment.attempt_rows]
    endpoints = endpoint_rows(segments)
    distribution_rows, anchor_classification, anchor_criterion = distribution_outputs(segments)
    validation_checks, validation_passed = validate_segments(segments, provenance)

    axis_fields = propertynames(first(axes))
    center_fields = propertynames(first(centers))
    ray_fields = propertynames(first(base_rays))
    attempt_fields = propertynames(first(attempts))
    endpoint_fields = propertynames(first(endpoints))
    distribution_fields = propertynames(first(distribution_rows))
    validation_fields = propertynames(first(validation_checks))
    write_csv(joinpath(output_dir, "signed_axis_results.csv"), axis_fields, axes)
    write_csv(joinpath(output_dir, "center_results.csv"), center_fields, centers)
    write_csv(joinpath(output_dir, "base_ray_results.csv"), ray_fields, base_rays)
    write_csv(joinpath(output_dir, "adaptive_ray_results.csv"), ray_fields, adaptive_rays)
    write_csv(joinpath(output_dir, "evaluation_attempts.csv"), attempt_fields, attempts)
    write_csv(joinpath(output_dir, "boundary_endpoints.csv"), endpoint_fields, endpoints)
    write_csv(joinpath(output_dir, "distribution_summary.csv"), distribution_fields, distribution_rows)
    write_csv(joinpath(output_dir, "final_validation_checks.csv"), validation_fields, validation_checks)

    reentry_rows = [(
        selection_index=result.selection_index, timestamp=result.timestamp,
        search_kind=hasproperty(result, :axis) ? "AXIS" : "RAY",
        search_id=hasproperty(result, :axis) ? result.axis : @sprintf("%.6f", result.angle_deg),
        status=result.status, no_reentry_statement=result.no_reentry_statement,
    ) for result in [result for segment in segments for result in vcat(segment.axes, segment.base_rays, segment.adaptive_rays)]]
    write_csv(joinpath(output_dir, "reentry_audit.csv"), propertynames(first(reentry_rows)), reentry_rows)
    exception_rows = [(
        selection_index=result.selection_index, timestamp=result.timestamp,
        search_kind=hasproperty(result, :axis) ? "AXIS" : "RAY",
        search_id=hasproperty(result, :axis) ? result.axis : @sprintf("%.6f", result.angle_deg),
        status=result.status,
    ) for result in [result for segment in segments for result in vcat(segment.axes, segment.base_rays, segment.adaptive_rays)]
       if occursin("UNRESOLVED", result.status) || occursin("UNBOUNDED_WITHIN_GUARD", result.status)]
    if isempty(exception_rows)
        exception_rows = [(selection_index=0, timestamp="", search_kind="", search_id="", status="NONE")]
    end
    write_csv(joinpath(output_dir, "unresolved_guard_cases.csv"), propertynames(first(exception_rows)), exception_rows)

    timestamp_rows = [(
        selection_index=parse(Int, segment.selection.selection_index),
        timestamp=segment.selection.timestamp,
        runtime_seconds=segment.runtime_seconds,
        logical_evaluations=segment.logical_evaluations,
        actual_evaluations=segment.actual_evaluations,
        retry_count=segment.retries,
        nonconverged_attempt_count=segment.nonconverged_attempts,
        axis_unresolved_count=count(axis -> axis.status == "AXIS_UNRESOLVED", segment.axes),
        axis_guard_limited_count=count(axis -> axis.status == "AXIS_UNBOUNDED_WITHIN_GUARD", segment.axes),
        axis_reentry_count=count(axis -> axis.status == "AXIS_REENTRY_DETECTED", segment.axes),
        ray_unresolved_count=count(ray -> ray.status == "RAY_UNRESOLVED", vcat(segment.base_rays, segment.adaptive_rays)),
        ray_guard_limited_count=count(ray -> ray.status == "RAY_UNBOUNDED_WITHIN_GUARD", vcat(segment.base_rays, segment.adaptive_rays)),
        ray_reentry_count=count(ray -> ray.status == "RAY_REENTRY_DETECTED", vcat(segment.base_rays, segment.adaptive_rays)),
        base_direction_count=length(segment.base_rays),
        adaptive_direction_count=length(segment.adaptive_rays),
        center_tier=segment.center.center_tier,
    ) for segment in segments]
    write_csv(joinpath(output_dir, "timestamp_runtime_evaluation_summary.csv"),
              propertynames(first(timestamp_rows)), timestamp_rows)

    checkpoint_rows = NamedTuple[]
    for index in 1:32
        path = joinpath(checkpoint_dir, @sprintf("timestamp_%02d.bin", index))
        isfile(path) || continue
        push!(checkpoint_rows, (
            selection_index=index,
            checkpoint_file=relpath(path, root),
            checkpoint_sha256=file_sha256(path),
            git_commit=provenance.git_commit,
            config_sha256=provenance.config_sha256,
            selected_timestamp_sha256=provenance.selected_timestamp_sha256,
            s0_evidence_sha256=provenance.s0_evidence_sha256,
            implementation_sha256=provenance.implementation_sha256,
        ))
    end
    write_csv(joinpath(output_dir, "checkpoint_resume_manifest.csv"),
              propertynames(first(checkpoint_rows)), checkpoint_rows)

    total_actual = sum(segment.actual_evaluations for segment in segments)
    total_logical = sum(segment.logical_evaluations for segment in segments)
    total_retries = sum(segment.retries for segment in segments)
    total_nonconverged = sum(segment.nonconverged_attempts for segment in segments)
    wall_seconds = finished_at - started_at
    axis_status_counts = Dict{String,Int}()
    center_counts = Dict{String,Int}()
    binding_counts = Dict{String,Int}()
    bus_counts = Dict{String,Int}()
    for axis in [axis for segment in segments for axis in segment.axes]
        axis_status_counts[axis.status] = get(axis_status_counts, axis.status, 0) + 1
    end
    for center in centers
        center_counts[center.center_tier] = get(center_counts, center.center_tier, 0) + 1
    end
    for result in [result for segment in segments for result in vcat(segment.axes, segment.base_rays, segment.adaptive_rays)]
        binding_counts[result.binding_mechanism] = get(binding_counts, result.binding_mechanism, 0) + 1
        if result.binding_bus !== nothing
            key = string(result.binding_bus)
            bus_counts[key] = get(bus_counts, key, 0) + 1
        end
    end
    unresolved_count = count(result -> occursin("UNRESOLVED", result.status),
        [result for segment in segments for result in vcat(segment.axes, segment.base_rays, segment.adaptive_rays)])
    guard_count = count(result -> occursin("UNBOUNDED_WITHIN_GUARD", result.status),
        [result for segment in segments for result in vcat(segment.axes, segment.base_rays, segment.adaptive_rays)])
    axis_reentry_count = count(axis -> axis.status == "AXIS_REENTRY_DETECTED", [axis for segment in segments for axis in segment.axes])
    ray_reentry_count = count(ray -> ray.status == "RAY_REENTRY_DETECTED", [ray for segment in segments for ray in vcat(segment.base_rays, segment.adaptive_rays)])
    classification = if !validation_passed
        "PRODUCTION_PROBE_EXECUTION_FAILED"
    elseif ray_reentry_count > 0
        "PRODUCTION_PROBE_BLOCKED_BY_SCIENTIFIC_AMENDMENT"
    elseif unresolved_count > 0 || guard_count > 0
        "PRODUCTION_PROBE_COMPLETE_WITH_PREREGISTERED_UNRESOLVED_CASES"
    else
        "PRODUCTION_PROBE_COMPLETE_VALIDATED"
    end

    manifest = Dict(
        "schema_version" => 1,
        "classification" => classification,
        "implementation_id" => IMPLEMENTATION_ID,
        "git_commit" => provenance.git_commit,
        "git_branch" => git_output(root, "branch", "--show-current"),
        "config_path" => relpath(prereg.config_path, root),
        "config_sha256" => provenance.config_sha256,
        "preregistration_manifest_sha256" => prereg.manifest_sha256,
        "selected_timestamp_path" => relpath(prereg.selected_path, root),
        "selected_timestamp_sha256" => provenance.selected_timestamp_sha256,
        "s0_evidence_path" => relpath(prereg.s0_path, root),
        "s0_evidence_sha256" => provenance.s0_evidence_sha256,
        "implementation_sha256" => provenance.implementation_sha256,
        "coordinate_space" => "ABSOLUTE_PHYSICAL_P_PCC_KW",
        "reactive_policy" => "UNITY_POWER_FACTOR_INTERFACE_POLICY",
        "q_pcc_kvar" => 0.0,
        "started_utc" => Dates.format(unix2datetime(started_at), dateformat"yyyy-mm-ddTHH:MM:SS") * "Z",
        "finished_utc" => Dates.format(unix2datetime(finished_at), dateformat"yyyy-mm-ddTHH:MM:SS") * "Z",
        "resume_mode" => resume_mode,
        "process_count" => 1,
        "julia_thread_count" => Threads.nthreads(),
        "timestamp_count" => length(segments),
        "logical_evaluation_count" => total_logical,
        "actual_ac_evaluation_count" => total_actual,
        "retry_count" => total_retries,
        "nonconverged_attempt_count" => total_nonconverged,
        "wall_seconds" => wall_seconds,
        "peak_rss_bytes" => Sys.maxrss(),
        "validation_passed" => validation_passed,
        "anchor_distribution_classification" => anchor_classification,
        "anchor_distribution_criterion" => anchor_criterion,
    )
    open(joinpath(output_dir, "run_manifest.toml"), "w") do io
        TOML.print(io, manifest; sorted=true)
    end

    report_path = joinpath(output_dir, "production_report.md")
    axis_status_text = join(
        ["$key=$(axis_status_counts[key])" for key in sort!(collect(keys(axis_status_counts)))],
        ", ",
    )
    center_status_text = join(
        ["$key=$(center_counts[key])" for key in sort!(collect(keys(center_counts)))],
        ", ",
    )
    binding_status_text = join(
        ["$key=$(binding_counts[key])" for key in sort!(collect(keys(binding_counts)))],
        ", ",
    )
    binding_bus_text = join(
        ["$key=$(bus_counts[key])" for key in sort!(collect(keys(bus_counts)))],
        ", ",
    )
    validation_text = validation_passed ? "PASS" : "FAIL"
    open(report_path, "w") do io
        println(io, "# DSO-VPP production AC boundary probe")
        println(io)
        println(io, "Primary classification: `$(classification)`")
        println(io)
        println(io, "- Coordinate system: absolute physical `P_PCC` kW; `Q_PCC = 0`.")
        println(io, "- Git commit: `$(provenance.git_commit)`.")
        println(io, "- Run mode: $(resume_mode); 1 Julia process, $(Threads.nthreads()) Julia thread(s).")
        println(io, @sprintf("- Wall time: %.3f s; actual AC evaluations: %d; retries: %d.", wall_seconds, total_actual, total_retries))
        println(io, "- Timestamps: $(length(segments))/32; base directions: $(length(base_rays)); adaptive directions: $(length(adaptive_rays)).")
        println(io, "- Axis status distribution: $axis_status_text.")
        println(io, "- Center-tier distribution: $center_status_text.")
        println(io, "- Binding distribution: $binding_status_text.")
        println(io, "- Binding buses: $binding_bus_text.")
        println(io, "- Unresolved: $unresolved_count; guard-limited: $guard_count; axis re-entry: $axis_reentry_count; ray re-entry: $ray_reentry_count.")
        println(io, "- Anchor `2012-10-15 13:00:00`: $(anchor_classification). Criterion: $(anchor_criterion)")
        println(io, "- Independent post-run validation: $validation_text.")
        println(io)
        println(io, "Historical command-space anchor values are retained only as provenance and were not used as absolute-axis intercepts.")
    end

    artifact_rows = NamedTuple[]
    for name in sort!(readdir(output_dir))
        path = joinpath(output_dir, name)
        isfile(path) || continue
        name == "artifact_manifest.csv" && continue
        push!(artifact_rows, (artifact=name, bytes=filesize(path), sha256=file_sha256(path)))
    end
    write_csv(joinpath(output_dir, "artifact_manifest.csv"), propertynames(first(artifact_rows)), artifact_rows)
    return (
        classification=classification,
        validation_passed=validation_passed,
        wall_seconds=wall_seconds,
        total_actual_evaluations=total_actual,
        total_logical_evaluations=total_logical,
        retries=total_retries,
        nonconverged_attempts=total_nonconverged,
        unresolved_count=unresolved_count,
        guard_count=guard_count,
        axis_reentry_count=axis_reentry_count,
        ray_reentry_count=ray_reentry_count,
        anchor_classification=anchor_classification,
    )
end

function run_timestamp!(work::TimestampWork, network, profile, s0_rows,
                        config::ProbeConfig, checkpoint_dir, provenance)
    while length(work.axes) < 4
        definition = signed_axis_definition(length(work.axes) + 1)
        push!(work.axes, run_axis!(work, definition, network, profile, config))
        save_current_checkpoint(checkpoint_dir, provenance, work)
    end
    if work.center === nothing
        work.center = run_center!(work, network, profile, s0_rows, config)
        save_current_checkpoint(checkpoint_dir, provenance, work)
    end
    while length(work.base_rays) < 36
        angle = BASE_ANGLES_DEG[length(work.base_rays) + 1]
        ray = run_ray!(work, angle, "BASE", NaN, NaN, "BASE_PREREGISTERED",
                       network, profile, config)
        push!(work.base_rays, ray)
        if ray.status == "RAY_REENTRY_DETECTED"
            work.fatal_status = "CENTERED_RADIAL_METHOD_REVIEW_REQUIRED"
            save_current_checkpoint(checkpoint_dir, provenance, work)
            return work
        end
        save_current_checkpoint(checkpoint_dir, provenance, work)
    end
    isempty(work.adaptive_plan) && (work.adaptive_plan = build_adaptive_plan(work.base_rays))
    while length(work.adaptive_rays) < length(work.adaptive_plan)
        plan = work.adaptive_plan[length(work.adaptive_rays) + 1]
        ray = run_ray!(work, plan.angle_deg, "ADAPTIVE", plan.parent_start_angle_deg,
                       plan.parent_end_angle_deg, plan.triggers, network, profile, config)
        push!(work.adaptive_rays, ray)
        if ray.status == "RAY_REENTRY_DETECTED"
            work.fatal_status = "CENTERED_RADIAL_METHOD_REVIEW_REQUIRED"
            save_current_checkpoint(checkpoint_dir, provenance, work)
            return work
        end
        save_current_checkpoint(checkpoint_dir, provenance, work)
    end
    return work
end

function production_paths(root::AbstractString)
    output = joinpath(root, "results", "dso_vpp_ac_map_pilot", "production_probe")
    return (output=output, checkpoints=joinpath(output, "checkpoints"))
end

function run_production_probe(root::AbstractString; execution_authorized::Bool=false)
    execution_authorized || throw(ArgumentError(
        "production execution requires explicit $EXECUTION_FLAG authorization",
    ))
    started_at = time()
    println("preflight_stage=VERIFY_PREREGISTRATION_MANIFEST")
    flush(stdout)
    prereg = verify_preregistration_manifest(root)
    println("preflight_stage=VALIDATE_LOCKED_CONFIG")
    flush(stdout)
    policy = TOML.parsefile(prereg.config_path)
    config = validate_locked_config(policy)
    selections = read_csv_rows(prereg.selected_path)
    s0_rows = read_csv_rows(prereg.s0_path)
    length(selections) == 32 || throw(ArgumentError("expected exactly 32 selected timestamps"))
    length(unique(row.timestamp for row in selections)) == 32 ||
        throw(ArgumentError("selected timestamps contain duplicates"))
    count(row -> row.timestamp == "2012-10-15 13:00:00", selections) == 1 ||
        throw(ArgumentError("mandatory anchor missing or duplicated"))

    commit = git_output(root, "rev-parse", "HEAD")
    provenance = checkpoint_provenance(root, prereg, commit)
    paths = production_paths(root)
    output_existed = isdir(paths.output)
    mkpath(paths.checkpoints)
    completed = load_completed_segments(paths.checkpoints, provenance)
    completed_indices = Set(parse(Int, segment.selection.selection_index) for segment in completed)
    resume_mode = isempty(completed) && !isfile(joinpath(paths.checkpoints, "current_timestamp.bin")) ?
                  "FRESH" : "RESUMED"

    network = Stage0.build_pilot_network()
    println("preflight_stage=LOAD_CANONICAL_PROFILE")
    flush(stdout)
    profile = Stage0.load_profile(root)
    profile_lookup = Dict(
        Dates.format(timestamp, dateformat"yyyy-mm-dd HH:MM:SS") => index
        for (index, timestamp) in pairs(profile.timestamps)
    )
    current_path = joinpath(paths.checkpoints, "current_timestamp.bin")
    println("preflight_stage=EXECUTE_TIMESTAMPS")
    flush(stdout)
    for selection in selections
        selection_index = parse(Int, selection.selection_index)
        selection_index in completed_indices && continue
        haskey(profile_lookup, selection.timestamp) ||
            throw(ArgumentError("timestamp absent from canonical profile: $(selection.timestamp)"))
        work = if isfile(current_path)
            stored = load_serialized(current_path)
            assert_checkpoint_provenance(stored.provenance, provenance)
            parse(Int, stored.work.selection.selection_index) == selection_index ||
                throw(ArgumentError("current checkpoint timestamp does not match next incomplete timestamp"))
            stored.work
        else
            TimestampWork(selection=selection, profile_index=profile_lookup[selection.timestamp])
        end
        work = run_timestamp!(work, network, profile, s0_rows, config, paths.checkpoints, provenance)
        if work.fatal_status == "CENTERED_RADIAL_METHOD_REVIEW_REQUIRED"
            complete_timestamp_checkpoint(paths.checkpoints, provenance, work)
            push!(completed, timestamp_segment(work))
            finished_at = time()
            result = write_outputs(root, paths.output, paths.checkpoints, prereg, provenance,
                                   completed, started_at, finished_at, resume_mode)
            return merge(result, (output_directory=paths.output, resume_mode=resume_mode,
                                  output_existed=output_existed))
        end
        complete_timestamp_checkpoint(paths.checkpoints, provenance, work)
        push!(completed, timestamp_segment(work))
        push!(completed_indices, selection_index)
        println("completed_timestamp=$(selection_index)/32 timestamp=$(selection.timestamp) " *
                "actual_evaluations=$(last(completed).actual_evaluations) " *
                @sprintf("runtime_seconds=%.3f", last(completed).runtime_seconds))
        flush(stdout)
    end
    finished_at = time()
    segments = load_completed_segments(paths.checkpoints, provenance)
    result = write_outputs(root, paths.output, paths.checkpoints, prereg, provenance,
                           segments, started_at, finished_at, resume_mode)
    return merge(result, (output_directory=paths.output, resume_mode=resume_mode,
                          output_existed=output_existed))
end

export ProbeConfig, PointResult, EvaluationState, TimestampWork,
       normalized_sha256, split_csv_line, read_csv_rows, git_output,
       attempt_class, nearest_accepted_neighbor,
       reentry_detected, first_adjacent_bracket, binding_mechanism,
       endpoint_voltage_close, adaptive_trigger, build_adaptive_plan,
       validate_locked_config, validate_segments, run_production_probe,
       EXECUTION_FLAG

end
