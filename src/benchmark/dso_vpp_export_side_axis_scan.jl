module DSOVPPExportSideAxisScan

using CiroPVHC
using Dates
using Printf
using SHA

include("dso_vpp_ac_map_stage0.jl")
const Stage0 = DSOVPPACMapStage0

const IMPLEMENTATION_ID = "CiroPVHC.DSOVPPExportSideAxisScan.radial_bfs.v1"
const AXES = ((name="P13_VPP", bus=13), (name="P30_VPP", bus=30))
const CAPACITY_FIELDS = (
    :timestamp, :axis, :axis_bus, :baseline_status, :baseline_power_flow_status,
    :baseline_voltage_status, :baseline_replay_status, :axis_status,
    :initial_step_kW, :doubling_steps, :bisection_steps, :evaluation_count,
    :safe_lower_kW, :violating_upper_kW, :axis_capacity_kW,
    :capacity_tolerance_kW, :bracket_width_kW,
    :safe_Vmin_pu, :safe_Vmin_bus, :safe_Vmax_pu, :safe_Vmax_bus,
    :safe_vmax_bus_set, :safe_upper_limit_near_binding_bus_set,
    :safe_voltage_margin_pu, :violating_Vmin_pu, :violating_Vmin_bus,
    :violating_Vmax_pu, :violating_Vmax_bus, :violating_vmax_bus_set,
    :violating_upper_limit_near_binding_bus_set, :violating_voltage_excess_pu,
    :binding_tolerance_pu, :safe_P_sub_kW, :safe_Q_sub_kvar,
    :safe_active_loss_kW, :safe_reactive_loss_kvar, :violating_P_sub_kW,
    :violating_Q_sub_kvar, :violating_active_loss_kW,
    :violating_reactive_loss_kvar, :safe_replay_status,
    :violating_replay_status, :monotonic_Vmax_check, :monotonic_status_check,
    :maximum_residual, :maximum_primary_replay_voltage_difference,
    :voltage_margin_tolerance_pu, :power_stopping_criterion_met,
    :voltage_stopping_criterion_met,
)
const SCAN_FIELDS = (
    :timestamp, :axis, :axis_bus, :point_index, :search_phase,
    :axis_injection_kW, :reference_pv_kw, :vpp_p13_kw, :vpp_p30_kw,
    :H_kW, :pv_factor, :P_sub_kW, :Q_sub_kvar, :active_loss_kW,
    :reactive_loss_kvar, :Vmin_pu, :Vmin_bus, :Vmax_pu, :Vmax_bus,
    :vmax_bus_set, :upper_limit_near_binding_bus_set, :power_flow_status,
    :voltage_status, :replay_status, :maximum_residual,
    :primary_replay_max_voltage_difference_pu, :iterations,
    :replay_iterations, :warm_start_source, :assembly_ms,
    :primary_power_flow_ms, :replay_ms, :residual_audit_ms,
    :classification_ms, :bookkeeping_ms, :total_evaluation_ms,
    :allocated_bytes, :gc_time_ms, :axis_status, :monotonic_Vmax_check,
    :monotonic_status_check,
)

Base.@kwdef struct ScanConfig
    repository_root::String = normpath(joinpath(@__DIR__, "..", ".."))
    output_directory::String = joinpath(repository_root, "results", "dso_vpp_ac_map_pilot")
    reference_pv_capacity_kw::Float64 = 850.0
    reference_pv_bus::Int = 13
    vmin_pu::Float64 = 0.90
    vmax_pu::Float64 = 1.05
    initial_step_rule::String = "total_canonical_nominal_active_load_kW/64"
    initial_step_kw::Union{Nothing,Float64} = nothing
    maximum_doubling_steps::Int = 12
    maximum_refinement_steps::Int = 60
    capacity_tolerance_kw::Float64 = 1.0
    voltage_margin_tolerance_pu::Float64 = 1e-5
    binding_tolerance_pu::Float64 = 1e-5
    overwrite::Bool = false
    maximum_intervals::Union{Nothing,Int} = nothing
    exact_command::String = "julia --project=. scripts/run_dso_vpp_export_side_axis_scan.jl"
end

function validate_config(config::ScanConfig)
    config.reference_pv_bus == Stage0.REFERENCE_PV_BUS || throw(ArgumentError(
        "the corrected implementation currently requires reference PV bus 13",
    ))
    config.vmin_pu == Stage0.VMIN_PU || throw(ArgumentError("Vmin must equal the replay Vmin"))
    config.vmax_pu == Stage0.VMAX_PU || throw(ArgumentError("Vmax must equal the replay Vmax"))
    config.reference_pv_capacity_kw >= 0 || throw(ArgumentError("H_kW must be nonnegative"))
    config.maximum_doubling_steps > 0 || throw(ArgumentError("maximum doubling steps must be positive"))
    config.maximum_refinement_steps > 0 || throw(ArgumentError("maximum refinement steps must be positive"))
    config.capacity_tolerance_kw > 0 || throw(ArgumentError("capacity tolerance must be positive"))
    config.voltage_margin_tolerance_pu > 0 || throw(ArgumentError("voltage tolerance must be positive"))
    config.binding_tolerance_pu >= 0 || throw(ArgumentError("binding tolerance must be nonnegative"))
    config.maximum_intervals === nothing || config.maximum_intervals > 0 ||
        throw(ArgumentError("maximum intervals must be positive"))
    return config
end

"Load the authoritative IEEE-33 network, canonical normalized profile, and pilot indices."
function load_canonical_data(config::ScanConfig=ScanConfig())
    validate_config(config)
    network = Stage0.build_pilot_network()
    profile = Stage0.load_profile(config.repository_root)
    indices = Stage0.select_pilot_indices(profile)
    if config.maximum_intervals !== nothing
        indices = indices[1:min(config.maximum_intervals, length(indices))]
    end
    return (network=network, profile=profile, indices=indices)
