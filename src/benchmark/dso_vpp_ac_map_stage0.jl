module DSOVPPACMapStage0

using CiroPVHC
using Dates
using Printf
using SHA

const PILOT_DATES = (Date(2012, 10, 15), Date(2012, 10, 16))
const EXPECTED_INTERVALS = 96
const ROOT_VOLTAGE_PU = 1.00
const VMIN_PU = 0.90
const VMAX_PU = 1.05
const BASE_MVA = 10.0
const BASE_KW = 10_000.0
const PRIMARY_TOLERANCE_PU = 1e-11
const PRIMARY_MAXIMUM_ITERATIONS = 2000
const REPLAY_TOLERANCE_PU = 1e-12
const REPLAY_MAXIMUM_ITERATIONS = 4000
const DAMPING = 0.70
const RESIDUAL_TOLERANCE_PU = 1e-5
const REPLAY_VOLTAGE_MATCH_TOLERANCE_PU = 2e-5
const REPLAY_SUBSTATION_MATCH_TOLERANCE_KW = 5e-2
const SAMPLE_COUNT = 1000
const INJECTION_MIN_KW = -2500.0
const INJECTION_MAX_KW = 6500.0
const REFERENCE_PV_BUS = 13
const REFERENCE_PV_CAPACITY_KW = 850.0

struct PilotNetwork
    buses::Vector{CiroPVHC.Bus}
    branches::Vector{CiroPVHC.Branch}
    topology::Any
    impedance_pu::Vector{ComplexF64}
end

function load_profile(repository_root::AbstractString)
    path = joinpath(
        repository_root,
        "data_processed",
        "ausgrid",
        "ausgrid_halfhour_normalized.csv",
    )
    return CiroPVHC.read_s1b_profile(path)
end

function select_pilot_indices(profile)
    indices = findall(timestamp -> Date(timestamp) in PILOT_DATES, profile.timestamps)
    length(indices) == EXPECTED_INTERVALS || throw(ArgumentError(
        "pilot window must contain exactly $EXPECTED_INTERVALS intervals; found $(length(indices))",
    ))
    length(unique(profile.timestamps[indices])) == EXPECTED_INTERVALS ||
        throw(ArgumentError("pilot window contains duplicate intervals"))
    all(diff(profile.timestamps[indices]) .== Minute(30)) ||
        throw(ArgumentError("pilot window contains a missing or non-half-hour interval"))
    counts = [count(i -> Date(profile.timestamps[i]) == day, indices) for day in PILOT_DATES]
    counts == [48, 48] || throw(ArgumentError(
        "pilot dates must each contain 48 intervals; found $counts",
    ))
    all(isfinite, profile.load_multiplier[indices]) ||
        throw(ArgumentError("pilot load factors contain nonfinite values"))
    all(isfinite, profile.pv_profile[indices]) ||
        throw(ArgumentError("pilot PV factors contain nonfinite values"))
    Dates.format(profile.timestamps[first(indices)], dateformat"yyyy-mm-dd HH:MM:SS") ==
        "2012-10-15 00:00:00" || throw(ArgumentError("pilot start timestamp mismatch"))
    Dates.format(profile.timestamps[last(indices)], dateformat"yyyy-mm-dd HH:MM:SS") ==
        "2012-10-16 23:30:00" || throw(ArgumentError("pilot end timestamp mismatch"))
    return indices
end

function build_pilot_network()
    buses, branches = CiroPVHC.build_ieee33_network()
    topology = CiroPVHC._s0_unconstrained_topology(buses, branches; root_bus=1)
    bus_by_id = Dict(bus.id => bus for bus in buses)
    branch_by_id = Dict(branch.id => branch for branch in branches)
    impedance_pu = zeros(ComplexF64, length(branches))
    for branch_id in eachindex(impedance_pu)
        branch = branch_by_id[branch_id]
        from_bus = topology.branch_from[branch_id]
        zbase_ohm = bus_by_id[from_bus].base_kv^2 / BASE_MVA
        impedance_pu[branch_id] = complex(branch.r_ohm, branch.x_ohm) / zbase_ohm
    end
    all(bus -> bus.base_kv == 12.66, buses) ||
        throw(ArgumentError("IEEE 33-bus base voltage is not uniformly 12.66 kV"))
    all(branch -> branch.smax_kva == 0.0, branches) ||
        throw(ArgumentError("unexpected nonzero branch rating in the pilot network"))
    return PilotNetwork(buses, branches, topology, impedance_pu)
end

function assemble_stage0_inputs(
    network::PilotNetwork,
    load_multiplier::Real,
    pv_factor::Real,
    reference_pv_capacity_kw::Real,
    p13_vpp_kw::Real,
    p30_vpp_kw::Real,
)
    load_scale = Float64(load_multiplier)
    pv_scale = Float64(pv_factor)
    reference_capacity_kw = Float64(reference_pv_capacity_kw)
    isfinite(load_scale) && load_scale >= 0.0 ||
        throw(ArgumentError("load multiplier must be finite and nonnegative"))
    isfinite(pv_scale) && pv_scale >= 0.0 ||
        throw(ArgumentError("PV factor must be finite and nonnegative"))
    isfinite(reference_capacity_kw) && reference_capacity_kw >= 0.0 ||
        throw(ArgumentError("reference PV capacity must be finite and nonnegative"))
    all(isfinite, (p13_vpp_kw, p30_vpp_kw)) ||
        throw(ArgumentError("VPP injections must be finite"))

    reference_pv_kw = reference_capacity_kw * pv_scale
    reference_pv_by_bus_kw = zeros(Float64, length(network.buses))
    reference_pv_by_bus_kw[REFERENCE_PV_BUS] = reference_pv_kw
    vpp_injection_by_bus_kw = zeros(Float64, length(network.buses))
    vpp_injection_by_bus_kw[13] = Float64(p13_vpp_kw)
    vpp_injection_by_bus_kw[30] = Float64(p30_vpp_kw)
    active_injection_by_bus_kw =
        reference_pv_by_bus_kw .+ vpp_injection_by_bus_kw
    net_demand_pu = zeros(ComplexF64, length(network.buses))
    for bus in network.buses
        net_demand_pu[bus.id] = complex(
            bus.pd_kw * load_scale - active_injection_by_bus_kw[bus.id],
            bus.qd_kvar * load_scale,
        ) / BASE_KW
    end
    return (
        load_multiplier=load_scale,
        pv_factor=pv_scale,
        reference_pv_capacity_kw=reference_capacity_kw,
        reference_pv_kw=reference_pv_kw,
        reference_pv_by_bus_kw=reference_pv_by_bus_kw,
        vpp_injection_by_bus_kw=vpp_injection_by_bus_kw,
        active_injection_by_bus_kw=active_injection_by_bus_kw,
        net_demand_pu=net_demand_pu,
    )