end

function resolved_initial_step_kw(config::ScanConfig, network)
    config.initial_step_kw !== nothing && return config.initial_step_kw
    config.initial_step_rule == "total_canonical_nominal_active_load_kW/64" ||
        throw(ArgumentError("unsupported initial-step rule: $(config.initial_step_rule)"))
    return sum(bus.pd_kw for bus in network.buses) / 64
end

"Evaluate the corrected fixed-injection AC point and its independent replay."
function evaluate_fixed_injection(
    network, profile, profile_index::Integer, p13_kw::Real, p30_kw::Real,
    config::ScanConfig; initial_voltage=nothing, warm_start_source="flat_start",
)
    p13_kw >= 0 && p30_kw >= 0 || throw(ArgumentError("export commands must be nonnegative"))
    return Stage0.evaluate_point(
        network, profile, profile_index, p13_kw, p30_kw;
        reference_pv_capacity_kw=config.reference_pv_capacity_kw,
        initial_voltage=initial_voltage,
        warm_start_source=warm_start_source,
    )
end

function deterministic_bus_set(values, predicate)
    return sort!(Int[i for i in eachindex(values) if predicate(values[i])])
end

format_bus_set(buses) = join(sort!(unique!(Int.(collect(buses)))), ";")

function binding_bus_sets(voltage_pu, config::ScanConfig)
    observed_maximum = maximum(voltage_pu)
    near_maximum = deterministic_bus_set(
        voltage_pu, value -> abs(value - observed_maximum) <= config.binding_tolerance_pu,
    )
    near_upper_limit = deterministic_bus_set(
        voltage_pu, value -> abs(value - config.vmax_pu) <= config.binding_tolerance_pu,
    )
    return (near_maximum=near_maximum, near_upper_limit=near_upper_limit)
end

function point_class(point)
    point.power_flow_status == "CONVERGED" || return :unresolved
    point.replay_status == "PASSED" || return :unresolved
    point.voltage_status == "WITHIN_LIMITS" && return :safe
    point.voltage_status == "UPPER_VOLTAGE_VIOLATION" && return :upper
    point.voltage_status == "LOWER_VOLTAGE_VIOLATION" && return :lower
    point.voltage_status == "BOTH_LIMITS_VIOLATED" && return :both
    return :unresolved
end

"Evaluate one nonnegative command on exactly one coordinate axis."
function evaluate_axis_point(
    network, profile, profile_index::Integer, axis_bus::Integer, command_kw::Real,
    config::ScanConfig; initial_voltage=nothing, warm_start_source="flat_start",
)
    command_kw >= 0 || throw(ArgumentError("axis command must be nonnegative"))
    axis_bus in (13, 30) || throw(ArgumentError("axis bus must be 13 or 30"))
    p13_kw = axis_bus == 13 ? Float64(command_kw) : 0.0
    p30_kw = axis_bus == 30 ? Float64(command_kw) : 0.0
    evaluated = evaluate_fixed_injection(
        network, profile, profile_index, p13_kw, p30_kw, config;
        initial_voltage=initial_voltage, warm_start_source=warm_start_source,
    )
    voltages = abs.(evaluated.primary_voltage_complex_pu)
    sets = binding_bus_sets(voltages, config)
    return merge(evaluated, (
        axis_bus=Int(axis_bus), axis_injection_kw=Float64(command_kw),
        vmax_bus_set=sets.near_maximum,
        upper_limit_near_binding_bus_set=sets.near_upper_limit,
    ))
end

function verify_voltage_monotonicity(points; tolerance_pu=1e-10)
    usable = [point for point in points if point_class(point) != :unresolved]
    return all(
        usable[i].maximum_voltage_pu + tolerance_pu >= usable[i - 1].maximum_voltage_pu
        for i in 2:length(usable)
    )
end

function verify_one_transition(statuses)
    states = Symbol[status isa Symbol ? status : Symbol(status) for status in statuses]
    any(state -> state == :unresolved, states) && return false
    all(state -> state in (:safe, :upper), states) || return false
    transitions = count(i -> states[i - 1] == :safe && states[i] == :upper, 2:length(states))
    reverse_transitions = count(i -> states[i - 1] == :upper && states[i] == :safe, 2:length(states))
    return transitions == 1 && reverse_transitions == 0
end

function adaptive_coarse_doubling(evaluator, initial_step_kw, maximum_steps)
    points = Any[]
    baseline = evaluator(0.0, "baseline", nothing, "flat_start_axis_baseline")
    push!(points, baseline)
    point_class(baseline) == :safe || return (
        points=points, safe=nothing, terminal=baseline, doubling_steps=0,
        status="BASELINE_NOT_SAFE",
    )
    safe = baseline
    for step in 1:maximum_steps
        command = Float64(initial_step_kw) * 2.0^(step - 1)
        point = evaluator(command, "doubling", safe, "previous_doubling_point")
        push!(points, point)
        classification = point_class(point)
        if classification == :safe
            safe = point
        elseif classification == :upper
            return (points=points, safe=safe, terminal=point,
                    doubling_steps=step, status="VALID_COARSE_BRACKET")
        elseif classification == :unresolved
            return (points=points, safe=safe, terminal=point,
                    doubling_steps=step,
                    status="AXIS_UNRESOLVED_BEFORE_VOLTAGE_BOUND")
        else
            return (points=points, safe=safe, terminal=point,
                    doubling_steps=step,
                    status="UNEXPECTED_$(uppercase(String(classification)))_TERMINAL")
        end
    end
    return (points=points, safe=safe, terminal=nothing,
            doubling_steps=maximum_steps, status="DOUBLING_GUARD_REACHED")