end

function primary_power_flow(
    network::PilotNetwork,
    load_multiplier::Real,
    p13_vpp_kw::Real,
    p30_vpp_kw::Real;
    pv_factor::Real=0.0,
    reference_pv_capacity_kw::Real=0.0,
    initial_voltage::Union{Nothing,Vector{ComplexF64}}=nothing,
    tolerance_pu::Real=PRIMARY_TOLERANCE_PU,
    maximum_iterations::Integer=PRIMARY_MAXIMUM_ITERATIONS,
    damping::Real=DAMPING,
    assembled_inputs=nothing,
)
    maximum_iterations > 0 || throw(ArgumentError("maximum iterations must be positive"))
    0.0 < damping <= 1.0 || throw(ArgumentError("damping must lie in (0, 1]"))
    inputs = assembled_inputs === nothing ?
             assemble_stage0_inputs(
                 network,
                 load_multiplier,
                 pv_factor,
                 reference_pv_capacity_kw,
                 p13_vpp_kw,
                 p30_vpp_kw,
             ) :
             assembled_inputs
    net_demand_pu = inputs.net_demand_pu

    voltage = initial_voltage === nothing ?
              fill(complex(ROOT_VOLTAGE_PU, 0.0), length(network.buses)) :
              copy(initial_voltage)
    length(voltage) == length(network.buses) ||
        throw(ArgumentError("initial-voltage vector length mismatch"))
    voltage[network.topology.root_bus] = complex(ROOT_VOLTAGE_PU, 0.0)
    converged = false
    iterations = 0
    final_update = Inf
    for iteration in 1:Int(maximum_iterations)
        iterations = iteration
        currents = CiroPVHC._s0_unconstrained_branch_currents(
            network.topology,
            voltage,
            net_demand_pu,
        )
        currents === nothing && break
        branch_current, _ = currents
        fixed_voltage = CiroPVHC._s0_unconstrained_forward_voltage(
            network.topology,
            network.impedance_pu,
            branch_current,
            ROOT_VOLTAGE_PU,
        )
        final_update = maximum(abs.(fixed_voltage .- voltage))
        isfinite(final_update) || break
        voltage .= Float64(damping) .* fixed_voltage .+
                   (1.0 - Float64(damping)) .* voltage
        voltage[network.topology.root_bus] = complex(ROOT_VOLTAGE_PU, 0.0)
        if final_update <= Float64(tolerance_pu)
            voltage .= fixed_voltage
            converged = true
            break
        end
    end

    magnitudes = abs.(voltage)
    if !converged
        return (
            converged=false,
            iterations=iterations,
            voltage_complex_pu=voltage,
            voltage_pu=magnitudes,
            minimum_voltage_pu=minimum(magnitudes),
            minimum_voltage_bus=argmin(magnitudes),
            maximum_voltage_pu=maximum(magnitudes),
            maximum_voltage_bus=argmax(magnitudes),
            substation_p_kw=NaN,
            substation_q_kvar=NaN,
            active_losses_kw=NaN,
            reactive_losses_kvar=NaN,
            maximum_voltage_equation_residual_pu=Inf,
            assembled_inputs=inputs,
        )
    end

    branch_current, _ = something(CiroPVHC._s0_unconstrained_branch_currents(
        network.topology,
        voltage,
        net_demand_pu,
    ))
    fixed_voltage = CiroPVHC._s0_unconstrained_forward_voltage(
        network.topology,
        network.impedance_pu,
        branch_current,
        ROOT_VOLTAGE_PU,
    )
    voltage_residual = maximum(abs.(fixed_voltage .- voltage))
    branch_power = zeros(ComplexF64, length(network.branches))
    losses = 0.0 + 0.0im
    for branch_id in eachindex(branch_current)
        from_bus = network.topology.branch_from[branch_id]
        branch_power[branch_id] =
            voltage[from_bus] * conj(branch_current[branch_id]) * BASE_KW
        losses += network.impedance_pu[branch_id] * abs2(branch_current[branch_id]) * BASE_KW
    end
    root_branches = [
        network.topology.parent_branch[child]
        for child in network.topology.children[network.topology.root_bus]
    ]
    substation = sum(branch_power[root_branches])
    magnitudes = abs.(voltage)
    return (
        converged=true,
        iterations=iterations,
        voltage_complex_pu=voltage,
        voltage_pu=magnitudes,
        minimum_voltage_pu=minimum(magnitudes),
        minimum_voltage_bus=argmin(magnitudes),
        maximum_voltage_pu=maximum(magnitudes),
        maximum_voltage_bus=argmax(magnitudes),
        substation_p_kw=real(substation),
        substation_q_kvar=imag(substation),
        active_losses_kw=real(losses),
        reactive_losses_kvar=imag(losses),
        maximum_voltage_equation_residual_pu=voltage_residual,
        assembled_inputs=inputs,
    )
end

function replay_status(primary, replay)
    !replay.converged && return "NONCONVERGED"
    !replay.phasor_recoverable && return "PHASOR_NOT_RECOVERABLE"
    (!isfinite(replay.maximum_equation_residual) ||
     !isfinite(replay.maximum_scaled_residual) ||
     replay.maximum_equation_residual > RESIDUAL_TOLERANCE_PU ||
     replay.maximum_scaled_residual > RESIDUAL_TOLERANCE_PU) &&
        return "RESIDUAL_FAILED"
    voltage_difference = maximum(abs.(primary.voltage_pu .- replay.voltage_pu))
    substation_difference = abs(primary.substation_p_kw - replay.substation_p_kw)
    (voltage_difference > REPLAY_VOLTAGE_MATCH_TOLERANCE_PU ||
     substation_difference > REPLAY_SUBSTATION_MATCH_TOLERANCE_KW) &&
        return "STATE_MISMATCH"
    return "PASSED"
end

function classify_voltage(power_flow_status::AbstractString, replay_state)
    power_flow_status == "CONVERGED" || return "NOT_EVALUATED"
    replay_state === nothing && return "NOT_EVALUATED"
    lower = replay_state.minimum_voltage_pu < VMIN_PU
    upper = replay_state.maximum_voltage_pu > VMAX_PU
    lower && upper && return "BOTH_LIMITS_VIOLATED"
    lower && return "LOWER_VOLTAGE_VIOLATION"
    upper && return "UPPER_VOLTAGE_VIOLATION"
    return "WITHIN_LIMITS"
end

function legacy_label(power_flow_status::AbstractString, voltage_status::AbstractString)
    power_flow_status == "NONCONVERGED" && return "UNRESOLVED_AC_NONCONVERGENCE"
    voltage_status == "NOT_EVALUATED" && return "UNKNOWN_SOLVER"
    voltage_status == "WITHIN_LIMITS" && return "FEASIBLE"
    return "INFEASIBLE_VOLTAGE"
end

function evaluate_point(
    network::PilotNetwork,
    profile,
    profile_index::Integer,
    p13_vpp_kw::Real,
    p30_vpp_kw::Real;
    reference_pv_capacity_kw::Real=REFERENCE_PV_CAPACITY_KW,
    initial_voltage::Union{Nothing,Vector{ComplexF64}}=nothing,
    warm_start_source::AbstractString="flat_start",
    primary_maximum_iterations::Integer=PRIMARY_MAXIMUM_ITERATIONS,
)
    started_ns = time_ns()
    assembly_started_ns = time_ns()
    assembled_inputs = assemble_stage0_inputs(
        network,
        profile.load_multiplier[profile_index],
        profile.pv_profile[profile_index],
        reference_pv_capacity_kw,
        p13_vpp_kw,
        p30_vpp_kw,
    )
    assembly_ms = (time_ns() - assembly_started_ns) / 1e6

    primary_started_ns = time_ns()
    primary = primary_power_flow(
        network,
        profile.load_multiplier[profile_index],
        p13_vpp_kw,
        p30_vpp_kw;
        pv_factor=profile.pv_profile[profile_index],
        reference_pv_capacity_kw=reference_pv_capacity_kw,
        initial_voltage=initial_voltage,
        maximum_iterations=primary_maximum_iterations,
        assembled_inputs=assembled_inputs,
    )
    primary_power_flow_ms = (time_ns() - primary_started_ns) / 1e6

    reference_pv_kw = Float64(reference_pv_capacity_kw) *
                      profile.pv_profile[profile_index]
    # replay_s1b_interval accepts one availability multiplier. Passing the
    # already time-resolved, explicitly additive injections with availability
    # 1.0 preserves the separate reference-PV and VPP assembly above.
    replay_injections_kw = Dict(
        13 => reference_pv_kw + Float64(p13_vpp_kw),
        30 => Float64(p30_vpp_kw),
    )
    replay_started_ns = time_ns()
    replay = CiroPVHC.replay_s1b_interval(
        network.buses,
        network.branches,
        profile.load_multiplier[profile_index],
        1.0,
        replay_injections_kw;
        base_mva=BASE_MVA,
        root_voltage_pu=ROOT_VOLTAGE_PU,
        vmin_pu=VMIN_PU,
        vmax_pu=VMAX_PU,
        tolerance_pu=REPLAY_TOLERANCE_PU,
        voltage_tolerance_pu=0.0,
        residual_tolerance_pu=RESIDUAL_TOLERANCE_PU,
        maximum_iterations=REPLAY_MAXIMUM_ITERATIONS,
        damping=DAMPING,
    )
    replay_ms = (time_ns() - replay_started_ns) / 1e6

    residual_audit_started_ns = time_ns()
    power_flow_status = primary.converged ? "CONVERGED" : "NONCONVERGED"
    status = primary.converged ? replay_status(primary, replay) : "PRIMARY_NOT_CONVERGED"
    voltage_difference = primary.converged && replay.converged ?
                         maximum(abs.(primary.voltage_pu .- replay.voltage_pu)) : Inf
    residual_audit_ms = (time_ns() - residual_audit_started_ns) / 1e6

    classification_started_ns = time_ns()
    voltage_status = classify_voltage(
        power_flow_status,
        status == "PASSED" ? replay : nothing,
    )
    classification = legacy_label(power_flow_status, voltage_status)
    classification_ms = (time_ns() - classification_started_ns) / 1e6

    formatted_timestamp = Dates.format(
        profile.timestamps[profile_index],
        dateformat"yyyy-mm-dd HH:MM:SS",
    )
    total_p_load_kw = sum(bus.pd_kw for bus in network.buses) *
                      profile.load_multiplier[profile_index]
    total_q_load_kvar = sum(bus.qd_kvar for bus in network.buses) *
                        profile.load_multiplier[profile_index]
    total_evaluation_ms = (time_ns() - started_ns) / 1e6
    bookkeeping_ms = max(
        0.0,
        total_evaluation_ms - assembly_ms - primary_power_flow_ms - replay_ms -
        residual_audit_ms - classification_ms,
    )
    runtime_seconds = total_evaluation_ms / 1e3
    return (
        timestamp=formatted_timestamp,
        reference_pv_capacity_kw=Float64(reference_pv_capacity_kw),
        pv_factor=profile.pv_profile[profile_index],
        actual_reference_pv_kw=reference_pv_kw,
        p13_vpp_kw=Float64(p13_vpp_kw),
        p30_vpp_kw=Float64(p30_vpp_kw),
        q13_vpp_kvar=0.0,
        q30_vpp_kvar=0.0,
        total_p_load_kw=total_p_load_kw,
        total_q_load_kvar=total_q_load_kvar,
        power_flow_status=power_flow_status,
        voltage_status=voltage_status,
        legacy_label=classification,
        classification=classification,
        solver_status=power_flow_status,
        replay_status=status,
        maximum_absolute_residual=replay.maximum_equation_residual,
        maximum_scaled_residual=replay.maximum_scaled_residual,
        minimum_voltage_pu=replay.minimum_voltage_pu,
        minimum_voltage_bus=replay.minimum_voltage_bus,
        maximum_voltage_pu=replay.maximum_voltage_pu,
        maximum_voltage_bus=replay.maximum_voltage_bus,
        substation_p_kw=replay.substation_p_kw,
        substation_q_kvar=replay.substation_q_kvar,
        active_losses_kw=replay.active_losses_kw,
        reactive_losses_kvar=replay.reactive_losses_kvar,
        warm_start_source=String(warm_start_source),
        runtime_seconds=runtime_seconds,
        assembly_ms=assembly_ms,
        primary_power_flow_ms=primary_power_flow_ms,
        replay_ms=replay_ms,
        residual_audit_ms=residual_audit_ms,
        classification_ms=classification_ms,
        bookkeeping_ms=bookkeeping_ms,
        total_evaluation_ms=total_evaluation_ms,
        solver_iterations=primary.iterations,
        replay_iterations=replay.iterations,
        primary_replay_max_voltage_difference_pu=voltage_difference,
        primary_voltage_equation_residual_pu=
            primary.maximum_voltage_equation_residual_pu,
        primary_voltage_complex_pu=primary.voltage_complex_pu,
        assembled_reference_pv_by_bus_kw=
            primary.assembled_inputs.reference_pv_by_bus_kw,
        assembled_vpp_injection_by_bus_kw=
            primary.assembled_inputs.vpp_injection_by_bus_kw,
        assembled_active_injection_by_bus_kw=
            primary.assembled_inputs.active_injection_by_bus_kw,
        assembled_net_demand_pu=primary.assembled_inputs.net_demand_pu,
    )