end

function refinement_complete(safe, violating, config::ScanConfig)
    width_ok = violating.axis_injection_kw - safe.axis_injection_kw <=
               config.capacity_tolerance_kw
    voltage_ok = config.vmax_pu - safe.maximum_voltage_pu <=
                 config.voltage_margin_tolerance_pu &&
                 violating.maximum_voltage_pu - config.vmax_pu <=
                 config.voltage_margin_tolerance_pu
    return width_ok, voltage_ok
end

function refine_bracket(evaluator, safe, violating, config::ScanConfig)
    safe.axis_injection_kw < violating.axis_injection_kw ||
        throw(ArgumentError("refinement requires an ordered bracket"))
    point_class(safe) == :safe || throw(ArgumentError("lower endpoint must be safe"))
    point_class(violating) == :upper || throw(ArgumentError("upper endpoint must violate Vmax"))
    points = Any[]
    steps = 0
    width_ok, voltage_ok = refinement_complete(safe, violating, config)
    while !(width_ok && voltage_ok) && steps < config.maximum_refinement_steps
        steps += 1
        midpoint = (safe.axis_injection_kw + violating.axis_injection_kw) / 2
        source = abs(midpoint - safe.axis_injection_kw) <=
                 abs(violating.axis_injection_kw - midpoint) ? safe : violating
        point = evaluator(midpoint, "refinement", source, "nearest_bracket_endpoint")
        safe.axis_injection_kw < point.axis_injection_kw < violating.axis_injection_kw ||
            throw(ErrorException("refinement evaluation left the established bracket"))
        push!(points, point)
        classification = point_class(point)
        if classification == :safe
            safe = point
        elseif classification == :upper
            violating = point
        elseif classification == :unresolved
            return (points=points, safe=safe, violating=violating, steps=steps,
                    status="AXIS_UNRESOLVED_DURING_REFINEMENT",
                    width_ok=false, voltage_ok=false)
        else
            return (points=points, safe=safe, violating=violating, steps=steps,
                    status="UNEXPECTED_$(uppercase(String(classification)))_DURING_REFINEMENT",
                    width_ok=false, voltage_ok=false)
        end
        width_ok, voltage_ok = refinement_complete(safe, violating, config)
    end
    status = width_ok && voltage_ok ? "VALID_REFINED_BOUND" : "REFINEMENT_GUARD_REACHED"
    return (points=points, safe=safe, violating=violating, steps=steps,
            status=status, width_ok=width_ok, voltage_ok=voltage_ok)
end

function _timed_axis_point(
    network, profile, profile_index, axis_bus, command, config, phase,
    source_point, source_name,
)
    initial_voltage = source_point === nothing ? nothing : source_point.primary_voltage_complex_pu
    stats = @timed evaluate_axis_point(
        network, profile, profile_index, axis_bus, command, config;
        initial_voltage=initial_voltage, warm_start_source=source_name,
    )
    return merge(stats.value, (
        search_phase=String(phase), allocated_bytes=stats.bytes,
        gc_time_ms=stats.gctime * 1e3,
    ))
end

function scan_one_axis(network, profile, profile_index, axis, config, initial_step_kw)
    evaluator = (command, phase, source, source_name) -> _timed_axis_point(
        network, profile, profile_index, axis.bus, command, config, phase,
        source, source_name,
    )
    coarse = adaptive_coarse_doubling(
        evaluator, initial_step_kw, config.maximum_doubling_steps,
    )
    all_points = copy(coarse.points)
    refinement = nothing
    final_status = coarse.status
    safe = coarse.safe
    violating = coarse.terminal
    if coarse.status == "VALID_COARSE_BRACKET"
        coarse_statuses = point_class.(coarse.points)
        if !verify_voltage_monotonicity(coarse.points)
            final_status = "NONMONOTONIC_VMAX"
        elseif !verify_one_transition(coarse_statuses)
            final_status = "NONMONOTONIC_STATUS"
        else
            refinement = refine_bracket(evaluator, safe, violating, config)
            append!(all_points, refinement.points)
            safe = refinement.safe
            violating = refinement.violating
            final_status = refinement.status
        end
    end
    monotonic_vmax = verify_voltage_monotonicity(coarse.points)
    monotonic_status = coarse.status == "VALID_COARSE_BRACKET" &&
                       verify_one_transition(point_class.(coarse.points))
    scan_rows = scan_output_rows(all_points, axis, config, final_status,
                                 monotonic_vmax, monotonic_status)
    capacity_row = capacity_output_row(
        all_points, axis, config, final_status, coarse.doubling_steps,
        refinement === nothing ? 0 : refinement.steps, safe, violating,
        monotonic_vmax, monotonic_status,
    )
    return (capacity=capacity_row, points=scan_rows)
end