end

function halton(index::Integer, base::Integer)
    index >= 1 || throw(ArgumentError("Halton index must be positive"))
    base >= 2 || throw(ArgumentError("Halton base must be at least two"))
    value = 0.0
    fraction = 1.0 / base
    remaining = Int(index)
    while remaining > 0
        value += fraction * (remaining % base)
        remaining ÷= base
        fraction /= base
    end
    return value
end

function sample_plan(indices::AbstractVector{<:Integer}; count::Integer=SAMPLE_COUNT)
    count >= length(indices) || throw(ArgumentError(
        "sample count must include one zero-injection reference per interval",
    ))
    span = INJECTION_MAX_KW - INJECTION_MIN_KW
    rows = NamedTuple[]
    for sample_id in 1:Int(count)
        local_interval = mod1(sample_id, length(indices))
        if sample_id <= length(indices)
            p13, p30 = 0.0, 0.0
        else
            sequence_index = sample_id - length(indices)
            p13 = INJECTION_MIN_KW + span * halton(sequence_index, 2)
            p30 = INJECTION_MIN_KW + span * halton(sequence_index, 3)
        end
        push!(rows, (
            sample_id=sample_id,
            local_interval=local_interval,
            profile_index=Int(indices[local_interval]),
            p13_vpp_kw=p13,
            p30_vpp_kw=p30,
        ))
    end
    return rows
end

function nearest_feasible_start(feasible_starts, p13::Float64, p30::Float64)
    isempty(feasible_starts) && return nothing, "flat_start"
    distances = [
        hypot(start.p13_vpp_kw - p13, start.p30_vpp_kw - p30)
        for start in feasible_starts
    ]
    selected = feasible_starts[argmin(distances)]
    source = @sprintf(
        "nearest_feasible_sample_%d_distance_%.6f_kw",
        selected.sample_id,
        minimum(distances),
    )
    return selected.voltage, source
end

function process_cpu_seconds()
    ticks = Float64(ccall(:clock, Clong, ()))
    ticks_per_second = Sys.iswindows() ? 1_000.0 : 1_000_000.0
    return ticks / ticks_per_second
end

function csv_value(value)
    if value isa AbstractString
        escaped = replace(value, "\"" => "\"\"")
        return occursin(r"[,\"]", escaped) ? "\"$escaped\"" : escaped
    elseif value isa Float64
        return isfinite(value) ? @sprintf("%.12g", value) : string(value)
    end
    return string(value)
end

function write_namedtuple_csv(path::AbstractString, columns, rows)
    open(path, "w") do io
        println(io, join(string.(columns), ','))
        for row in rows
            println(io, join((csv_value(getproperty(row, column)) for column in columns), ','))
        end
    end
    return path
end

function benchmark_columns()
    return (
        :sample_id,
        :timestamp,
        :p13_vpp_kw,
        :p30_vpp_kw,
        :q13_vpp_kvar,
        :q30_vpp_kvar,
        :classification,
        :solver_status,
        :replay_status,
        :maximum_absolute_residual,
        :maximum_scaled_residual,
        :minimum_voltage_pu,
        :minimum_voltage_bus,
        :maximum_voltage_pu,
        :maximum_voltage_bus,
        :substation_p_kw,
        :substation_q_kvar,
        :active_losses_kw,
        :reactive_losses_kvar,
        :warm_start_source,
        :runtime_seconds,
        :solver_iterations,
        :replay_iterations,
        :primary_replay_max_voltage_difference_pu,
        :primary_voltage_equation_residual_pu,
    )
end

function evaluate_benchmark(network, profile, indices; count::Integer=SAMPLE_COUNT)
    plan = sample_plan(indices; count=count)
    feasible_starts = Dict(index => NamedTuple[] for index in indices)
    output_rows = NamedTuple[]
    warmup_index = first(indices)
    evaluate_point(network, profile, warmup_index, 0.0, 0.0)
    GC.gc()
    cpu_start = process_cpu_seconds()
    wall_start_ns = time_ns()
    for point in plan
        candidates = feasible_starts[point.profile_index]
        initial_voltage, warm_source = nearest_feasible_start(
            candidates,
            point.p13_vpp_kw,
            point.p30_vpp_kw,
        )
        evaluated = evaluate_point(
            network,
            profile,
            point.profile_index,
            point.p13_vpp_kw,
            point.p30_vpp_kw;
            initial_voltage=initial_voltage,
            warm_start_source=warm_source,
        )
        row = merge((sample_id=point.sample_id,), Base.structdiff(
            evaluated,
            NamedTuple{(:primary_voltage_complex_pu,)}((
                evaluated.primary_voltage_complex_pu,
            )),
        ))
        push!(output_rows, row)
        if evaluated.classification == "FEASIBLE"
            push!(candidates, (
                sample_id=point.sample_id,
                p13_vpp_kw=point.p13_vpp_kw,
                p30_vpp_kw=point.p30_vpp_kw,
                voltage=evaluated.primary_voltage_complex_pu,
            ))
        end
    end
    wall_seconds = (time_ns() - wall_start_ns) / 1e9
    cpu_seconds = process_cpu_seconds() - cpu_start
    return output_rows, wall_seconds, cpu_seconds
end

function read_authoritative_plan(path::AbstractString, profile, indices)
    isfile(path) || throw(ArgumentError("authoritative Stage-0 points file is missing: $path"))
    timestamp_to_index = Dict(
        Dates.format(profile.timestamps[index], dateformat"yyyy-mm-dd HH:MM:SS") => index
        for index in indices
    )
    rows = NamedTuple[]
    open(path, "r") do io
        eof(io) && throw(ArgumentError("authoritative Stage-0 points file is empty"))
        header = split(chomp(readline(io)), ',')
        required = ("sample_id", "timestamp", "p13_vpp_kw", "p30_vpp_kw")
        column = Dict(name => findfirst(==(name), header) for name in required)
        all(!isnothing, values(column)) ||
            throw(ArgumentError("authoritative Stage-0 points file is missing required columns"))
        for line in eachline(io)
            fields = split(line, ',')
            length(fields) == length(header) ||
                throw(ArgumentError("authoritative Stage-0 points column mismatch"))
            timestamp = fields[column["timestamp"]]
            haskey(timestamp_to_index, timestamp) ||
                throw(ArgumentError("authoritative point timestamp is outside the pilot window"))
            push!(rows, (
                sample_id=parse(Int, fields[column["sample_id"]]),
                profile_index=timestamp_to_index[timestamp],
                timestamp=timestamp,
                p13_vpp_kw=parse(Float64, fields[column["p13_vpp_kw"]]),
                p30_vpp_kw=parse(Float64, fields[column["p30_vpp_kw"]]),
            ))
        end
    end
    length(rows) == SAMPLE_COUNT ||
        throw(ArgumentError("authoritative Stage-0 plan must contain $SAMPLE_COUNT points"))
    [row.sample_id for row in rows] == collect(1:SAMPLE_COUNT) ||
        throw(ArgumentError("authoritative Stage-0 point ids are not exactly 1:$SAMPLE_COUNT"))
    return rows
end

function corrected_benchmark_columns()
    return (
        :point_id,
        :timestamp,
        :H_kW,
        :pv_factor,
        :actual_PV_kW,
        :P13_VPP_kW,
        :P30_VPP_kW,
        :total_P_load_kW,
        :total_Q_load_kvar,
        :P_sub_kW,
        :Q_sub_kvar,
        :active_loss_kW,
        :reactive_loss_kvar,
        :Vmin_pu,
        :Vmin_bus,
        :Vmax_pu,
        :Vmax_bus,
        :power_flow_status,
        :voltage_status,
        :legacy_label,
        :replay_status,
        :maximum_residual,
        :maximum_scaled_residual,
        :iterations,
        :replay_iterations,
        :warm_start_source,
        :assembly_ms,
        :primary_power_flow_ms,
        :replay_ms,
        :residual_audit_ms,
        :classification_ms,
        :bookkeeping_ms,
        :total_evaluation_ms,
        :elapsed_ms,
        :allocated_bytes,
        :gc_time_ms,
    )
end

function evaluate_corrected_benchmark(
    network,
    profile,
    plan;
    reference_pv_capacity_kw::Real=REFERENCE_PV_CAPACITY_KW,
)
    feasible_starts = Dict(
        index => NamedTuple[] for index in unique(point.profile_index for point in plan)
    )
    warmup = evaluate_point(
        network,
        profile,
        first(plan).profile_index,
        0.0,
        0.0;
        reference_pv_capacity_kw=reference_pv_capacity_kw,
    )
    evaluate_point(
        network,
        profile,
        first(plan).profile_index,
        0.0,
        0.0;
        reference_pv_capacity_kw=reference_pv_capacity_kw,
        initial_voltage=warmup.primary_voltage_complex_pu,
        warm_start_source="timing_specialization_warmup",
    )
    GC.gc()
    output_rows = NamedTuple[]
    cpu_start = process_cpu_seconds()
    wall_start_ns = time_ns()
    for point in plan
        candidates = feasible_starts[point.profile_index]
        initial_voltage, warm_source = nearest_feasible_start(
            candidates,
            point.p13_vpp_kw,
            point.p30_vpp_kw,
        )
        timed = @timed evaluate_point(
            network,
            profile,
            point.profile_index,
            point.p13_vpp_kw,
            point.p30_vpp_kw;
            reference_pv_capacity_kw=reference_pv_capacity_kw,
            initial_voltage=initial_voltage,
            warm_start_source=warm_source,
        )
        evaluated = timed.value
        row = (
            point_id=point.sample_id,
            timestamp=evaluated.timestamp,
            H_kW=evaluated.reference_pv_capacity_kw,
            pv_factor=evaluated.pv_factor,
            actual_PV_kW=evaluated.actual_reference_pv_kw,
            P13_VPP_kW=evaluated.p13_vpp_kw,
            P30_VPP_kW=evaluated.p30_vpp_kw,
            total_P_load_kW=evaluated.total_p_load_kw,
            total_Q_load_kvar=evaluated.total_q_load_kvar,
            P_sub_kW=evaluated.substation_p_kw,
            Q_sub_kvar=evaluated.substation_q_kvar,
            active_loss_kW=evaluated.active_losses_kw,
            reactive_loss_kvar=evaluated.reactive_losses_kvar,
            Vmin_pu=evaluated.minimum_voltage_pu,
            Vmin_bus=evaluated.minimum_voltage_bus,
            Vmax_pu=evaluated.maximum_voltage_pu,
            Vmax_bus=evaluated.maximum_voltage_bus,
            power_flow_status=evaluated.power_flow_status,
            voltage_status=evaluated.voltage_status,
            legacy_label=evaluated.legacy_label,
            replay_status=evaluated.replay_status,
            maximum_residual=evaluated.maximum_absolute_residual,
            maximum_scaled_residual=evaluated.maximum_scaled_residual,
            iterations=evaluated.solver_iterations,
            replay_iterations=evaluated.replay_iterations,
            warm_start_source=evaluated.warm_start_source,
            assembly_ms=evaluated.assembly_ms,
            primary_power_flow_ms=evaluated.primary_power_flow_ms,
            replay_ms=evaluated.replay_ms,
            residual_audit_ms=evaluated.residual_audit_ms,
            classification_ms=evaluated.classification_ms,
            bookkeeping_ms=evaluated.bookkeeping_ms,
            total_evaluation_ms=evaluated.total_evaluation_ms,
            elapsed_ms=evaluated.total_evaluation_ms,
            allocated_bytes=timed.bytes,
            gc_time_ms=1000.0 * timed.gctime,
        )
        push!(output_rows, row)
        if evaluated.legacy_label == "FEASIBLE"
            push!(candidates, (
                sample_id=point.sample_id,
                p13_vpp_kw=point.p13_vpp_kw,
                p30_vpp_kw=point.p30_vpp_kw,
                voltage=evaluated.primary_voltage_complex_pu,
            ))
        end
    end
    wall_seconds = (time_ns() - wall_start_ns) / 1e9
    cpu_seconds = process_cpu_seconds() - cpu_start
    return output_rows, wall_seconds, cpu_seconds
end

function write_data_audit(output_directory, profile, indices)
    interpretation = "timezone-naive local wall-clock labels; no UTC conversion; fixed 48 source slots per local-data day; DST behavior inherited from Ausgrid source format"
    row = (
        start_timestamp=Dates.format(
            profile.timestamps[first(indices)],
            dateformat"yyyy-mm-dd HH:MM:SS",
        ),
        end_timestamp=Dates.format(
            profile.timestamps[last(indices)],
            dateformat"yyyy-mm-dd HH:MM:SS",
        ),
        interval_count=length(indices),
        unique_interval_count=length(unique(profile.timestamps[indices])),
        missing_interval_count=count(!=(Minute(30)), diff(profile.timestamps[indices])),
        finite_load_factors=all(isfinite, profile.load_multiplier[indices]),
        finite_pv_factors=all(isfinite, profile.pv_profile[indices]),
        minimum_load_factor=minimum(profile.load_multiplier[indices]),
        maximum_load_factor=maximum(profile.load_multiplier[indices]),
        minimum_pv_factor=minimum(profile.pv_profile[indices]),
        maximum_pv_factor=maximum(profile.pv_profile[indices]),
        timestamp_interpretation=interpretation,
        source_path=profile.source_path,
        source_sha256=profile.source_sha256,
    )
    columns = propertynames(row)
    path = joinpath(output_directory, "stage0_data_audit.csv")
    write_namedtuple_csv(path, columns, [row])
    return path, row