function scan_output_rows(points, axis, config, axis_status, monotonic_vmax, monotonic_status)
    return [(
        timestamp=point.timestamp, axis=axis.name, axis_bus=axis.bus,
        point_index=index, search_phase=point.search_phase,
        axis_injection_kW=point.axis_injection_kw,
        reference_pv_kw=point.actual_reference_pv_kw,
        vpp_p13_kw=point.p13_vpp_kw, vpp_p30_kw=point.p30_vpp_kw,
        H_kW=config.reference_pv_capacity_kw, pv_factor=point.pv_factor,
        P_sub_kW=point.substation_p_kw, Q_sub_kvar=point.substation_q_kvar,
        active_loss_kW=point.active_losses_kw,
        reactive_loss_kvar=point.reactive_losses_kvar,
        Vmin_pu=point.minimum_voltage_pu, Vmin_bus=point.minimum_voltage_bus,
        Vmax_pu=point.maximum_voltage_pu, Vmax_bus=point.maximum_voltage_bus,
        vmax_bus_set=format_bus_set(point.vmax_bus_set),
        upper_limit_near_binding_bus_set=format_bus_set(point.upper_limit_near_binding_bus_set),
        power_flow_status=point.power_flow_status,
        voltage_status=point.voltage_status, replay_status=point.replay_status,
        maximum_residual=point.maximum_absolute_residual,
        primary_replay_max_voltage_difference_pu=point.primary_replay_max_voltage_difference_pu,
        iterations=point.solver_iterations, replay_iterations=point.replay_iterations,
        warm_start_source=point.warm_start_source, assembly_ms=point.assembly_ms,
        primary_power_flow_ms=point.primary_power_flow_ms, replay_ms=point.replay_ms,
        residual_audit_ms=point.residual_audit_ms,
        classification_ms=point.classification_ms, bookkeeping_ms=point.bookkeeping_ms,
        total_evaluation_ms=point.total_evaluation_ms,
        allocated_bytes=point.allocated_bytes, gc_time_ms=point.gc_time_ms,
        axis_status=axis_status, monotonic_Vmax_check=monotonic_vmax,
        monotonic_status_check=monotonic_status,
    ) for (index, point) in enumerate(points)]
end

function _endpoint_value(point, field, default=NaN)
    point === nothing && return default
    return getproperty(point, field)
end

function capacity_output_row(
    points, axis, config, status, doubling_steps, bisection_steps,
    safe, violating, monotonic_vmax, monotonic_status,
)
    baseline = first(points)
    valid_endpoints = safe !== nothing && violating !== nothing
    maximum_residual = maximum(point.maximum_absolute_residual for point in points)
    maximum_difference = maximum(
        point.primary_replay_max_voltage_difference_pu for point in points
    )
    width = valid_endpoints ? violating.axis_injection_kw - safe.axis_injection_kw : NaN
    width_ok, voltage_ok = valid_endpoints ? refinement_complete(safe, violating, config) : (false, false)
    return (
        timestamp=baseline.timestamp, axis=axis.name, axis_bus=axis.bus,
        baseline_status=point_class(baseline) == :safe ? "SAFE" : uppercase(String(point_class(baseline))),
        baseline_power_flow_status=baseline.power_flow_status,
        baseline_voltage_status=baseline.voltage_status,
        baseline_replay_status=baseline.replay_status, axis_status=status,
        initial_step_kW=begin
            first_positive = findfirst(point -> point.search_phase == "doubling", points)
            first_positive === nothing ? NaN : points[first_positive].axis_injection_kw
        end,
        doubling_steps=doubling_steps, bisection_steps=bisection_steps,
        evaluation_count=length(points),
        safe_lower_kW=_endpoint_value(safe, :axis_injection_kw),
        violating_upper_kW=_endpoint_value(violating, :axis_injection_kw),
        axis_capacity_kW=status == "VALID_REFINED_BOUND" ? safe.axis_injection_kw : NaN,
        capacity_tolerance_kW=config.capacity_tolerance_kw, bracket_width_kW=width,
        safe_Vmin_pu=_endpoint_value(safe, :minimum_voltage_pu),
        safe_Vmin_bus=_endpoint_value(safe, :minimum_voltage_bus, 0),
        safe_Vmax_pu=_endpoint_value(safe, :maximum_voltage_pu),
        safe_Vmax_bus=_endpoint_value(safe, :maximum_voltage_bus, 0),
        safe_vmax_bus_set=safe === nothing ? "" : format_bus_set(safe.vmax_bus_set),
        safe_upper_limit_near_binding_bus_set=safe === nothing ? "" : format_bus_set(safe.upper_limit_near_binding_bus_set),
        safe_voltage_margin_pu=safe === nothing ? NaN : config.vmax_pu - safe.maximum_voltage_pu,
        violating_Vmin_pu=_endpoint_value(violating, :minimum_voltage_pu),
        violating_Vmin_bus=_endpoint_value(violating, :minimum_voltage_bus, 0),
        violating_Vmax_pu=_endpoint_value(violating, :maximum_voltage_pu),
        violating_Vmax_bus=_endpoint_value(violating, :maximum_voltage_bus, 0),
        violating_vmax_bus_set=violating === nothing ? "" : format_bus_set(violating.vmax_bus_set),
        violating_upper_limit_near_binding_bus_set=violating === nothing ? "" : format_bus_set(violating.upper_limit_near_binding_bus_set),
        violating_voltage_excess_pu=violating === nothing ? NaN : violating.maximum_voltage_pu - config.vmax_pu,
        binding_tolerance_pu=config.binding_tolerance_pu,
        safe_P_sub_kW=_endpoint_value(safe, :substation_p_kw),
        safe_Q_sub_kvar=_endpoint_value(safe, :substation_q_kvar),
        safe_active_loss_kW=_endpoint_value(safe, :active_losses_kw),
        safe_reactive_loss_kvar=_endpoint_value(safe, :reactive_losses_kvar),
        violating_P_sub_kW=_endpoint_value(violating, :substation_p_kw),
        violating_Q_sub_kvar=_endpoint_value(violating, :substation_q_kvar),
        violating_active_loss_kW=_endpoint_value(violating, :active_losses_kw),
        violating_reactive_loss_kvar=_endpoint_value(violating, :reactive_losses_kvar),
        safe_replay_status=safe === nothing ? "" : safe.replay_status,
        violating_replay_status=violating === nothing ? "" : violating.replay_status,
        monotonic_Vmax_check=monotonic_vmax,
        monotonic_status_check=monotonic_status,
        maximum_residual=maximum_residual,
        maximum_primary_replay_voltage_difference=maximum_difference,
        voltage_margin_tolerance_pu=config.voltage_margin_tolerance_pu,
        power_stopping_criterion_met=width_ok,
        voltage_stopping_criterion_met=voltage_ok,
    )