end

function sample_quantile(values::AbstractVector{<:Real}, probability::Real)
    isempty(values) && throw(ArgumentError("quantile input must not be empty"))
    0.0 <= probability <= 1.0 ||
        throw(ArgumentError("quantile probability must lie in [0, 1]"))
    ordered = sort(Float64.(values))
    position = 1.0 + (length(ordered) - 1) * Float64(probability)
    lower = floor(Int, position)
    upper = ceil(Int, position)
    lower == upper && return ordered[lower]
    weight = position - lower
    return (1.0 - weight) * ordered[lower] + weight * ordered[upper]
end

function timing_summary(rows, wall_seconds, cpu_seconds, points_path)
    runtimes = [row.runtime_seconds for row in rows]
    counts = Dict(
        label => count(row -> row.classification == label, rows)
        for label in ("FEASIBLE", "INFEASIBLE_VOLTAGE", "UNKNOWN_SOLVER")
    )
    file_bytes = filesize(points_path)
    header_bytes = length(readline(points_path)) + 2
    mean_row_bytes = (file_bytes - header_bytes) / length(rows)
    coarse_count = 96 * 15 * 15
    dense_count = 96 * 50 * 50
    seconds_per_evaluation = wall_seconds / length(rows)
    average_cores = cpu_seconds / wall_seconds
    return (
        benchmark_evaluations=length(rows),
        benchmark_wall_seconds=wall_seconds,
        median_solve_seconds=sample_quantile(runtimes, 0.50),
        p90_solve_seconds=sample_quantile(runtimes, 0.90),
        maximum_solve_seconds=maximum(runtimes),
        converged_count=count(row -> row.solver_status == "CONVERGED", rows),
        replay_passed_count=count(row -> row.replay_status == "PASSED", rows),
        feasible_count=counts["FEASIBLE"],
        infeasible_voltage_count=counts["INFEASIBLE_VOLTAGE"],
        unknown_solver_count=counts["UNKNOWN_SOLVER"],
        peak_rss_bytes=Sys.maxrss(),
        process_cpu_seconds=cpu_seconds,
        average_process_cores=average_cores,
        cpu_utilization_percent_of_logical_capacity=
            100.0 * average_cores / Sys.CPU_THREADS,
        logical_cpu_count=Sys.CPU_THREADS,
        total_physical_memory_bytes=Sys.total_memory(),
        estimated_21600_wall_seconds=seconds_per_evaluation * coarse_count,
        estimated_240000_wall_seconds=seconds_per_evaluation * dense_count,
        measured_points_file_bytes=file_bytes,
        estimated_mean_raw_row_bytes=mean_row_bytes,
        estimated_21600_raw_bytes=header_bytes + mean_row_bytes * coarse_count,
        estimated_240000_raw_bytes=header_bytes + mean_row_bytes * dense_count,
        parallelization_assessment="safe after serial module initialization; evaluations use immutable feeder inputs and per-call state; merge outputs in deterministic sample order",
    )
end

function write_readme(output_directory, audit, timing)
    path = joinpath(output_directory, "README.md")
    open(path, "w") do io
        println(io, "# DSO-VPP sampled AC voltage-feasible injection map: Stage 0")
        println(io)
        println(io, "This directory contains only the audit and 1,000-evaluation timing pilot.")
        println(io, "The complete 96-interval map has not been launched.")
        println(io)
        println(io, "## Scope and authority")
        println(io)
        println(io, "- Boundary variables are direct active-power injections at buses 13 and 30.")
        println(io, "- Positive values inject into the network; negative values consume from it.")
        println(io, "- Controllable reactive power is zero at both VPP connection points.")
        println(io, "- The primary calculation is the repository's exact radial backward/forward AC solve.")
        println(io, "- Every point is separately replayed with `replay_s1b_interval` and its branch-flow residual audit.")
        println(io, "- The voltage band is 0.90-1.05 p.u., root voltage is 1.00 p.u., base power is 10 MVA, and base voltage is 12.66 kV.")
        println(io, "- Upstream exchange is unconstrained. No thermal or transformer limit is applied.")
        println(io)
        println(io, "## Timestamp audit")
        println(io)
        println(io, "- Interval count: $(audit.interval_count); unique intervals: $(audit.unique_interval_count); missing intervals: $(audit.missing_interval_count).")
        println(io, "- Window: $(audit.start_timestamp) through $(audit.end_timestamp).")
        println(io, "- Interpretation: $(audit.timestamp_interpretation).")
        println(io, "- Load and PV factors are finite: $(audit.finite_load_factors && audit.finite_pv_factors).")
        println(io)
        println(io, "## Benchmark")
        println(io)
        @printf(io, "- Wall time for %d evaluations: %.6f s.\n", timing.benchmark_evaluations, timing.benchmark_wall_seconds)
        @printf(io, "- Per-point solve time: median %.6g s, p90 %.6g s, maximum %.6g s.\n", timing.median_solve_seconds, timing.p90_solve_seconds, timing.maximum_solve_seconds)
        println(io, "- Counts: FEASIBLE=$(timing.feasible_count), INFEASIBLE_VOLTAGE=$(timing.infeasible_voltage_count), UNKNOWN_SOLVER=$(timing.unknown_solver_count).")
        @printf(io, "- Peak process RSS: %.3f MiB.\n", timing.peak_rss_bytes / 2.0^20)
        @printf(io, "- Average CPU: %.3f logical cores (%.2f%% of %d-core logical capacity).\n", timing.average_process_cores, timing.cpu_utilization_percent_of_logical_capacity, timing.logical_cpu_count)
        @printf(io, "- Linear estimate for 21,600 evaluations: %.3f s; raw table %.3f MiB.\n", timing.estimated_21600_wall_seconds, timing.estimated_21600_raw_bytes / 2.0^20)
        @printf(io, "- Linear estimate for 240,000 evaluations: %.3f s; raw table %.3f MiB.\n", timing.estimated_240000_wall_seconds, timing.estimated_240000_raw_bytes / 2.0^20)
        println(io)
        println(io, "The timing estimates are linear extrapolations from this Stage-0 sample and exclude plotting and adaptive-bound discovery.")
        println(io, "No complete map or refinement was run. Explicit user approval is required before Stage 1.")
    end
    return path
end

function read_csv_dicts(path::AbstractString)
    open(path, "r") do io
        eof(io) && throw(ArgumentError("CSV is empty: $path"))
        header = split(chomp(readline(io)), ',')
        rows = Dict{String,String}[]
        for line in eachline(io)
            fields = split(line, ',')
            length(fields) == length(header) ||
                throw(ArgumentError("CSV column mismatch in $path"))
            push!(rows, Dict(header .=> fields))
        end
        return rows
    end