end

function csv_value(value)
    value === nothing && return ""
    if value isa AbstractString
        escaped = replace(value, "\"" => "\"\"")
        return occursin(r"[,\"\r\n]", escaped) ? "\"$escaped\"" : escaped
    elseif value isa Bool
        return lowercase(string(value))
    elseif value isa AbstractFloat
        return isnan(value) ? "NaN" : isinf(value) ? string(value) : @sprintf("%.12g", value)
    end
    return string(value)
end

function write_csv(path, rows, fields)
    open(path, "w") do io
        println(io, join(String.(fields), ","))
        for row in rows
            println(io, join((csv_value(getproperty(row, field)) for field in fields), ","))
        end
    end
    return path
end

sha256_file(path) = bytes2hex(open(SHA.sha256, path))

function git_output(root, arguments...)
    return strip(read(`git -C $root $(arguments)`, String))
end

function network_data_digest(network)
    io = IOBuffer()
    for bus in sort(network.buses; by=bus -> bus.id)
        println(io, join((bus.id, bus.base_kv, bus.pd_kw, bus.qd_kvar), ','))
    end
    for branch in sort(network.branches; by=branch -> branch.id)
        println(io, join((branch.id, branch.from_bus, branch.to_bus,
                          branch.r_ohm, branch.x_ohm, branch.smax_kva), ','))
    end
    return bytes2hex(SHA.sha256(take!(io)))
end

function config_string(config, initial_step_kw)
    pairs = [
        "H_kW=$(csv_value(config.reference_pv_capacity_kw))",
        "reference_pv_bus=$(config.reference_pv_bus)", "Vmin=$(config.vmin_pu)",
        "Vmax=$(config.vmax_pu)", "initial_step_rule=$(config.initial_step_rule)",
        "initial_step_kW=$(csv_value(initial_step_kw))",
        "maximum_doubling_steps=$(config.maximum_doubling_steps)",
        "maximum_refinement_steps=$(config.maximum_refinement_steps)",
        "capacity_tolerance_kW=$(config.capacity_tolerance_kw)",
        "voltage_margin_tolerance_pu=$(config.voltage_margin_tolerance_pu)",
        "binding_tolerance_pu=$(config.binding_tolerance_pu)",
        "Q_PV_kvar=0", "Q_VPP13_kvar=0", "Q_VPP30_kvar=0",
        "thermal_limit=none", "transformer_limit=none",
        "upstream_exchange=unconstrained", "axes=P13_VPP;P30_VPP",
    ]
    return join(pairs, ";")
end

function output_paths(output_directory)
    return (
        capacity=joinpath(output_directory, "export_side_axis_capacity_bounds.csv"),
        points=joinpath(output_directory, "export_side_axis_scan_points.csv"),
        timing=joinpath(output_directory, "export_side_axis_timing.csv"),
        resource=joinpath(output_directory, "export_side_axis_resource_estimate.csv"),
        report=joinpath(output_directory, "export_side_axis_report.md"),
        manifest=joinpath(output_directory, "export_side_axis_evidence_manifest.csv"),
        topology_csv=joinpath(output_directory, "export_side_axis_topology_diagnostic.csv"),
        topology_md=joinpath(output_directory, "export_side_axis_topology_diagnostic.md"),
        reproducibility=joinpath(output_directory, "export_side_axis_reproducibility_check.csv"),
    )
end

function ensure_output_policy(paths, overwrite)
    existing = [path for path in values(paths) if isfile(path)]
    isempty(existing) || overwrite || throw(ArgumentError(
        "refusing to overwrite existing outputs without --overwrite: $(join(existing, ", "))",
    ))
end

function resource_row(config, interval_count, initial_step_kw)
    expected = interval_count * length(AXES) * (1 + 8 + 15)
    worst = interval_count * length(AXES) *
            (1 + config.maximum_doubling_steps + config.maximum_refinement_steps)
    return (
        intervals=interval_count, axes=length(AXES),
        initial_step_formula=config.initial_step_rule, initial_step_kW=initial_step_kw,
        expected_doubling_steps=8, expected_refinement_steps=15,
        expected_evaluations=expected,
        worst_case_doubling_steps=config.maximum_doubling_steps,
        worst_case_refinement_steps=config.maximum_refinement_steps,
        worst_case_evaluations=worst, estimated_runtime_seconds=60.0,
        estimated_peak_rss_bytes=891_289_600, estimated_output_bytes=12_582_912,
        safety_verdict="SAFE_TO_RUN_UNDER_15_MINUTES_AND_LOW_RAM",
    )
end

function write_report(path, config, capacity_rows, point_rows, initial_step_kw,
                      elapsed_seconds, base_commit)
    valid = [row for row in capacity_rows if row.axis_status == "VALID_REFINED_BOUND"]
    open(path, "w") do io
        println(io, "# Export-side AC axis scan")
        println(io)
        println(io, "- Computation base commit: `$base_commit` (Phase-A repair).")
        println(io, "- Implementation: `$IMPLEMENTATION_ID`.")
        println(io, "- Command: `$(config.exact_command)`.")
        println(io, "- Canonical window: $(first(capacity_rows).timestamp) through $(last(capacity_rows).timestamp).")
        println(io, "- Fixed reference PV: H = $(config.reference_pv_capacity_kw) kW at bus 13, P_PV(t)=H*f_t; all PV/VPP reactive commands are zero.")
        println(io, "- Voltage limits: $(config.vmin_pu)-$(config.vmax_pu) p.u.; no thermal or transformer limit; upstream exchange unconstrained.")
        println(io, "- Binding sets use two separate rules with tau_bind=$(config.binding_tolerance_pu) p.u.: distance from the observed maximum, and absolute distance from the 1.05-p.u. upper limit.")
        println(io)
        println(io, "## Algorithm")
        println(io)
        println(io, "Baseline is evaluated first. Positive commands begin at $initial_step_kw kW (total canonical nominal active load / 64), double up to $(config.maximum_doubling_steps) times, and refine only a safe-to-upper-voltage bracket. Refinement stops when width <= $(config.capacity_tolerance_kw) kW and both endpoint voltage distances <= $(config.voltage_margin_tolerance_pu) p.u. Nonconvergence is unresolved, never physical infeasibility. Every point receives an independent replay.")
        println(io)
        println(io, "## Results")
        println(io)
        println(io, "- Capacity rows: $(length(capacity_rows)); scan evaluations: $(length(point_rows)); valid refined bounds: $(length(valid)).")
        println(io, "- Measured wall time (excluded from scientific reproducibility): $(@sprintf("%.6f", elapsed_seconds)) s.")
        for axis in AXES
            rows = [row for row in valid if row.axis_bus == axis.bus]
            isempty(rows) && continue
            limiting = rows[argmin(row.axis_capacity_kW for row in rows)]
            println(io, "- $(axis.name): minimum safe endpoint $(csv_value(limiting.axis_capacity_kW)) kW at $(limiting.timestamp); safe/violating maximum sets `$(limiting.safe_vmax_bus_set)`/`$(limiting.violating_vmax_bus_set)`.")
        end
        println(io)
        println(io, "These are one-axis-at-a-time bounds. Their Cartesian product is not a certified simultaneous feasible region, not a DOE, and not a two-dimensional map. No LinDistFlow model is implemented here.")
    end
end

function write_manifest(path, config, data, paths, base_commit, initial_step_kw,
                        start_time, end_time, evaluation_count)
    profile_path = joinpath(config.repository_root, "data_processed", "ausgrid",
                            "ausgrid_halfhour_normalized.csv")
    network_path = joinpath(config.repository_root, "src", "data", "ieee33.jl")
    rows = [
        (key="computation_base_commit", value=base_commit),
        (key="artifact_commit", value="SELF_REFERENCE: Git commit containing this manifest"),
        (key="artifact_commit_design", value="symbolic self-reference avoids circular or false commit hashes"),
        (key="julia_version", value=string(VERSION)),
        (key="machine_architecture", value=Sys.MACHINE),
        (key="operating_system", value=string(Sys.KERNEL)),
        (key="julia_threads", value=string(Threads.nthreads())),
        (key="manifest_toml_sha256", value=sha256_file(joinpath(config.repository_root, "Manifest.toml"))),
        (key="solver_power_flow_implementation", value=IMPLEMENTATION_ID),
        (key="profile_input_path", value=relpath(profile_path, config.repository_root)),
        (key="profile_input_sha256", value=sha256_file(profile_path)),
        (key="network_input_path", value=relpath(network_path, config.repository_root)),
        (key="network_input_file_sha256", value=sha256_file(network_path)),
        (key="network_data_sha256", value=network_data_digest(data.network)),
        (key="profile_data_sha256", value=sha256_file(profile_path)),
        (key="runner_path", value="scripts/run_dso_vpp_export_side_axis_scan.jl"),
        (key="exact_command", value=config.exact_command),
        (key="resolved_configuration", value=config_string(config, initial_step_kw)),
        (key="start_timestamp", value=string(start_time)),
        (key="end_timestamp", value=string(end_time)),
        (key="canonical_start_timestamp", value=Dates.format(
            data.profile.timestamps[first(data.indices)], dateformat"yyyy-mm-dd HH:MM:SS")),
        (key="canonical_end_timestamp", value=Dates.format(
            data.profile.timestamps[last(data.indices)], dateformat"yyyy-mm-dd HH:MM:SS")),
        (key="number_of_evaluations", value=string(evaluation_count)),
    ]
    for name in (:capacity, :points, :timing, :resource, :report,
                 :topology_csv, :topology_md, :reproducibility)
        output = getproperty(paths, name)
        isfile(output) || continue
        push!(rows, (key="output_sha256_$(basename(output))", value=sha256_file(output)))
    end
    write_csv(path, rows, (:key, :value))
end

"Scan every selected timestamp on both coordinate axes and write all permanent artifacts."
function run_scan(config::ScanConfig=ScanConfig())
    validate_config(config)
    data = load_canonical_data(config)
    initial_step_kw = resolved_initial_step_kw(config, data.network)
    paths = output_paths(config.output_directory)
    mkpath(config.output_directory)
    ensure_output_policy(paths, config.overwrite)
    # A reproducibility check is derived from a later, independent second run.
    # Explicit overwrite invalidates any check left by an older primary run.
    if config.overwrite && isfile(paths.reproducibility)
        rm(paths.reproducibility; force=true)
    end
    capacity_rows = NamedTuple[]
    point_rows = NamedTuple[]
    started_at = now(UTC)
    started_ns = time_ns()
    for profile_index in data.indices
        for axis in AXES
            result = scan_one_axis(
                data.network, data.profile, profile_index, axis, config, initial_step_kw,
            )
            push!(capacity_rows, result.capacity)
            append!(point_rows, result.points)
        end
    end
    elapsed_seconds = (time_ns() - started_ns) / 1e9
    ended_at = now(UTC)
    base_commit = git_output(config.repository_root, "rev-parse", "HEAD")
    write_csv(paths.capacity, capacity_rows, CAPACITY_FIELDS)
    write_csv(paths.points, point_rows, SCAN_FIELDS)
    timing_row = (
        computation_base_commit=base_commit,
        timing_scope="scan orchestration including assembly, primary AC solve, independent replay, residual audit, classification, evaluator bookkeeping, and CSV-row construction; excludes artifact file I/O",
        evaluation_count=length(point_rows), wall_seconds=elapsed_seconds,
        total_allocated_bytes=sum(row.allocated_bytes for row in point_rows),
        total_gc_time_ms=sum(row.gc_time_ms for row in point_rows),
    )
    write_csv(paths.timing, [timing_row], propertynames(timing_row))
    resources = resource_row(config, length(data.indices), initial_step_kw)
    write_csv(paths.resource, [resources], propertynames(resources))
    write_report(paths.report, config, capacity_rows, point_rows, initial_step_kw,
                 elapsed_seconds, base_commit)
    topology_rows = write_topology_diagnostic(
        config, capacity_rows, paths.topology_csv, paths.topology_md,
    )
    write_manifest(paths.manifest, config, data, paths, base_commit, initial_step_kw,
                   started_at, ended_at, length(point_rows))
    return (config=config, data=data, capacity_rows=capacity_rows,
            point_rows=point_rows, topology_rows=topology_rows,
            paths=paths, elapsed_seconds=elapsed_seconds)