end

function voltage_status_from_values(power_flow_status, vmin, vmax)
    power_flow_status == "CONVERGED" || return "NOT_EVALUATED"
    lower = vmin < VMIN_PU
    upper = vmax > VMAX_PU
    lower && upper && return "BOTH_LIMITS_VIOLATED"
    lower && return "LOWER_VOLTAGE_VIOLATION"
    upper && return "UPPER_VOLTAGE_VIOLATION"
    return "WITHIN_LIMITS"
end

function corrected_timing_summary(rows, wall_seconds, cpu_seconds)
    phase_values(field) = [getproperty(row, field) for row in rows]
    phase_summary(field) = (
        sample_quantile(phase_values(field), 0.50),
        sample_quantile(phase_values(field), 0.90),
        maximum(phase_values(field)),
    )
    assembly = phase_summary(:assembly_ms)
    primary = phase_summary(:primary_power_flow_ms)
    replay = phase_summary(:replay_ms)
    residual = phase_summary(:residual_audit_ms)
    classification = phase_summary(:classification_ms)
    bookkeeping = phase_summary(:bookkeeping_ms)
    total = phase_summary(:total_evaluation_ms)
    maximum_index = argmax(phase_values(:total_evaluation_ms))
    maximum_row = rows[maximum_index]
    return (
        timing_scope="assembly + primary AC solve + independent replay + residual audit + classification + evaluator bookkeeping; excludes CSV row construction and file I/O",
        warmup_policy="one flat-start evaluation plus one warm-start evaluation before GC and measurement",
        allocation_scope="outer @timed evaluate_point call; excludes corrected CSV row construction and file I/O",
        benchmark_evaluations=length(rows),
        benchmark_wall_seconds=wall_seconds,
        median_assembly_ms=assembly[1],
        p90_assembly_ms=assembly[2],
        maximum_assembly_ms=assembly[3],
        median_primary_power_flow_ms=primary[1],
        p90_primary_power_flow_ms=primary[2],
        maximum_primary_power_flow_ms=primary[3],
        median_replay_ms=replay[1],
        p90_replay_ms=replay[2],
        maximum_replay_ms=replay[3],
        median_residual_audit_ms=residual[1],
        p90_residual_audit_ms=residual[2],
        maximum_residual_audit_ms=residual[3],
        median_classification_ms=classification[1],
        p90_classification_ms=classification[2],
        maximum_classification_ms=classification[3],
        median_bookkeeping_ms=bookkeeping[1],
        p90_bookkeeping_ms=bookkeeping[2],
        maximum_bookkeeping_ms=bookkeeping[3],
        median_total_evaluation_ms=total[1],
        p90_total_evaluation_ms=total[2],
        maximum_total_evaluation_ms=total[3],
        median_elapsed_ms=total[1],
        p90_elapsed_ms=total[2],
        maximum_elapsed_ms=total[3],
        maximum_elapsed_point_id=maximum_row.point_id,
        maximum_elapsed_timestamp=maximum_row.timestamp,
        converged_count=count(row -> row.power_flow_status == "CONVERGED", rows),
        unresolved_count=count(row -> row.power_flow_status != "CONVERGED", rows),
        within_limits_count=count(row -> row.voltage_status == "WITHIN_LIMITS", rows),
        upper_voltage_violation_count=count(
            row -> row.voltage_status == "UPPER_VOLTAGE_VIOLATION", rows,
        ),
        lower_voltage_violation_count=count(
            row -> row.voltage_status == "LOWER_VOLTAGE_VIOLATION", rows,
        ),
        both_limits_violated_count=count(
            row -> row.voltage_status == "BOTH_LIMITS_VIOLATED", rows,
        ),
        replay_passed_count=count(row -> row.replay_status == "PASSED", rows),
        maximum_replay_residual=maximum(row.maximum_residual for row in rows),
        total_allocated_bytes=sum(row.allocated_bytes for row in rows),
        maximum_allocated_bytes=maximum(row.allocated_bytes for row in rows),
        total_gc_time_ms=sum(row.gc_time_ms for row in rows),
        maximum_gc_time_ms=maximum(row.gc_time_ms for row in rows),
        peak_rss_bytes=Sys.maxrss(),
        process_cpu_seconds=cpu_seconds,
        average_process_cores=cpu_seconds / wall_seconds,
    )
end

function write_corrected_data_audit(
    output_directory,
    profile,
    indices,
    authoritative_points_path,
)
    row = (
        start_timestamp=Dates.format(
            profile.timestamps[first(indices)], dateformat"yyyy-mm-dd HH:MM:SS",
        ),
        end_timestamp=Dates.format(
            profile.timestamps[last(indices)], dateformat"yyyy-mm-dd HH:MM:SS",
        ),
        interval_count=length(indices),
        unique_interval_count=length(unique(profile.timestamps[indices])),
        missing_interval_count=count(!=(Minute(30)), diff(profile.timestamps[indices])),
        reference_pv_bus=REFERENCE_PV_BUS,
        reference_pv_capacity_kW=REFERENCE_PV_CAPACITY_KW,
        reference_pv_formula="H_kW * canonical pv_factor",
        vpp_p13_formula="independent additive active injection at bus 13",
        vpp_p30_formula="independent additive active injection at bus 30",
        source_path=profile.source_path,
        source_sha256=profile.source_sha256,
        authoritative_points_path=abspath(authoritative_points_path),
        authoritative_points_sha256=bytes2hex(open(SHA.sha256, authoritative_points_path)),
    )
    path = joinpath(output_directory, "stage0_data_audit_corrected.csv")
    write_namedtuple_csv(path, propertynames(row), [row])
    return path, row
end