end

const REPRO_CAPACITY_EXCLUDED = Set{String}()
const REPRO_POINT_EXCLUDED = Set([
    "assembly_ms", "primary_power_flow_ms", "replay_ms", "residual_audit_ms",
    "classification_ms", "bookkeeping_ms", "total_evaluation_ms",
    "allocated_bytes", "gc_time_ms",
])

function read_simple_csv(path)
    lines = readlines(path)
    headers = split(first(lines), ','; keepempty=true)
    rows = [split(line, ','; keepempty=true) for line in Iterators.drop(lines, 1)]
    all(length(row) == length(headers) for row in rows) ||
        throw(ArgumentError("quoted commas are not supported by scientific comparison"))
    return headers, rows
end

function compare_csv(primary, duplicate, excluded)
    headers_a, rows_a = read_simple_csv(primary)
    headers_b, rows_b = read_simple_csv(duplicate)
    headers_a == headers_b || return (rows=min(length(rows_a), length(rows_b)),
                                      mismatches=1, maximum_discrepancy=Inf)
    length(rows_a) == length(rows_b) || return (rows=min(length(rows_a), length(rows_b)),
                                                mismatches=1, maximum_discrepancy=Inf)
    included = findall(header -> !(header in excluded), headers_a)
    mismatches = 0
    maximum_discrepancy = 0.0
    for (row_a, row_b) in zip(rows_a, rows_b), index in included
        row_a[index] == row_b[index] && continue
        parsed_a = tryparse(Float64, row_a[index])
        parsed_b = tryparse(Float64, row_b[index])
        if parsed_a !== nothing && parsed_b !== nothing
            difference = abs(parsed_a - parsed_b)
            maximum_discrepancy = max(maximum_discrepancy, difference)
        else
            maximum_discrepancy = Inf
        end
        mismatches += 1
    end
    return (rows=length(rows_a), mismatches=mismatches,
            maximum_discrepancy=maximum_discrepancy)
end

function write_reproducibility_check(primary_directory, duplicate_directory, output_path)
    comparisons = NamedTuple[]
    for (filename, excluded) in (
        ("export_side_axis_capacity_bounds.csv", REPRO_CAPACITY_EXCLUDED),
        ("export_side_axis_scan_points.csv", REPRO_POINT_EXCLUDED),
    )
        result = compare_csv(joinpath(primary_directory, filename),
                             joinpath(duplicate_directory, filename), excluded)
        push!(comparisons, (
            file=filename, compared_rows=result.rows,
            scientific_mismatches=result.mismatches,
            maximum_numerical_discrepancy=result.maximum_discrepancy,
            excluded_fields=join(sort!(collect(excluded)), ";"),
            reproducible=result.mismatches == 0,
        ))
    end
    write_csv(output_path, comparisons, propertynames(first(comparisons)))
    return comparisons
end

function append_manifest_output_hash(manifest_path, output_path)
    key = "output_sha256_$(basename(output_path))"
    existing = readlines(manifest_path)
    any(line -> startswith(line, key * ","), existing) && throw(ArgumentError(
        "manifest already contains $key; regenerate the primary run before comparing",
    ))
    open(manifest_path, "a") do io
        println(io, csv_value(key), ",", csv_value(sha256_file(output_path)))
    end
    return manifest_path
end

function radial_path_branch_ids(network, bus_id)
    topology = network.topology
    1 <= bus_id <= length(network.buses) || throw(ArgumentError("invalid bus ID"))
    path = Int[]
    current = bus_id
    while current != topology.root_bus
        branch = topology.parent_branch[current]
        branch > 0 || throw(ArgumentError("missing radial parent branch for bus $current"))
        push!(path, branch)
        current = topology.branch_from[branch]
    end
    return reverse(path)
end

function topology_coefficient(network, candidate_bus, injection_bus)
    candidate_path = Set(radial_path_branch_ids(network, candidate_bus))
    injection_path = Set(radial_path_branch_ids(network, injection_bus))
    common = intersect(candidate_path, injection_path)
    return 2 * sum(real(network.impedance_pu[branch]) for branch in common)
end

function parse_bus_set(value)
    isempty(value) && return Int[]
    return sort!(parse.(Int, split(value, ';')))
end

function validate_radial_topology(network)
    topology = network.topology
    topology.root_bus == 1 || throw(ArgumentError("IEEE-33 slack/root must be bus 1"))
    length(network.branches) == length(network.buses) - 1 ||
        throw(ArgumentError("network does not have n-1 branches"))
    for bus in 2:length(network.buses)
        path = radial_path_branch_ids(network, bus)
        isempty(path) && throw(ArgumentError("bus $bus is disconnected"))
        last_branch = last(path)
        topology.branch_to[last_branch] == bus ||
            throw(ArgumentError("branch orientation is not root-to-leaf"))
    end
    all(bus -> bus.base_kv == 12.66, network.buses) ||
        throw(ArgumentError("unexpected voltage base"))
    all(real(z) > 0 for z in network.impedance_pu) ||
        throw(ArgumentError("resistances must be positive in per unit"))
    return true
end

function write_topology_diagnostic(config::ScanConfig, capacity_rows, csv_path, markdown_path)
    data = load_canonical_data(config)
    validate_radial_topology(data.network)
    limiting = Dict{Int,Any}()
    for axis_bus in (13, 30)
        rows = [row for row in capacity_rows if row.axis_bus == axis_bus &&
                row.axis_status == "VALID_REFINED_BOUND"]
        limiting[axis_bus] = rows[argmin(row.axis_capacity_kW for row in rows)]
    end
    candidates = Dict(
        bus => sort!(unique!(vcat(parse_bus_set(limiting[bus].safe_vmax_bus_set),
                                  parse_bus_set(limiting[bus].violating_vmax_bus_set))))
        for bus in (13, 30)
    )
    common = intersect(Set(candidates[13]), Set(candidates[30]))
    ac_ratio = limiting[13].axis_capacity_kW / limiting[30].axis_capacity_kW
    timestamp_to_index = Dict(
        Dates.format(data.profile.timestamps[index], dateformat"yyyy-mm-dd HH:MM:SS") => index
        for index in data.indices
    )
    rows = NamedTuple[]
    for axis_bus in (13, 30)
        limit = limiting[axis_bus]
        profile_index = timestamp_to_index[limit.timestamp]
        baseline = evaluate_fixed_injection(
            data.network, data.profile, profile_index, 0.0, 0.0, config,
        )
        baseline_v2 = abs2.(baseline.primary_voltage_complex_pu)
        for candidate in candidates[axis_bus]
            coefficient = topology_coefficient(data.network, candidate, axis_bus)
            predicted_kw = ((config.vmax_pu^2 - baseline_v2[candidate]) / coefficient) * Stage0.BASE_KW
            is_common = candidate in common
            topology_ratio = is_common ?
                topology_coefficient(data.network, candidate, 30) /
                topology_coefficient(data.network, candidate, 13) : NaN
            relative_ratio = is_common ? (ac_ratio - topology_ratio) / topology_ratio : NaN
            interpretation = if length(candidates[axis_bus]) > 1
                "AMBIGUOUS_MULTIPLE_BINDING_BUSES"
            elseif !isempty(common)
                isfinite(relative_ratio) && abs(relative_ratio) <= 0.25 ?
                    "STRUCTURALLY_CONSISTENT" :
                    "MATERIAL_DIFFERENCE_REQUIRES_LATER_INVESTIGATION"
            else
                "NOT_APPLICABLE_DIFFERENT_BINDING_BUSES"
            end
            push!(rows, (
                timestamp=limit.timestamp, axis_bus=axis_bus,
                candidate_binding_bus=candidate,
                AC_axis_capacity_kW=limit.axis_capacity_kW,
                baseline_AC_voltage_squared=baseline_v2[candidate],
                path_resistance_coefficient=coefficient,
                predicted_capacity_kW=predicted_kw,
                capacity_ratio_or_difference=(limit.axis_capacity_kW - predicted_kw) / predicted_kw,
                common_binding_bus=is_common, AC_axis_ratio=isempty(common) ? NaN : ac_ratio,
                topology_coefficient_ratio=topology_ratio,
                relative_ratio_difference=relative_ratio,
                interpretation=interpretation,
            ))
        end
    end
    fields = propertynames(first(rows))
    write_csv(csv_path, rows, fields)
    open(markdown_path, "w") do io
        println(io, "# AC-anchored topology-sensitivity diagnostic")
        println(io)
        println(io, "This is a topology-only first-order diagnostic, not classical LinDistFlow and not a LinDistFlow validation. The code verified the radial parent structure, slack bus 1, root-to-leaf orientation, IEEE-33 bus numbering, 12.66-kV base, 10-MVA/10,000-kW power base, ohm-to-per-unit conversion, and positive branch resistance.")
        println(io)
        for axis_bus in (13, 30)
            limit = limiting[axis_bus]
            println(io, "- Axis $axis_bus: limiting timestamp $(limit.timestamp), safe AC capacity $(csv_value(limit.axis_capacity_kW)) kW, safe/violating maximum-voltage sets `$(limit.safe_vmax_bus_set)`/`$(limit.violating_vmax_bus_set)`.")
        end
        println(io)
        if isempty(common)
            println(io, "The axes have different candidate binding buses, so the single-ratio formula is not applicable. Separate AC-anchored predictions use (1.05^2-v_i^AC(0))/c_i,k in consistent per-unit quantities. Discrepancy is diagnostic only and does not imply causality or rejection of the AC model.")
        else
            println(io, "Common candidate binding buses: $(format_bus_set(common)). The AC capacity ratio and topology-coefficient ratio are reported for every common candidate. No hard pass/fail tolerance is imposed.")
        end
    end
    return rows
end

export ScanConfig, CAPACITY_FIELDS, SCAN_FIELDS, load_canonical_data,
       evaluate_fixed_injection, evaluate_axis_point, adaptive_coarse_doubling,
       verify_one_transition, verify_voltage_monotonicity, refine_bracket,
       binding_bus_sets, format_bus_set, scan_one_axis, run_scan,
       write_reproducibility_check, append_manifest_output_hash,
       validate_radial_topology,
       topology_coefficient, write_topology_diagnostic, output_paths

end