function write_corrected_pv_presence_check(output_directory, network, profile, indices)
    profile_index = indices[argmax(profile.pv_profile[indices])]
    cases = [
        evaluate_point(
            network, profile, profile_index, 0.0, 0.0;
            reference_pv_capacity_kw=capacity,
        )
        for capacity in (REFERENCE_PV_CAPACITY_KW, 0.0)
    ]
    with_pv, without_pv = cases
    expected_pv_kw = REFERENCE_PV_CAPACITY_KW * profile.pv_profile[profile_index]
    delta_p_sub_kw = without_pv.substation_p_kw - with_pv.substation_p_kw
    delta_p_loss_kw = with_pv.active_losses_kw - without_pv.active_losses_kw
    balance_tolerance_kw = RESIDUAL_TOLERANCE_PU * BASE_KW
    nonzero_assertion = expected_pv_kw > 1e-9
    balance_assertion =
        abs(delta_p_sub_kw + delta_p_loss_kw - expected_pv_kw) <= balance_tolerance_kw
    response_assertion = abs(delta_p_sub_kw) > 0.5 * expected_pv_kw
    actual_pv_assertion = isapprox(
        with_pv.actual_reference_pv_kw,
        expected_pv_kw;
        atol=1e-10,
        rtol=1e-12,
    )
    all((nonzero_assertion, balance_assertion, response_assertion, actual_pv_assertion)) ||
        error("corrected fixed-PV presence assertions failed")
    rows = [
        (
            timestamp=case.timestamp,
            H_kW=case.reference_pv_capacity_kw,
            pv_factor=case.pv_factor,
            actual_PV_kW=case.actual_reference_pv_kw,
            total_P_load_kW=case.total_p_load_kw,
            total_Q_load_kvar=case.total_q_load_kvar,
            P_sub_kW=case.substation_p_kw,
            Q_sub_kvar=case.substation_q_kvar,
            total_active_loss_kW=case.active_losses_kw,
            total_reactive_loss_kvar=case.reactive_losses_kvar,
            V_bus13_pu=abs(case.primary_voltage_complex_pu[13]),
            V_bus20_pu=abs(case.primary_voltage_complex_pu[20]),
            V_max_pu=case.maximum_voltage_pu,
            V_max_bus=case.maximum_voltage_bus,
            power_flow_status=case.power_flow_status,
            voltage_status=case.voltage_status,
            replay_status=case.replay_status,
            maximum_residual=case.maximum_absolute_residual,
            expected_PV_kW=expected_pv_kw,
            delta_P_sub_kW=delta_p_sub_kw,
            delta_P_loss_kW=delta_p_loss_kw,
            balance_tolerance_kW=balance_tolerance_kw,
            nonzero_assertion=nonzero_assertion,
            balance_assertion=balance_assertion,
            response_assertion=response_assertion,
            actual_pv_assertion=actual_pv_assertion,
        )
        for case in cases
    ]
    path = joinpath(output_directory, "stage0_pv_presence_check_corrected.csv")
    write_namedtuple_csv(path, propertynames(first(rows)), rows)
    return path, rows
end

function write_before_after_comparison(output_directory, old_points_path, new_rows)
    old_rows = read_csv_dicts(old_points_path)
    length(old_rows) == length(new_rows) ||
        error("old/new Stage-0 row-count mismatch")
    comparison = NamedTuple[]
    for (old, new) in zip(old_rows, new_rows)
        point_id = parse(Int, old["sample_id"])
        point_id == new.point_id || error("old/new Stage-0 point-id mismatch")
        old_power_flow_status = old["solver_status"]
        old_vmin = parse(Float64, old["minimum_voltage_pu"])
        old_vmax = parse(Float64, old["maximum_voltage_pu"])
        old_voltage_status = voltage_status_from_values(
            old_power_flow_status, old_vmin, old_vmax,
        )
        old_p_sub = parse(Float64, old["substation_p_kw"])
        push!(comparison, (
            point_id=point_id,
            timestamp=old["timestamp"],
            P13_VPP_kW=parse(Float64, old["p13_vpp_kw"]),
            P30_VPP_kW=parse(Float64, old["p30_vpp_kw"]),
            old_actual_PV_kW=0.0,
            new_actual_PV_kW=new.actual_PV_kW,
            old_power_flow_status=old_power_flow_status,
            new_power_flow_status=new.power_flow_status,
            old_voltage_status=old_voltage_status,
            new_voltage_status=new.voltage_status,
            old_Vmin_pu=old_vmin,
            new_Vmin_pu=new.Vmin_pu,
            old_Vmax_pu=old_vmax,
            new_Vmax_pu=new.Vmax_pu,
            delta_Vmin_pu=new.Vmin_pu - old_vmin,
            delta_Vmax_pu=new.Vmax_pu - old_vmax,
            old_P_sub_kW=old_p_sub,
            new_P_sub_kW=new.P_sub_kW,
            delta_P_sub_kW=new.P_sub_kW - old_p_sub,
            label_changed=old_voltage_status != new.voltage_status,
        ))
    end
    path = joinpath(output_directory, "stage0_before_after_comparison.csv")
    write_namedtuple_csv(path, propertynames(first(comparison)), comparison)
    return path, comparison
end

function run_stage0(
    repository_root::AbstractString;
    authoritative_points_path::Union{Nothing,AbstractString}=nothing,
)
    profile = load_profile(repository_root)
    indices = select_pilot_indices(profile)
    network = build_pilot_network()
    output_directory = joinpath(repository_root, "results", "dso_vpp_ac_map_pilot")
    mkpath(output_directory)
    points_source = authoritative_points_path === nothing ?
                    joinpath(output_directory, "stage0_benchmark_points.csv") :
                    String(authoritative_points_path)
    plan = read_authoritative_plan(points_source, profile, indices)
    audit_path, audit = write_corrected_data_audit(
        output_directory, profile, indices, points_source,
    )
    rows, wall_seconds, cpu_seconds = evaluate_corrected_benchmark(
        network, profile, plan;
        reference_pv_capacity_kw=REFERENCE_PV_CAPACITY_KW,
    )
    points_path = joinpath(output_directory, "stage0_benchmark_points_corrected.csv")
    write_namedtuple_csv(points_path, corrected_benchmark_columns(), rows)
    timing = corrected_timing_summary(rows, wall_seconds, cpu_seconds)
    timing_path = joinpath(output_directory, "timing_benchmark_corrected.csv")
    write_namedtuple_csv(timing_path, propertynames(timing), [timing])
    pv_presence_path, _ = write_corrected_pv_presence_check(
        output_directory, network, profile, indices,
    )
    comparison_path, comparison = write_before_after_comparison(
        output_directory, points_source, rows,
    )
    written_lines = readlines(points_path)
    length(written_lines) == SAMPLE_COUNT + 1 ||
        error("written corrected benchmark row count mismatch")
    header = split(first(written_lines), ',')
    voltage_index = findfirst(==("voltage_status"), header)
    voltage_index === nothing &&
        error("written corrected benchmark voltage_status column is missing")
    written_voltage_statuses = [
        split(line, ',')[voltage_index] for line in Iterators.drop(written_lines, 1)
    ]
    count(==("WITHIN_LIMITS"), written_voltage_statuses) == timing.within_limits_count ||
        error("written/in-memory WITHIN_LIMITS counts disagree")
    count(identity, [row.label_changed for row in comparison]) ==
        count(line -> endswith(line, ",true"), readlines(comparison_path)[2:end]) ||
        error("written/in-memory label-change counts disagree")
    return (
        output_directory=output_directory,
        audit_path=audit_path,
        points_path=points_path,
        timing_path=timing_path,
        pv_presence_path=pv_presence_path,
        comparison_path=comparison_path,
        authoritative_points_path=abspath(points_source),
        timing=timing,
    )
end

end
