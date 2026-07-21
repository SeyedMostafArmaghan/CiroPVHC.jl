using JuMP
using Clarabel
using Dates
using Printf
using SHA

const _S0_ACCEPTED_SOLVER_STATUSES = Set(("OPTIMAL", "ALMOST_OPTIMAL"))
const _S0_STREAM_CHUNK_SIZE = 512

struct S0ParametricModel
    model::JuMP.Model
    network::SOCPNetworkVariables
    load_multiplier::JuMP.VariableRef
    data::CaseData
    root_voltage_pu::Float64
    operational_voltage_limits_enforced::Bool
    no_export_constraint_active::Bool
    loss_cap_constraint_active::Bool
end

struct S0StateResult
    load_multiplier::Float64
    operational_solver_status::String
    diagnostic_solver_status::String
    solution_source::String
    primal_available::Bool
    numerical_validation_passed::Bool
    failure_reason::String
    operational_voltage_feasible::Bool
    total_active_load_kw::Float64
    total_reactive_load_kvar::Float64
    voltages_pu::Vector{Float64}
    minimum_voltage_pu::Float64
    minimum_voltage_bus::Int
    maximum_voltage_pu::Float64
    maximum_voltage_bus::Int
    undervoltage_bus_count::Int
    overvoltage_bus_count::Int
    branch_active_power_pu::Vector{Float64}
    branch_reactive_power_pu::Vector{Float64}
    branch_ell_pu2::Vector{Float64}
    branch_soc_gap_pu2::Vector{Float64}
    branch_current_a::Vector{Float64}
    branch_receiving_active_power_pu::Vector{Float64}
    branch_receiving_reactive_power_pu::Vector{Float64}
    substation_active_power_kw::Float64
    substation_reactive_power_kvar::Float64
    substation_apparent_power_kva::Float64
    substation_direction::String
    active_losses_kw::Float64
    reactive_losses_kvar::Float64
    active_loss_percentage::Float64
    maximum_ell_pu2::Float64
    maximum_current_branch_id::Int
    maximum_current_a::Float64
    maximum_soc_gap_pu2::Float64
    minimum_soc_gap_pu2::Float64
    maximum_active_balance_residual_kw::Float64
    maximum_reactive_balance_residual_kvar::Float64
    maximum_voltage_drop_residual_pu2::Float64
    root_voltage_residual_pu2::Float64
    substation_active_balance_residual_kw::Float64
    substation_reactive_balance_residual_kvar::Float64
end

function _s0_sha256(path::AbstractString)
    return bytes2hex(open(SHA.sha256, path))
end

function _read_ausgrid_s0_load_profile(
    path::AbstractString;
    expected_intervals::Integer=52_608,
    expected_dt_hours::Real=0.5,
)
    isfile(path) || throw(ArgumentError("Ausgrid input file does not exist: $path"))
    timestamps = DateTime[]
    multipliers = Float64[]

    open(path, "r") do io
        eof(io) && throw(ArgumentError("Ausgrid input file is empty"))
        header = split(chomp(readline(io)), ',')
        timestamp_index = findfirst(==("datetime"), header)
        multiplier_index = findfirst(==("load_multiplier"), header)
        timestamp_index === nothing && throw(ArgumentError("Ausgrid input is missing datetime"))
        multiplier_index === nothing && throw(ArgumentError("Ausgrid input is missing load_multiplier"))

        for (row_number, line) in enumerate(eachline(io))
            isempty(line) && throw(ArgumentError("blank Ausgrid row at data row $row_number"))
            fields = split(line, ',')
            length(fields) == length(header) ||
                throw(ArgumentError("Ausgrid column-count mismatch at data row $row_number"))
            timestamp = try
                DateTime(fields[timestamp_index], dateformat"yyyy-mm-dd HH:MM:SS")
            catch
                throw(ArgumentError("invalid Ausgrid timestamp at data row $row_number: $(fields[timestamp_index])"))
            end
            multiplier = tryparse(Float64, fields[multiplier_index])
            multiplier === nothing &&
                throw(ArgumentError("invalid Ausgrid load multiplier at data row $row_number"))
            isfinite(multiplier) || throw(ArgumentError("non-finite Ausgrid load multiplier at data row $row_number"))
            multiplier >= 0.0 || throw(ArgumentError("negative Ausgrid load multiplier at data row $row_number"))
            push!(timestamps, timestamp)
            push!(multipliers, multiplier)
        end
    end

    length(timestamps) == expected_intervals || throw(ArgumentError(
        "Ausgrid interval count mismatch: expected $expected_intervals, found $(length(timestamps))",
    ))
    length(unique(timestamps)) == length(timestamps) ||
        throw(ArgumentError("Ausgrid timestamps contain duplicates"))
    issorted(timestamps) || throw(ArgumentError("Ausgrid timestamps are not monotonic"))
    expected_step = Millisecond(round(Int, Float64(expected_dt_hours) * 3_600_000))
    all(diff(timestamps) .== expected_step) ||
        throw(ArgumentError("Ausgrid timestamps are not uniformly spaced by $(expected_dt_hours) h"))

    return S0LoadProfile(
        timestamps,
        multipliers,
        Float64(expected_dt_hours),
        abspath(path),
        _s0_sha256(path),
    )
end

function _s0_case_data(config::S0BaselineConfig, vmin_pu::Float64, vmax_pu::Float64)
    buses, branches = build_ieee33_network()
    timeseries = TimeSeries(1, config.dt_hours, [0.0], [0.0], [0.0], [0.0])
    data = CaseData(
        buses,
        branches,
        PVUnit[],
        EVCS[],
        BESS[],
        nothing,
        timeseries,
        10.0,
        vmin_pu,
        vmax_pu,
    )
    check_data_consistency(data)
    return data
end

function _build_s0_baseline_model(
    root_voltage_pu::Real;
    config::S0BaselineConfig=S0BaselineConfig(),
    enforce_operational_voltage_limits::Bool=true,
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
)
    root_voltage = Float64(root_voltage_pu)
    root_voltage in config.root_voltages_pu ||
        throw(ArgumentError("root voltage $root_voltage is not configured for S0"))
    vmin = enforce_operational_voltage_limits ? config.vmin_pu : config.diagnostic_vmin_pu
    vmax = enforce_operational_voltage_limits ? config.vmax_pu : config.diagnostic_vmax_pu
    data = _s0_case_data(config, vmin, vmax)

    model = JuMP.Model(optimizer)
    silent && JuMP.set_silent(model)
    for (attribute, value) in (
        ("tol_gap_abs", 1e-9),
        ("tol_gap_rel", 1e-9),
        ("tol_feas", 1e-9),
        ("reduced_tol_gap_abs", 1e-6),
        ("reduced_tol_gap_rel", 1e-6),
        ("reduced_tol_feas", 1e-6),
        ("reduced_tol_infeas_rel", 1e-6),
        ("reduced_tol_ktratio", 1e-6),
        ("max_iter", 300),
    )
        JuMP.set_optimizer_attribute(model, attribute, value)
    end
    @variable(model, load_multiplier >= 0.0, base_name="s0_load_multiplier")
    JuMP.fix(load_multiplier, 0.0; force=true)
    zero_injection = Dict(
        bus.id => [JuMP.AffExpr(0.0)]
        for bus in data.buses
    )
    network = add_socp_branch_flow_constraints!(
        model,
        data,
        zero_injection;
        root_bus=1,
        root_voltage_pu=root_voltage,
        load_multiplier_by_time=[load_multiplier],
    )
    @objective(
        model,
        Min,
        sum(network.r_pu[branch_id] * network.ell[branch_id, 1] for branch_id in network.topology.branch_ids),
    )

    return S0ParametricModel(
        model,
        network,
        load_multiplier,
        data,
        root_voltage,
        enforce_operational_voltage_limits,
        false,
        false,
    )
end

function _s0_optimize_state!(bundle::S0ParametricModel, multiplier::Float64)
    JuMP.fix(bundle.load_multiplier, multiplier; force=true)
    JuMP.optimize!(bundle.model)
    status = string(JuMP.termination_status(bundle.model))
    primal_available = status in _S0_ACCEPTED_SOLVER_STATUSES && JuMP.has_values(bundle.model)
    return status, primal_available
end

function _s0_extract_network_state(
    network::SOCPNetworkVariables,
    data::CaseData,
    root_voltage_pu::Float64,
    time_index::Int,
    multiplier::Float64,
    operational_status::String,
    diagnostic_status::String,
    solution_source::String,
    config::S0BaselineConfig,
)
    topology = network.topology
    bus_ids = sort(topology.bus_ids)
    branch_ids = sort(topology.branch_ids)
    bus_index = Dict(bus_id => index for (index, bus_id) in enumerate(bus_ids))
    branch_index = Dict(branch_id => index for (index, branch_id) in enumerate(branch_ids))
    bus_by_id = Dict(bus.id => bus for bus in data.buses)
    base_power_kw = data.base_mva * 1000.0

    voltage_sq = [JuMP.value(network.v[bus_id, time_index]) for bus_id in bus_ids]
    voltages = sqrt.(max.(0.0, voltage_sq))
    p_branch = [JuMP.value(network.Pij[branch_id, time_index]) for branch_id in branch_ids]
    q_branch = [JuMP.value(network.Qij[branch_id, time_index]) for branch_id in branch_ids]
    ell = [JuMP.value(network.ell[branch_id, time_index]) for branch_id in branch_ids]
    soc_gap = zeros(Float64, length(branch_ids))
    receiving_p = zeros(Float64, length(branch_ids))
    receiving_q = zeros(Float64, length(branch_ids))
    current_a = zeros(Float64, length(branch_ids))
    voltage_drop_residual = 0.0

    for branch_id in branch_ids
        index = branch_index[branch_id]
        from_bus = topology.from_bus[branch_id]
        to_bus = topology.to_bus[branch_id]
        from_v = voltage_sq[bus_index[from_bus]]
        p = p_branch[index]
        q = q_branch[index]
        l = ell[index]
        r = network.r_pu[branch_id]
        x = network.x_pu[branch_id]
        soc_gap[index] = from_v * l - p^2 - q^2
        receiving_p[index] = p - r * l
        receiving_q[index] = q - x * l
        base_kv = bus_by_id[from_bus].base_kv
        base_current_a = data.base_mva * 1e6 / (sqrt(3.0) * base_kv * 1e3)
        current_a[index] = sqrt(max(0.0, l)) * base_current_a
        expected_to_v = from_v - 2.0 * (r * p + x * q) + (r^2 + x^2) * l
        voltage_drop_residual = max(
            voltage_drop_residual,
            abs(voltage_sq[bus_index[to_bus]] - expected_to_v),
        )
    end

    maximum_p_residual_kw = 0.0
    maximum_q_residual_kvar = 0.0
    for bus_id in bus_ids
        bus_id == topology.root_bus && continue
        incoming = topology.incoming_branch[bus_id]
        incoming_index = branch_index[incoming]
        child_branches = topology.outgoing_branches[bus_id]
        child_p = sum(p_branch[branch_index[child]] for child in child_branches; init=0.0)
        child_q = sum(q_branch[branch_index[child]] for child in child_branches; init=0.0)
        bus = bus_by_id[bus_id]
        p_residual_pu = p_branch[incoming_index] - network.r_pu[incoming] * ell[incoming_index] -
                        child_p - bus.pd_kw * multiplier / base_power_kw
        q_residual_pu = q_branch[incoming_index] - network.x_pu[incoming] * ell[incoming_index] -
                        child_q - bus.qd_kvar * multiplier / base_power_kw
        maximum_p_residual_kw = max(maximum_p_residual_kw, abs(p_residual_pu) * base_power_kw)
        maximum_q_residual_kvar = max(maximum_q_residual_kvar, abs(q_residual_pu) * base_power_kw)
    end

    total_active_load_kw = sum(bus.pd_kw for bus in data.buses) * multiplier
    total_reactive_load_kvar = sum(bus.qd_kvar for bus in data.buses) * multiplier
    active_losses_kw = sum(network.r_pu[id] * ell[branch_index[id]] for id in branch_ids) * base_power_kw
    reactive_losses_kvar = sum(network.x_pu[id] * ell[branch_index[id]] for id in branch_ids) * base_power_kw
    root_outgoing = topology.outgoing_branches[topology.root_bus]
    p_sub = sum(p_branch[branch_index[id]] for id in root_outgoing; init=0.0) * base_power_kw
    q_sub = sum(q_branch[branch_index[id]] for id in root_outgoing; init=0.0) * base_power_kw
    s_sub = s0_apparent_power(p_sub, q_sub)
    p_sub_residual = p_sub - total_active_load_kw - active_losses_kw
    q_sub_residual = q_sub - total_reactive_load_kvar - reactive_losses_kvar
    loss_percentage = total_active_load_kw > 0.0 ? 100.0 * active_losses_kw / total_active_load_kw : 0.0
    min_voltage, min_index = findmin(voltages)
    max_voltage, max_index = findmax(voltages)
    violation_counts = s0_voltage_violation_counts(
        voltages,
        config.vmin_pu,
        config.vmax_pu;
        tolerance_pu=config.voltage_tolerance_pu,
    )
    max_ell, max_current_index = findmax(ell)
    maximum_soc_gap = maximum(soc_gap)
    minimum_soc_gap = minimum(soc_gap)
    root_residual = abs(voltage_sq[bus_index[topology.root_bus]] - root_voltage_pu^2)
    finite_values = all(isfinite, voltage_sq) && all(isfinite, p_branch) && all(isfinite, q_branch) &&
                    all(isfinite, ell) && all(isfinite, soc_gap) && isfinite(p_sub) && isfinite(q_sub)

    reasons = String[]
    finite_values || push!(reasons, "nonfinite_solution_value")
    minimum(ell) >= -config.ell_tolerance_pu2 || push!(reasons, "negative_ell")
    maximum(abs, soc_gap) <= config.soc_gap_tolerance_pu2 || push!(reasons, "soc_gap_tolerance_exceeded")
    maximum_p_residual_kw <= config.balance_tolerance_kw || push!(reasons, "active_balance_tolerance_exceeded")
    maximum_q_residual_kvar <= config.balance_tolerance_kw || push!(reasons, "reactive_balance_tolerance_exceeded")
    voltage_drop_residual <= config.voltage_drop_tolerance_pu2 || push!(reasons, "voltage_drop_tolerance_exceeded")
    root_residual <= config.root_voltage_tolerance_pu2 || push!(reasons, "root_voltage_tolerance_exceeded")
    abs(p_sub_residual) <= config.balance_tolerance_kw || push!(reasons, "substation_active_balance_tolerance_exceeded")
    abs(q_sub_residual) <= config.balance_tolerance_kw || push!(reasons, "substation_reactive_balance_tolerance_exceeded")
    p_sub >= -config.export_tolerance_kw || push!(reasons, "zero_pv_substation_export")
    numerical_passed = isempty(reasons)
    direction = p_sub < -config.export_tolerance_kw ? "export" :
                p_sub > config.export_tolerance_kw ? "import" : "approximately_zero"

    return S0StateResult(
        multiplier,
        operational_status,
        diagnostic_status,
        solution_source,
        true,
        numerical_passed,
        join(reasons, '|'),
        violation_counts.total == 0,
        total_active_load_kw,
        total_reactive_load_kvar,
        voltages,
        min_voltage,
        bus_ids[min_index],
        max_voltage,
        bus_ids[max_index],
        violation_counts.undervoltage,
        violation_counts.overvoltage,
        p_branch,
        q_branch,
        ell,
        soc_gap,
        current_a,
        receiving_p,
        receiving_q,
        p_sub,
        q_sub,
        s_sub,
        direction,
        active_losses_kw,
        reactive_losses_kvar,
        loss_percentage,
        max_ell,
        branch_ids[max_current_index],
        current_a[max_current_index],
        maximum_soc_gap,
        minimum_soc_gap,
        maximum_p_residual_kw,
        maximum_q_residual_kvar,
        voltage_drop_residual,
        root_residual,
        p_sub_residual,
        q_sub_residual,
    )
end

function _s0_extract_state(
    bundle::S0ParametricModel,
    multiplier::Float64,
    operational_status::String,
    diagnostic_status::String,
    solution_source::String,
    config::S0BaselineConfig,
)
    return _s0_extract_network_state(
        bundle.network,
        bundle.data,
        bundle.root_voltage_pu,
        1,
        multiplier,
        operational_status,
        diagnostic_status,
        solution_source,
        config,
    )
end

function _s0_failed_state(
    multiplier::Float64,
    operational_status::String,
    diagnostic_status::String,
    reason::String,
)
    nan_vector = Float64[]
    return S0StateResult(
        multiplier,
        operational_status,
        diagnostic_status,
        "none",
        false,
        false,
        reason,
        false,
        NaN,
        NaN,
        nan_vector,
        NaN,
        0,
        NaN,
        0,
        0,
        0,
        nan_vector,
        nan_vector,
        nan_vector,
        nan_vector,
        nan_vector,
        nan_vector,
        nan_vector,
        NaN,
        NaN,
        NaN,
        "unavailable",
        NaN,
        NaN,
        NaN,
        NaN,
        0,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
    )
end

function _solve_s0_load_state(
    operational_model::S0ParametricModel,
    diagnostic_model::S0ParametricModel,
    multiplier::Real;
    config::S0BaselineConfig=S0BaselineConfig(),
)
    value = Float64(multiplier)
    isfinite(value) && value >= 0.0 || throw(ArgumentError("S0 load multiplier must be finite and nonnegative"))
    operational_status, operational_primal = _s0_optimize_state!(operational_model, value)
    if operational_primal
        return _s0_extract_state(
            operational_model,
            value,
            operational_status,
            "not_run",
            "operational_model",
            config,
        )
    end

    diagnostic_status, diagnostic_primal = _s0_optimize_state!(diagnostic_model, value)
    if diagnostic_primal
        return _s0_extract_state(
            diagnostic_model,
            value,
            operational_status,
            diagnostic_status,
            "diagnostic_voltage_relaxation",
            config,
        )
    end
    return _s0_failed_state(
        value,
        operational_status,
        diagnostic_status,
        "operational_and_diagnostic_models_have_no_primal_solution",
    )
end

function _build_s0_batch_model(
    load_multipliers::Vector{Float64},
    root_voltage_pu::Float64,
    config::S0BaselineConfig;
    enforce_operational_voltage_limits::Bool=false,
)
    isempty(load_multipliers) && throw(ArgumentError("S0 batch must contain at least one interval"))
    vmin = enforce_operational_voltage_limits ? config.vmin_pu : config.diagnostic_vmin_pu
    vmax = enforce_operational_voltage_limits ? config.vmax_pu : config.diagnostic_vmax_pu
    buses, branches = build_ieee33_network()
    interval_count = length(load_multipliers)
    timeseries = TimeSeries(
        interval_count,
        config.dt_hours,
        load_multipliers,
        zeros(interval_count),
        zeros(interval_count),
        zeros(interval_count),
    )
    data = CaseData(
        buses,
        branches,
        PVUnit[],
        EVCS[],
        BESS[],
        nothing,
        timeseries,
        10.0,
        vmin,
        vmax,
    )
    check_data_consistency(data)
    model = JuMP.Model(Clarabel.Optimizer)
    JuMP.set_silent(model)
    for (attribute, value) in (
        ("tol_gap_abs", 1e-9),
        ("tol_gap_rel", 1e-9),
        ("tol_feas", 1e-9),
        ("reduced_tol_gap_abs", 1e-6),
        ("reduced_tol_gap_rel", 1e-6),
        ("reduced_tol_feas", 1e-6),
        ("reduced_tol_infeas_rel", 1e-6),
        ("reduced_tol_ktratio", 1e-6),
        ("max_iter", 300),
    )
        JuMP.set_optimizer_attribute(model, attribute, value)
    end
    zero_injection = Dict(
        bus.id => [JuMP.AffExpr(0.0) for _ in 1:interval_count]
        for bus in data.buses
    )
    network = add_socp_branch_flow_constraints!(
        model,
        data,
        zero_injection;
        root_bus=1,
        root_voltage_pu=root_voltage_pu,
    )
    @objective(
        model,
        Min,
        sum(
            network.r_pu[branch_id] * network.ell[branch_id, t]
            for branch_id in network.topology.branch_ids, t in 1:interval_count
        ),
    )
    return model, network, data
end

function _solve_s0_batch(
    load_multipliers::Vector{Float64},
    root_voltage_pu::Float64,
    config::S0BaselineConfig;
    enforce_operational_voltage_limits::Bool=false,
)
    model, network, data = _build_s0_batch_model(
        load_multipliers,
        root_voltage_pu,
        config;
        enforce_operational_voltage_limits=enforce_operational_voltage_limits,
    )
    solve_runtime_seconds = @elapsed JuMP.optimize!(model)
    status = string(JuMP.termination_status(model))
    primal_available = status in _S0_ACCEPTED_SOLVER_STATUSES && JuMP.has_values(model)
    if !primal_available
        states = [
            _s0_failed_state(multiplier, status, "not_run", "batch_model_has_no_primal_solution")
            for multiplier in load_multipliers
        ]
        return (
            status=status,
            primal_available=false,
            solve_runtime_seconds=solve_runtime_seconds,
            states=states,
        )
    end

    source = enforce_operational_voltage_limits ? "operational_batch_socp" : "full_period_batch_socp"
    states = [
        _s0_extract_network_state(
            network,
            data,
            root_voltage_pu,
            time_index,
            multiplier,
            status,
            "not_required",
            source,
            config,
        )
        for (time_index, multiplier) in enumerate(load_multipliers)
    ]
    return (
        status=status,
        primal_available=true,
        solve_runtime_seconds=solve_runtime_seconds,
        states=states,
    )
end

function _s0_build_thread_bundles(root_voltage_pu::Float64, config::S0BaselineConfig)
    thread_count = Threads.nthreads()
    # Julia's interactive thread (ID 1) is not part of the default pool used by
    # `@threads`; default-pool IDs can therefore start at 2.  Index the bundles
    # by the actual global thread ID, not by a dense 1:thread_count assumption.
    bundles = Vector{Any}(undef, Threads.maxthreadid())
    Threads.@threads :static for slot in 1:thread_count
        bundles[Threads.threadid()] = (
            operational=_build_s0_baseline_model(root_voltage_pu; config=config),
            diagnostic=_build_s0_baseline_model(
                root_voltage_pu;
                config=config,
                enforce_operational_voltage_limits=false,
            ),
        )
    end
    return bundles
end

function _s0_solve_interval_range(
    profile::S0LoadProfile,
    indices::UnitRange{Int},
    bundles::Vector{Any},
    config::S0BaselineConfig,
)
    results = Vector{S0StateResult}(undef, length(indices))
    solve_runtime_seconds = @elapsed Threads.@threads :static for local_index in eachindex(indices)
        index = indices[local_index]
        bundle = bundles[Threads.threadid()]
        multiplier = profile.load_multipliers[index]
        results[local_index] = try
            _solve_s0_load_state(
                bundle.operational,
                bundle.diagnostic,
                multiplier;
                config=config,
            )
        catch err
            _s0_failed_state(
                multiplier,
                "EXCEPTION",
                "not_run",
                "exception:" * replace(sprint(showerror, err), ',' => ';', '\n' => ' '),
            )
        end
    end
    return results, solve_runtime_seconds
end

function _solve_s0_case_threaded(
    profile::S0LoadProfile,
    root_voltage_pu::Float64,
    config::S0BaselineConfig,
)
    bundles = _s0_build_thread_bundles(root_voltage_pu, config)
    return _s0_solve_interval_range(profile, 1:length(profile.timestamps), bundles, config)
end

function _s0_format_timestamp(timestamp::DateTime)
    return Dates.format(timestamp, dateformat"yyyy-mm-dd HH:MM:SS")
end

function _s0_csv_value(value)
    if value isa DateTime
        return _s0_format_timestamp(value)
    elseif value isa AbstractFloat
        return isfinite(value) ? @sprintf("%.15g", value) : string(value)
    elseif value isa Bool
        return value ? "true" : "false"
    elseif value === nothing
        return ""
    end
    text = string(value)
    if occursin(',', text) || occursin('"', text) || occursin('\n', text)
        return "\"" * replace(text, '"' => "\"\"") * "\""
    end
    return text
end

function _s0_write_csv_header(io::IO, columns)
    println(io, join(columns, ','))
end

function _s0_write_csv_row(io::IO, values)
    println(io, join((_s0_csv_value(value) for value in values), ','))
end

function _s0_write_interval_row(io::IO, root_voltage_pu::Float64, timestamp::DateTime, state::S0StateResult)
    _s0_write_csv_row(io, (
        root_voltage_pu,
        timestamp,
        state.load_multiplier,
        state.operational_solver_status,
        state.diagnostic_solver_status,
        state.solution_source,
        state.primal_available,
        state.numerical_validation_passed,
        state.operational_voltage_feasible,
        state.total_active_load_kw,
        state.total_reactive_load_kvar,
        state.minimum_voltage_pu,
        state.minimum_voltage_bus,
        state.maximum_voltage_pu,
        state.maximum_voltage_bus,
        state.undervoltage_bus_count,
        state.overvoltage_bus_count,
        state.substation_active_power_kw,
        state.substation_reactive_power_kvar,
        state.substation_apparent_power_kva,
        state.substation_direction,
        state.active_losses_kw,
        state.reactive_losses_kvar,
        state.active_loss_percentage,
        state.maximum_ell_pu2,
        state.maximum_current_branch_id,
        state.maximum_current_a,
        state.maximum_soc_gap_pu2,
        state.minimum_soc_gap_pu2,
        state.maximum_active_balance_residual_kw,
        state.maximum_reactive_balance_residual_kvar,
        state.maximum_voltage_drop_residual_pu2,
        state.root_voltage_residual_pu2,
        state.substation_active_balance_residual_kw,
        state.substation_reactive_balance_residual_kvar,
    ))
end

struct S0ACResult
    converged::Bool
    iterations::Int
    voltages_pu::Vector{ComplexF64}
    substation_active_power_kw::Float64
    substation_reactive_power_kvar::Float64
end

function _s0_topological_bus_order(topology::RadialTopology)
    order = Int[topology.root_bus]
    head = 1
    while head <= length(order)
        bus = order[head]
        head += 1
        child_branches = sort(topology.outgoing_branches[bus])
        append!(order, (topology.to_bus[branch_id] for branch_id in child_branches))
    end
    return order
end

function _s0_ac_branch_currents(
    topology::RadialTopology,
    order::Vector{Int},
    voltage_pu::Vector{ComplexF64},
    load_power_pu::Vector{ComplexF64},
)
    local_current = zeros(ComplexF64, length(voltage_pu))
    branch_current = zeros(ComplexF64, length(topology.branch_ids))
    for bus in order
        bus == topology.root_bus && continue
        abs(voltage_pu[bus]) > 1e-10 || return branch_current, false
        local_current[bus] = conj(load_power_pu[bus] / voltage_pu[bus])
    end
    for bus in Iterators.reverse(order)
        bus == topology.root_bus && continue
        total_current = local_current[bus] + sum(
            branch_current[child]
            for child in topology.outgoing_branches[bus];
            init=0.0 + 0.0im,
        )
        branch_current[topology.incoming_branch[bus]] = total_current
    end
    return branch_current, true
end

function _s0_ac_power_flow(
    multiplier::Float64,
    root_voltage_pu::Float64;
    tolerance_pu::Float64=1e-12,
    maximum_iterations::Int=2000,
    damping::Float64=0.70,
)
    config = S0BaselineConfig()
    data = _s0_case_data(config, config.diagnostic_vmin_pu, config.diagnostic_vmax_pu)
    topology = _build_radial_topology(data; root_bus=1)
    r_pu, x_pu, _ = _branch_pu_parameters(data, topology)
    order = _s0_topological_bus_order(topology)
    base_power_kw = data.base_mva * 1000.0
    load_power_pu = zeros(ComplexF64, length(data.buses))
    for bus in data.buses
        load_power_pu[bus.id] = complex(bus.pd_kw, bus.qd_kvar) * multiplier / base_power_kw
    end
    voltage = fill(complex(root_voltage_pu, 0.0), length(data.buses))
    branch_current = zeros(ComplexF64, length(data.branches))

    for iteration in 1:maximum_iterations
        branch_current, valid = _s0_ac_branch_currents(topology, order, voltage, load_power_pu)
        valid || return S0ACResult(false, iteration, voltage, NaN, NaN)
        fixed_point_voltage = copy(voltage)
        fixed_point_voltage[topology.root_bus] = complex(root_voltage_pu, 0.0)
        for bus in order
            bus == topology.root_bus && continue
            incoming = topology.incoming_branch[bus]
            parent = topology.from_bus[incoming]
            impedance = complex(r_pu[incoming], x_pu[incoming])
            fixed_point_voltage[bus] = fixed_point_voltage[parent] - impedance * branch_current[incoming]
        end
        maximum_update = maximum(abs.(fixed_point_voltage .- voltage))
        voltage .= damping .* fixed_point_voltage .+ (1.0 - damping) .* voltage
        voltage[topology.root_bus] = complex(root_voltage_pu, 0.0)
        if maximum_update <= tolerance_pu
            branch_current, valid = _s0_ac_branch_currents(topology, order, voltage, load_power_pu)
            valid || return S0ACResult(false, iteration, voltage, NaN, NaN)
            substation_power_pu = sum(
                voltage[topology.root_bus] * conj(branch_current[branch_id])
                for branch_id in topology.outgoing_branches[topology.root_bus];
                init=0.0 + 0.0im,
            )
            return S0ACResult(
                true,
                iteration,
                voltage,
                real(substation_power_pu) * base_power_kw,
                imag(substation_power_pu) * base_power_kw,
            )
        end
    end
    return S0ACResult(false, maximum_iterations, voltage, NaN, NaN)
end

function _s0_process_case_results!(
    interval_io::IO,
    branch_io::IO,
    violation_io::IO,
    failure_io::IO,
    critical_io::IO,
    profile::S0LoadProfile,
    root_voltage_pu::Float64,
    results::Vector{S0StateResult},
    config::S0BaselineConfig,
)
    interval_count = length(profile.timestamps)
    s0_assert_full_interval_coverage(interval_count, length(results))
    data = _s0_case_data(config, config.diagnostic_vmin_pu, config.diagnostic_vmax_pu)
    topology = _build_radial_topology(data; root_bus=1)
    branch_ids = sort(topology.branch_ids)
    branch_count = length(branch_ids)
    bus_ids = sort(topology.bus_ids)
    bus_by_id = Dict(bus.id => bus for bus in data.buses)
    base_power_kw = data.base_mva * 1000.0

    peak_branch_ell = fill(-Inf, branch_count)
    peak_branch_index = fill(0, branch_count)
    branch_maximum_soc_gap = fill(-Inf, branch_count)
    branch_minimum_soc_gap = fill(Inf, branch_count)

    solved_intervals = 0
    solver_failed_intervals = 0
    operational_model_fallback_intervals = 0
    numerically_valid_intervals = 0
    operationally_feasible_intervals = 0
    violation_intervals = 0
    undervoltage_count = 0
    overvoltage_count = 0
    export_intervals = 0
    loss_percentage_sum = 0.0

    global_min_voltage = Inf
    global_min_bus = 0
    global_min_index = 0
    global_max_voltage = -Inf
    global_max_bus = 0
    global_max_index = 0
    peak_current = -Inf
    peak_current_index = 0
    peak_substation = -Inf
    peak_substation_index = 0
    maximum_losses = -Inf
    maximum_losses_index = 0
    maximum_loss_percentage = -Inf
    maximum_loss_percentage_index = 0
    maximum_soc_gap = -Inf
    minimum_soc_gap = Inf

    for index in 1:interval_count
        timestamp = profile.timestamps[index]
        state = results[index]
        _s0_write_interval_row(interval_io, root_voltage_pu, timestamp, state)

        if !state.primal_available
            solver_failed_intervals += 1
            _s0_write_csv_row(failure_io, (
                root_voltage_pu,
                timestamp,
                state.load_multiplier,
                state.operational_solver_status,
                state.diagnostic_solver_status,
                false,
                state.failure_reason,
            ))
            continue
        end

        solved_intervals += 1
        state.solution_source == "diagnostic_voltage_relaxation" && (operational_model_fallback_intervals += 1)
        state.numerical_validation_passed && (numerically_valid_intervals += 1)
        state.operational_voltage_feasible && (operationally_feasible_intervals += 1)
        state.substation_direction == "export" && (export_intervals += 1)
        loss_percentage_sum += state.active_loss_percentage
        maximum_soc_gap = max(maximum_soc_gap, state.maximum_soc_gap_pu2)
        minimum_soc_gap = min(minimum_soc_gap, state.minimum_soc_gap_pu2)

        failure_reasons = String[]
        if state.solution_source == "diagnostic_voltage_relaxation"
            push!(failure_reasons, "operational_voltage_model_infeasible;diagnostic_solution_recorded")
        end
        if !state.numerical_validation_passed
            push!(failure_reasons, state.failure_reason)
        end
        if !isempty(failure_reasons)
            _s0_write_csv_row(failure_io, (
                root_voltage_pu,
                timestamp,
                state.load_multiplier,
                state.operational_solver_status,
                state.diagnostic_solver_status,
                true,
                join(failure_reasons, '|'),
            ))
        end

        if !state.operational_voltage_feasible
            violation_intervals += 1
        end
        undervoltage_count += state.undervoltage_bus_count
        overvoltage_count += state.overvoltage_bus_count
        for (bus_index, voltage) in enumerate(state.voltages_pu)
            bus_id = bus_ids[bus_index]
            if voltage < config.vmin_pu - config.voltage_tolerance_pu
                _s0_write_csv_row(violation_io, (
                    root_voltage_pu,
                    timestamp,
                    bus_id,
                    voltage,
                    "undervoltage",
                    config.vmin_pu,
                    config.vmin_pu - voltage,
                ))
            elseif voltage > config.vmax_pu + config.voltage_tolerance_pu
                _s0_write_csv_row(violation_io, (
                    root_voltage_pu,
                    timestamp,
                    bus_id,
                    voltage,
                    "overvoltage",
                    config.vmax_pu,
                    voltage - config.vmax_pu,
                ))
            end
        end

        if state.minimum_voltage_pu < global_min_voltage
            global_min_voltage = state.minimum_voltage_pu
            global_min_bus = state.minimum_voltage_bus
            global_min_index = index
        end
        if state.maximum_voltage_pu > global_max_voltage
            global_max_voltage = state.maximum_voltage_pu
            global_max_bus = state.maximum_voltage_bus
            global_max_index = index
        end
        if state.maximum_current_a > peak_current
            peak_current = state.maximum_current_a
            peak_current_index = index
        end
        if state.substation_apparent_power_kva > peak_substation
            peak_substation = state.substation_apparent_power_kva
            peak_substation_index = index
        end
        if state.active_losses_kw > maximum_losses
            maximum_losses = state.active_losses_kw
            maximum_losses_index = index
        end
        if state.active_loss_percentage > maximum_loss_percentage
            maximum_loss_percentage = state.active_loss_percentage
            maximum_loss_percentage_index = index
        end

        for branch_id in branch_ids
            branch_position = findfirst(==(branch_id), branch_ids)
            ell_value = state.branch_ell_pu2[branch_position]
            if ell_value > peak_branch_ell[branch_position]
                peak_branch_ell[branch_position] = ell_value
                peak_branch_index[branch_position] = index
            end
            branch_maximum_soc_gap[branch_position] = max(
                branch_maximum_soc_gap[branch_position],
                state.branch_soc_gap_pu2[branch_position],
            )
            branch_minimum_soc_gap[branch_position] = min(
                branch_minimum_soc_gap[branch_position],
                state.branch_soc_gap_pu2[branch_position],
            )
        end
    end

    s0_assert_full_interval_coverage(interval_count, solved_intervals + solver_failed_intervals, solver_failed_intervals)
    solved_intervals > 0 || throw(ArgumentError("S0 case V0=$root_voltage_pu has no solved intervals"))

    branch_peak_current_a = zeros(Float64, branch_count)
    for (branch_position, branch_id) in enumerate(branch_ids)
        index = peak_branch_index[branch_position]
        index > 0 || continue
        state = results[index]
        from_bus = topology.from_bus[branch_id]
        to_bus = topology.to_bus[branch_id]
        base_kv = bus_by_id[from_bus].base_kv
        base_current_a = data.base_mva * 1e6 / (sqrt(3.0) * base_kv * 1e3)
        current_pu = sqrt(max(0.0, state.branch_ell_pu2[branch_position]))
        current_a = current_pu * base_current_a
        branch_peak_current_a[branch_position] = current_a
        p_send_kw = state.branch_active_power_pu[branch_position] * base_power_kw
        q_send_kvar = state.branch_reactive_power_pu[branch_position] * base_power_kw
        p_receive_kw = state.branch_receiving_active_power_pu[branch_position] * base_power_kw
        q_receive_kvar = state.branch_receiving_reactive_power_pu[branch_position] * base_power_kw
        _s0_write_csv_row(branch_io, (
            root_voltage_pu,
            branch_id,
            from_bus,
            to_bus,
            state.branch_ell_pu2[branch_position],
            current_pu,
            current_a,
            base_current_a,
            true,
            profile.timestamps[index],
            p_send_kw,
            q_send_kvar,
            s0_apparent_power(p_send_kw, q_send_kvar),
            p_receive_kw,
            q_receive_kvar,
            s0_apparent_power(p_receive_kw, q_receive_kvar),
            branch_maximum_soc_gap[branch_position],
            branch_minimum_soc_gap[branch_position],
        ))
    end

    peak_branch_position = argmax(branch_peak_current_a)
    peak_branch_id = branch_ids[peak_branch_position]
    peak_branch_state_index = peak_branch_index[peak_branch_position]
    critical_selections = (
        ("minimum_socp_voltage", global_min_index),
        ("peak_branch_current", peak_current_index),
        ("peak_substation_apparent_power", peak_substation_index),
        ("maximum_socp_loss_percentage", maximum_loss_percentage_index),
    )
    ac_passed_count = 0
    for (reason, index) in critical_selections
        state = results[index]
        ac = _s0_ac_power_flow(state.load_multiplier, root_voltage_pu)
        voltage_difference = ac.converged ? maximum(abs.(abs.(ac.voltages_pu) .- state.voltages_pu)) : Inf
        p_difference = ac.converged ? abs(ac.substation_active_power_kw - state.substation_active_power_kw) : Inf
        q_difference = ac.converged ? abs(ac.substation_reactive_power_kvar - state.substation_reactive_power_kvar) : Inf
        ac_passed = ac.converged &&
                    voltage_difference <= config.ac_voltage_tolerance_pu &&
                    p_difference <= config.ac_power_tolerance_kw &&
                    q_difference <= config.ac_power_tolerance_kw
        ac_passed && (ac_passed_count += 1)
        _s0_write_csv_row(critical_io, (
            root_voltage_pu,
            reason,
            profile.timestamps[index],
            state.load_multiplier,
            state.minimum_voltage_pu,
            state.maximum_current_branch_id,
            state.maximum_current_a,
            state.substation_apparent_power_kva,
            state.active_loss_percentage,
            ac_passed ? "PASS" : ac.converged ? "MISMATCH" : "NOT_CONVERGED",
            ac.iterations,
            voltage_difference,
            p_difference,
            q_difference,
        ))
    end

    fully_validated = solver_failed_intervals == 0 &&
                      operational_model_fallback_intervals == 0 &&
                      numerically_valid_intervals == interval_count &&
                      operationally_feasible_intervals == interval_count &&
                      export_intervals == 0 &&
                      ac_passed_count == length(critical_selections)
    summary = (
        root_voltage_pu=root_voltage_pu,
        interval_count=interval_count,
        solved_intervals=solved_intervals,
        solver_failed_intervals=solver_failed_intervals,
        operational_model_fallback_intervals=operational_model_fallback_intervals,
        numerically_valid_intervals=numerically_valid_intervals,
        operationally_feasible_intervals=operationally_feasible_intervals,
        intervals_with_voltage_violations=violation_intervals,
        violation_interval_percentage=100.0 * violation_intervals / interval_count,
        undervoltage_bus_time_count=undervoltage_count,
        overvoltage_bus_time_count=overvoltage_count,
        global_minimum_voltage_pu=global_min_voltage,
        global_minimum_voltage_bus=global_min_bus,
        global_minimum_voltage_timestamp=profile.timestamps[global_min_index],
        global_maximum_voltage_pu=global_max_voltage,
        global_maximum_voltage_bus=global_max_bus,
        global_maximum_voltage_timestamp=profile.timestamps[global_max_index],
        peak_branch_id=peak_branch_id,
        peak_branch_ell_pu2=peak_branch_ell[peak_branch_position],
        peak_branch_current_a=branch_peak_current_a[peak_branch_position],
        peak_branch_current_timestamp=profile.timestamps[peak_branch_state_index],
        peak_substation_apparent_power_kva=peak_substation,
        peak_substation_timestamp=profile.timestamps[peak_substation_index],
        maximum_active_losses_kw=maximum_losses,
        maximum_active_losses_timestamp=profile.timestamps[maximum_losses_index],
        maximum_active_loss_percentage=maximum_loss_percentage,
        maximum_active_loss_percentage_timestamp=profile.timestamps[maximum_loss_percentage_index],
        average_active_loss_percentage=loss_percentage_sum / solved_intervals,
        maximum_soc_gap_pu2=maximum_soc_gap,
        minimum_soc_gap_pu2=minimum_soc_gap,
        zero_pv_export_intervals=export_intervals,
        fully_validated=fully_validated,
    )
    return summary, ac_passed_count
end

function _s0_case_accumulator(profile::S0LoadProfile, root_voltage_pu::Float64, config::S0BaselineConfig)
    data = _s0_case_data(config, config.diagnostic_vmin_pu, config.diagnostic_vmax_pu)
    topology = _build_radial_topology(data; root_bus=1)
    branch_ids = sort(topology.branch_ids)
    branch_count = length(branch_ids)
    return Dict{Symbol,Any}(
        :profile => profile,
        :root_voltage_pu => root_voltage_pu,
        :config => config,
        :data => data,
        :topology => topology,
        :branch_ids => branch_ids,
        :bus_ids => sort(topology.bus_ids),
        :bus_by_id => Dict(bus.id => bus for bus in data.buses),
        :processed_intervals => 0,
        :solved_intervals => 0,
        :solver_failed_intervals => 0,
        :operational_model_fallback_intervals => 0,
        :numerically_valid_intervals => 0,
        :operationally_feasible_intervals => 0,
        :violation_intervals => 0,
        :undervoltage_count => 0,
        :overvoltage_count => 0,
        :export_intervals => 0,
        :loss_percentage_sum => 0.0,
        :global_min_voltage => Inf,
        :global_min_bus => 0,
        :global_min_index => 0,
        :global_min_state => nothing,
        :global_max_voltage => -Inf,
        :global_max_bus => 0,
        :global_max_index => 0,
        :peak_current => -Inf,
        :peak_current_index => 0,
        :peak_current_state => nothing,
        :peak_substation => -Inf,
        :peak_substation_index => 0,
        :peak_substation_state => nothing,
        :maximum_losses => -Inf,
        :maximum_losses_index => 0,
        :maximum_loss_percentage => -Inf,
        :maximum_loss_percentage_index => 0,
        :maximum_loss_percentage_state => nothing,
        :maximum_soc_gap => -Inf,
        :minimum_soc_gap => Inf,
        :peak_branch_ell => fill(-Inf, branch_count),
        :peak_branch_index => fill(0, branch_count),
        :peak_branch_states => Union{Nothing,S0StateResult}[nothing for _ in 1:branch_count],
        :branch_maximum_soc_gap => fill(-Inf, branch_count),
        :branch_minimum_soc_gap => fill(Inf, branch_count),
    )
end

function _s0_accumulate_case_chunk!(
    accumulator::Dict{Symbol,Any},
    interval_io::IO,
    violation_io::IO,
    failure_io::IO,
    results::Vector{S0StateResult},
    first_global_index::Int,
)
    profile = accumulator[:profile]
    root_voltage_pu = accumulator[:root_voltage_pu]
    config = accumulator[:config]
    bus_ids = accumulator[:bus_ids]
    branch_ids = accumulator[:branch_ids]

    for (local_index, state) in enumerate(results)
        index = first_global_index + local_index - 1
        timestamp = profile.timestamps[index]
        accumulator[:processed_intervals] += 1
        _s0_write_interval_row(interval_io, root_voltage_pu, timestamp, state)

        if !state.primal_available
            accumulator[:solver_failed_intervals] += 1
            _s0_write_csv_row(failure_io, (
                root_voltage_pu,
                timestamp,
                state.load_multiplier,
                state.operational_solver_status,
                state.diagnostic_solver_status,
                false,
                state.failure_reason,
            ))
            continue
        end

        accumulator[:solved_intervals] += 1
        state.solution_source == "diagnostic_voltage_relaxation" &&
            (accumulator[:operational_model_fallback_intervals] += 1)
        state.numerical_validation_passed && (accumulator[:numerically_valid_intervals] += 1)
        state.operational_voltage_feasible && (accumulator[:operationally_feasible_intervals] += 1)
        state.substation_direction == "export" && (accumulator[:export_intervals] += 1)
        accumulator[:loss_percentage_sum] += state.active_loss_percentage
        accumulator[:maximum_soc_gap] = max(accumulator[:maximum_soc_gap], state.maximum_soc_gap_pu2)
        accumulator[:minimum_soc_gap] = min(accumulator[:minimum_soc_gap], state.minimum_soc_gap_pu2)

        failure_reasons = String[]
        if state.solution_source == "diagnostic_voltage_relaxation"
            push!(failure_reasons, "operational_voltage_model_infeasible;diagnostic_solution_recorded")
        end
        !state.numerical_validation_passed && push!(failure_reasons, state.failure_reason)
        if !isempty(failure_reasons)
            _s0_write_csv_row(failure_io, (
                root_voltage_pu,
                timestamp,
                state.load_multiplier,
                state.operational_solver_status,
                state.diagnostic_solver_status,
                true,
                join(failure_reasons, '|'),
            ))
        end

        !state.operational_voltage_feasible && (accumulator[:violation_intervals] += 1)
        accumulator[:undervoltage_count] += state.undervoltage_bus_count
        accumulator[:overvoltage_count] += state.overvoltage_bus_count
        for (bus_index, voltage) in enumerate(state.voltages_pu)
            bus_id = bus_ids[bus_index]
            if voltage < config.vmin_pu - config.voltage_tolerance_pu
                _s0_write_csv_row(violation_io, (
                    root_voltage_pu,
                    timestamp,
                    bus_id,
                    voltage,
                    "undervoltage",
                    config.vmin_pu,
                    config.vmin_pu - voltage,
                ))
            elseif voltage > config.vmax_pu + config.voltage_tolerance_pu
                _s0_write_csv_row(violation_io, (
                    root_voltage_pu,
                    timestamp,
                    bus_id,
                    voltage,
                    "overvoltage",
                    config.vmax_pu,
                    voltage - config.vmax_pu,
                ))
            end
        end

        if state.minimum_voltage_pu < accumulator[:global_min_voltage]
            accumulator[:global_min_voltage] = state.minimum_voltage_pu
            accumulator[:global_min_bus] = state.minimum_voltage_bus
            accumulator[:global_min_index] = index
            accumulator[:global_min_state] = state
        end
        if state.maximum_voltage_pu > accumulator[:global_max_voltage]
            accumulator[:global_max_voltage] = state.maximum_voltage_pu
            accumulator[:global_max_bus] = state.maximum_voltage_bus
            accumulator[:global_max_index] = index
        end
        if state.maximum_current_a > accumulator[:peak_current]
            accumulator[:peak_current] = state.maximum_current_a
            accumulator[:peak_current_index] = index
            accumulator[:peak_current_state] = state
        end
        if state.substation_apparent_power_kva > accumulator[:peak_substation]
            accumulator[:peak_substation] = state.substation_apparent_power_kva
            accumulator[:peak_substation_index] = index
            accumulator[:peak_substation_state] = state
        end
        if state.active_losses_kw > accumulator[:maximum_losses]
            accumulator[:maximum_losses] = state.active_losses_kw
            accumulator[:maximum_losses_index] = index
        end
        if state.active_loss_percentage > accumulator[:maximum_loss_percentage]
            accumulator[:maximum_loss_percentage] = state.active_loss_percentage
            accumulator[:maximum_loss_percentage_index] = index
            accumulator[:maximum_loss_percentage_state] = state
        end

        for (branch_position, _) in enumerate(branch_ids)
            ell_value = state.branch_ell_pu2[branch_position]
            if ell_value > accumulator[:peak_branch_ell][branch_position]
                accumulator[:peak_branch_ell][branch_position] = ell_value
                accumulator[:peak_branch_index][branch_position] = index
                accumulator[:peak_branch_states][branch_position] = state
            end
            accumulator[:branch_maximum_soc_gap][branch_position] = max(
                accumulator[:branch_maximum_soc_gap][branch_position],
                state.branch_soc_gap_pu2[branch_position],
            )
            accumulator[:branch_minimum_soc_gap][branch_position] = min(
                accumulator[:branch_minimum_soc_gap][branch_position],
                state.branch_soc_gap_pu2[branch_position],
            )
        end
    end
    return accumulator
end

function _s0_finalize_case_accumulator!(
    accumulator::Dict{Symbol,Any},
    branch_io::IO,
    critical_io::IO,
)
    profile = accumulator[:profile]
    root_voltage_pu = accumulator[:root_voltage_pu]
    config = accumulator[:config]
    data = accumulator[:data]
    topology = accumulator[:topology]
    branch_ids = accumulator[:branch_ids]
    bus_by_id = accumulator[:bus_by_id]
    interval_count = length(profile.timestamps)
    solved_intervals = accumulator[:solved_intervals]
    solver_failed_intervals = accumulator[:solver_failed_intervals]

    s0_assert_full_interval_coverage(interval_count, accumulator[:processed_intervals])
    s0_assert_full_interval_coverage(
        interval_count,
        solved_intervals + solver_failed_intervals,
        solver_failed_intervals,
    )
    solved_intervals > 0 || throw(ArgumentError("S0 case V0=$root_voltage_pu has no solved intervals"))

    base_power_kw = data.base_mva * 1000.0
    branch_peak_current_a = zeros(Float64, length(branch_ids))
    for (branch_position, branch_id) in enumerate(branch_ids)
        index = accumulator[:peak_branch_index][branch_position]
        index > 0 || continue
        state = accumulator[:peak_branch_states][branch_position]::S0StateResult
        from_bus = topology.from_bus[branch_id]
        to_bus = topology.to_bus[branch_id]
        base_kv = bus_by_id[from_bus].base_kv
        base_current_a = data.base_mva * 1e6 / (sqrt(3.0) * base_kv * 1e3)
        current_pu = sqrt(max(0.0, state.branch_ell_pu2[branch_position]))
        current_a = current_pu * base_current_a
        branch_peak_current_a[branch_position] = current_a
        p_send_kw = state.branch_active_power_pu[branch_position] * base_power_kw
        q_send_kvar = state.branch_reactive_power_pu[branch_position] * base_power_kw
        p_receive_kw = state.branch_receiving_active_power_pu[branch_position] * base_power_kw
        q_receive_kvar = state.branch_receiving_reactive_power_pu[branch_position] * base_power_kw
        _s0_write_csv_row(branch_io, (
            root_voltage_pu,
            branch_id,
            from_bus,
            to_bus,
            state.branch_ell_pu2[branch_position],
            current_pu,
            current_a,
            base_current_a,
            true,
            profile.timestamps[index],
            p_send_kw,
            q_send_kvar,
            s0_apparent_power(p_send_kw, q_send_kvar),
            p_receive_kw,
            q_receive_kvar,
            s0_apparent_power(p_receive_kw, q_receive_kvar),
            accumulator[:branch_maximum_soc_gap][branch_position],
            accumulator[:branch_minimum_soc_gap][branch_position],
        ))
    end

    peak_branch_position = argmax(branch_peak_current_a)
    critical_selections = (
        ("minimum_socp_voltage", accumulator[:global_min_index], accumulator[:global_min_state]),
        ("peak_branch_current", accumulator[:peak_current_index], accumulator[:peak_current_state]),
        (
            "peak_substation_apparent_power",
            accumulator[:peak_substation_index],
            accumulator[:peak_substation_state],
        ),
        (
            "maximum_socp_loss_percentage",
            accumulator[:maximum_loss_percentage_index],
            accumulator[:maximum_loss_percentage_state],
        ),
    )
    ac_passed_count = 0
    for (reason, index, stored_state) in critical_selections
        state = stored_state::S0StateResult
        ac = _s0_ac_power_flow(state.load_multiplier, root_voltage_pu)
        voltage_difference = ac.converged ? maximum(abs.(abs.(ac.voltages_pu) .- state.voltages_pu)) : Inf
        p_difference = ac.converged ? abs(ac.substation_active_power_kw - state.substation_active_power_kw) : Inf
        q_difference = ac.converged ? abs(ac.substation_reactive_power_kvar - state.substation_reactive_power_kvar) : Inf
        ac_passed = ac.converged &&
                    voltage_difference <= config.ac_voltage_tolerance_pu &&
                    p_difference <= config.ac_power_tolerance_kw &&
                    q_difference <= config.ac_power_tolerance_kw
        ac_passed && (ac_passed_count += 1)
        _s0_write_csv_row(critical_io, (
            root_voltage_pu,
            reason,
            profile.timestamps[index],
            state.load_multiplier,
            state.minimum_voltage_pu,
            state.maximum_current_branch_id,
            state.maximum_current_a,
            state.substation_apparent_power_kva,
            state.active_loss_percentage,
            ac_passed ? "PASS" : ac.converged ? "MISMATCH" : "NOT_CONVERGED",
            ac.iterations,
            voltage_difference,
            p_difference,
            q_difference,
        ))
    end

    fully_validated = solver_failed_intervals == 0 &&
                      accumulator[:operational_model_fallback_intervals] == 0 &&
                      accumulator[:numerically_valid_intervals] == interval_count &&
                      accumulator[:operationally_feasible_intervals] == interval_count &&
                      accumulator[:export_intervals] == 0 &&
                      ac_passed_count == length(critical_selections)
    summary = (
        root_voltage_pu=root_voltage_pu,
        interval_count=interval_count,
        solved_intervals=solved_intervals,
        solver_failed_intervals=solver_failed_intervals,
        operational_model_fallback_intervals=accumulator[:operational_model_fallback_intervals],
        numerically_valid_intervals=accumulator[:numerically_valid_intervals],
        operationally_feasible_intervals=accumulator[:operationally_feasible_intervals],
        intervals_with_voltage_violations=accumulator[:violation_intervals],
        violation_interval_percentage=100.0 * accumulator[:violation_intervals] / interval_count,
        undervoltage_bus_time_count=accumulator[:undervoltage_count],
        overvoltage_bus_time_count=accumulator[:overvoltage_count],
        global_minimum_voltage_pu=accumulator[:global_min_voltage],
        global_minimum_voltage_bus=accumulator[:global_min_bus],
        global_minimum_voltage_timestamp=profile.timestamps[accumulator[:global_min_index]],
        global_maximum_voltage_pu=accumulator[:global_max_voltage],
        global_maximum_voltage_bus=accumulator[:global_max_bus],
        global_maximum_voltage_timestamp=profile.timestamps[accumulator[:global_max_index]],
        peak_branch_id=branch_ids[peak_branch_position],
        peak_branch_ell_pu2=accumulator[:peak_branch_ell][peak_branch_position],
        peak_branch_current_a=branch_peak_current_a[peak_branch_position],
        peak_branch_current_timestamp=profile.timestamps[accumulator[:peak_branch_index][peak_branch_position]],
        peak_substation_apparent_power_kva=accumulator[:peak_substation],
        peak_substation_timestamp=profile.timestamps[accumulator[:peak_substation_index]],
        maximum_active_losses_kw=accumulator[:maximum_losses],
        maximum_active_losses_timestamp=profile.timestamps[accumulator[:maximum_losses_index]],
        maximum_active_loss_percentage=accumulator[:maximum_loss_percentage],
        maximum_active_loss_percentage_timestamp=profile.timestamps[accumulator[:maximum_loss_percentage_index]],
        average_active_loss_percentage=accumulator[:loss_percentage_sum] / solved_intervals,
        maximum_soc_gap_pu2=accumulator[:maximum_soc_gap],
        minimum_soc_gap_pu2=accumulator[:minimum_soc_gap],
        zero_pv_export_intervals=accumulator[:export_intervals],
        fully_validated=fully_validated,
    )
    return summary, ac_passed_count
end

function _s0_solve_and_process_case_streamed!(
    interval_io::IO,
    branch_io::IO,
    violation_io::IO,
    failure_io::IO,
    critical_io::IO,
    profile::S0LoadProfile,
    root_voltage_pu::Float64,
    config::S0BaselineConfig;
    chunk_size::Int=_S0_STREAM_CHUNK_SIZE,
)
    chunk_size > 0 || throw(ArgumentError("S0 chunk size must be positive"))
    bundles = _s0_build_thread_bundles(root_voltage_pu, config)
    accumulator = _s0_case_accumulator(profile, root_voltage_pu, config)
    solver_runtime_seconds = 0.0
    interval_count = length(profile.timestamps)

    for first_index in 1:chunk_size:interval_count
        last_index = min(first_index + chunk_size - 1, interval_count)
        results, chunk_runtime = _s0_solve_interval_range(
            profile,
            first_index:last_index,
            bundles,
            config,
        )
        solver_runtime_seconds += chunk_runtime
        _s0_accumulate_case_chunk!(
            accumulator,
            interval_io,
            violation_io,
            failure_io,
            results,
            first_index,
        )
        empty!(results)
        if last_index == interval_count || last_index % (8 * chunk_size) == 0
            flush(interval_io)
            flush(violation_io)
            flush(failure_io)
            GC.gc()
        end
        if last_index == interval_count || last_index % (20 * chunk_size) == 0
            println("S0 V0=$(root_voltage_pu) progress: $(last_index)/$(interval_count) intervals")
        end
    end

    summary, ac_passed_count = _s0_finalize_case_accumulator!(accumulator, branch_io, critical_io)
    return summary, ac_passed_count, solver_runtime_seconds
end

function _s0_json_escape(value::AbstractString)
    return replace(value, '\\' => "\\\\", '"' => "\\\"", '\n' => "\\n", '\r' => "\\r")
end

_s0_json_string(value) = "\"" * _s0_json_escape(string(value)) * "\""

function _s0_write_metadata(
    path::AbstractString,
    profile::S0LoadProfile,
    config::S0BaselineConfig,
    summaries,
    case_solver_runtimes::Vector{Float64},
    total_runtime_seconds::Float64,
    repository_commit::AbstractString,
    output_filenames::Vector{String},
)
    open(path, "w") do io
        println(io, "{")
        println(io, "  \"schema_version\": 1,")
        println(io, "  \"created_utc\": ", _s0_json_string(Dates.format(Dates.now(Dates.UTC), dateformat"yyyy-mm-ddTHH:MM:SSZ")), ",")
        println(io, "  \"repository_commit_at_run\": ", _s0_json_string(repository_commit), ",")
        println(io, "  \"input_file\": ", _s0_json_string(profile.source_path), ",")
        println(io, "  \"input_sha256\": ", _s0_json_string(profile.source_sha256), ",")
        println(io, "  \"input_interval_count\": ", length(profile.timestamps), ",")
        println(io, "  \"input_start_timestamp\": ", _s0_json_string(_s0_format_timestamp(first(profile.timestamps))), ",")
        println(io, "  \"input_end_timestamp\": ", _s0_json_string(_s0_format_timestamp(last(profile.timestamps))), ",")
        println(io, "  \"dt_hours\": ", config.dt_hours, ",")
        println(io, "  \"root_voltages_pu\": [", join(config.root_voltages_pu, ", "), "],")
        println(io, "  \"operational_voltage_limits_pu\": {\"minimum\": ", config.vmin_pu, ", \"maximum\": ", config.vmax_pu, "},")
        println(io, "  \"diagnostic_voltage_bounds_pu\": {\"minimum\": ", config.diagnostic_vmin_pu, ", \"maximum\": ", config.diagnostic_vmax_pu, "},")
        println(io, "  \"configuration\": {")
        println(io, "    \"pv_capacity_and_injection_kw\": 0.0,")
        println(io, "    \"ev_load_kw\": 0.0,")
        println(io, "    \"bess_charge_kw\": 0.0,")
        println(io, "    \"bess_discharge_kw\": 0.0,")
        println(io, "    \"curtailment_variables\": \"absent\",")
        println(io, "    \"no_export_constraint_active\": false,")
        println(io, "    \"loss_cap_constraint_active\": false,")
        println(io, "    \"candidate_pv_buses_have_effect\": false,")
        println(io, "    \"root_voltage_equality\": \"v_root = V0^2\",")
        println(io, "    \"load_scaling\": \"P_i,t=P_i_case33bw*m_t and Q_i,t=Q_i_case33bw*m_t\"")
        println(io, "  },")
        println(io, "  \"numerical_tolerances\": {")
        println(io, "    \"balance_kw_or_kvar\": ", config.balance_tolerance_kw, ",")
        println(io, "    \"voltage_drop_pu2\": ", config.voltage_drop_tolerance_pu2, ",")
        println(io, "    \"soc_gap_pu2\": ", config.soc_gap_tolerance_pu2, ",")
        println(io, "    \"root_voltage_pu2\": ", config.root_voltage_tolerance_pu2, ",")
        println(io, "    \"ell_pu2\": ", config.ell_tolerance_pu2, ",")
        println(io, "    \"voltage_reporting_pu\": ", config.voltage_tolerance_pu, ",")
        println(io, "    \"zero_pv_export_kw\": ", config.export_tolerance_kw, ",")
        println(io, "    \"ac_voltage_agreement_pu\": ", config.ac_voltage_tolerance_pu, ",")
        println(io, "    \"ac_substation_power_agreement_kw_or_kvar\": ", config.ac_power_tolerance_kw)
        println(io, "  },")
        println(io, "  \"solver\": {")
        println(io, "    \"name\": \"Clarabel\",")
        println(io, "    \"version\": ", _s0_json_string(Base.pkgversion(Clarabel)), ",")
        println(io, "    \"jump_version\": ", _s0_json_string(Base.pkgversion(JuMP)), ",")
        println(io, "    \"julia_version\": ", _s0_json_string(VERSION), ",")
        println(io, "    \"julia_threads\": ", Threads.nthreads(), ",")
        println(io, "    \"method\": \"thread-local reusable one-interval SOCP models with deterministic streamed chunks\",")
        println(io, "    \"chunk_size_intervals\": ", _S0_STREAM_CHUNK_SIZE, ",")
        println(io, "    \"target_tolerance_gap_abs_rel\": 1.0e-9,")
        println(io, "    \"target_tolerance_feasibility\": 1.0e-9,")
        println(io, "    \"reduced_tolerance_gap_abs_rel\": 1.0e-6,")
        println(io, "    \"reduced_tolerance_feasibility\": 1.0e-6,")
        println(io, "    \"objective\": \"minimize active branch losses to tighten the SOCP relaxation\",")
        println(io, "    \"operational_infeasibility_fallback\": \"same SOCP with diagnostic voltage bounds; operational limits remain post-solution validation thresholds\"")
        println(io, "  },")
        println(io, "  \"current_conversion\": {")
        println(io, "    \"verified\": true,")
        println(io, "    \"formula\": \"I_A=sqrt(ell_pu2)*Sbase_VA/(sqrt(3)*Vbase_LL_V)\",")
        println(io, "    \"base_mva\": 10.0,")
        println(io, "    \"base_kv_line_to_line\": 12.66,")
        println(io, "    \"note\": \"This is a unit conversion, not a documented IEEE 33-bus rating.\"")
        println(io, "  },")
        println(io, "  \"ac_validation\": {")
        println(io, "    \"performed\": true,")
        println(io, "    \"method\": \"independent nonlinear radial backward-forward sweep\",")
        println(io, "    \"critical_records_per_root_voltage\": 4")
        println(io, "  },")
        println(io, "  \"runtime_seconds\": ", total_runtime_seconds, ",")
        println(io, "  \"case_solver_runtime_seconds\": [", join(case_solver_runtimes, ", "), "],")
        println(io, "  \"case_fully_validated\": [", join((summary.fully_validated for summary in summaries), ", "), "],")
        println(io, "  \"output_files\": [")
        for (index, filename) in enumerate(output_filenames)
            suffix = index == length(output_filenames) ? "" : ","
            println(io, "    ", _s0_json_string(filename), suffix)
        end
        println(io, "  ]")
        println(io, "}")
    end
end

function _s0_write_report(
    path::AbstractString,
    profile::S0LoadProfile,
    summaries,
    case_solver_runtimes::Vector{Float64},
    total_runtime_seconds::Float64,
    all_ac_passed::Bool,
)
    summary_by_root = Dict(summary.root_voltage_pu => summary for summary in summaries)
    v103 = get(summary_by_root, 1.03, nothing)
    open(path, "w") do io
        println(io, "# S0 full-period baseline validation")
        println(io)
        println(io, "## Scope")
        println(io)
        println(io, "This report covers the zero-DER IEEE 33-bus baseline for every half-hour interval in the processed three-year Ausgrid load profile. PV, EV, BESS, DOE, curtailment, export policy, loss caps, thermal ratings, transformer ratings, and hosting-capacity decisions are absent.")
        println(io)
        println(io, "Ausgrid supplies only the normalized temporal load multiplier. The original case33bw active and reactive bus loads remain the absolute values and are multiplied by the same interval multiplier.")
        println(io)
        println(io, "## Coverage and method")
        println(io)
        println(io, "- Input intervals: $(length(profile.timestamps))")
        println(io, "- Date range: $(_s0_format_timestamp(first(profile.timestamps))) to $(_s0_format_timestamp(last(profile.timestamps)))")
        println(io, "- Time step: $(profile.dt_hours) h")
        println(io, "- Root voltages: 1.00, 1.03, and 1.05 p.u.; the model equality is `v[root] = V0^2`.")
        println(io, "- SOCP strategy: reusable one-interval Clarabel models, partitioned deterministically across $(Threads.nthreads()) Julia threads and streamed in $(_S0_STREAM_CHUNK_SIZE)-interval chunks.")
        println(io, "- Operational voltage limits: 0.95–1.05 p.u. An interval infeasible under the hard band is solved again with diagnostic numerical bounds so the violating buses are recorded rather than silently skipped.")
        println(io, "- SOCP objective: minimize modeled active losses; no loss cap is present.")
        println(io, "- AC validation: independent nonlinear radial backward-forward sweep on four required critical selections per root-voltage case.")
        println(io)
        println(io, "## Results")
        println(io)
        println(io, "| V0 (p.u.) | Solved | Failed | Diagnostic fallbacks | Violation intervals | Vmin (p.u.) | Vmax (p.u.) | Peak branch / current (A) | Peak substation (kVA) | Max loss (kW) | Avg loss (%) | Max SOC gap | Fully validated |")
        println(io, "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|")
        for summary in summaries
            @printf(
                io,
                "| %.2f | %d | %d | %d | %d | %.9f | %.9f | %d / %.6f | %.6f | %.6f | %.6f | %.3e | %s |\n",
                summary.root_voltage_pu,
                summary.solved_intervals,
                summary.solver_failed_intervals,
                summary.operational_model_fallback_intervals,
                summary.intervals_with_voltage_violations,
                summary.global_minimum_voltage_pu,
                summary.global_maximum_voltage_pu,
                summary.peak_branch_id,
                summary.peak_branch_current_a,
                summary.peak_substation_apparent_power_kva,
                summary.maximum_active_losses_kw,
                summary.average_active_loss_percentage,
                summary.maximum_soc_gap_pu2,
                summary.fully_validated ? "yes" : "no",
            )
        end
        println(io)
        println(io, "## Interpretation")
        println(io)
        if v103 === nothing
            println(io, "The requested V0=1.03 p.u. case is unavailable.")
        elseif v103.fully_validated
            println(io, "The V0=1.03 p.u. case is feasible and numerically validated for the complete three-year period under the stated 0.95–1.05 p.u. voltage criterion.")
        else
            println(io, "The V0=1.03 p.u. case is **not** fully feasible over the complete three-year period under the stated 0.95–1.05 p.u. voltage criterion. See `s0_voltage_violations.csv` for the exact bus-time records.")
        end
        println(io)
        println(io, all_ac_passed ?
            "All selected SOCP critical records passed the independent AC comparison tolerances." :
            "At least one selected SOCP critical record did not pass the independent AC comparison tolerances; see `s0_critical_intervals.csv`.")
        println(io)
        println(io, "Peak currents are baseline reference quantities derived from per-unit `ell` using the verified three-phase base-current formula. They are not real or final IEEE 33-bus ampacity ratings. Likewise, peak substation apparent power is a baseline reference, not a documented transformer rating.")
        println(io)
        println(io, "No `κ_I` or `κ_tr` planning multiplier is selected here.")
        println(io)
        println(io, "## Runtime")
        println(io)
        @printf(io, "Total runtime: %.3f s. Case solve runtimes: %s s.\n", total_runtime_seconds, join((@sprintf("%.3f", value) for value in case_solver_runtimes), ", "))
    end
end

function _run_s0_full_period_baseline(
    input_path::AbstractString,
    output_directory::AbstractString;
    config::S0BaselineConfig=S0BaselineConfig(),
    repository_commit::AbstractString="unknown",
)
    profile = _read_ausgrid_s0_load_profile(
        input_path;
        expected_intervals=config.expected_intervals,
        expected_dt_hours=config.dt_hours,
    )
    profile.dt_hours == config.dt_hours || throw(ArgumentError("S0 input time step does not match configuration"))
    config.pv_capacity_kw == 0.0 || throw(ArgumentError("S0 PV capacity must be zero"))
    config.ev_load_kw == 0.0 || throw(ArgumentError("S0 EV load must be zero"))
    config.bess_charge_kw == 0.0 && config.bess_discharge_kw == 0.0 ||
        throw(ArgumentError("S0 BESS power must be zero"))
    !config.no_export_constraint_active || throw(ArgumentError("S0 no-export constraint must be disabled"))
    !config.loss_cap_constraint_active || throw(ArgumentError("S0 loss-cap constraint must be disabled"))

    mkpath(output_directory)
    paths = Dict(
        "s0_summary.csv" => joinpath(output_directory, "s0_summary.csv"),
        "s0_interval_metrics.csv" => joinpath(output_directory, "s0_interval_metrics.csv"),
        "s0_branch_peak_metrics.csv" => joinpath(output_directory, "s0_branch_peak_metrics.csv"),
        "s0_voltage_violations.csv" => joinpath(output_directory, "s0_voltage_violations.csv"),
        "s0_solver_failures.csv" => joinpath(output_directory, "s0_solver_failures.csv"),
        "s0_critical_intervals.csv" => joinpath(output_directory, "s0_critical_intervals.csv"),
        "s0_metadata.json" => joinpath(output_directory, "s0_metadata.json"),
        "s0_report.md" => joinpath(output_directory, "s0_report.md"),
    )

    interval_io = open(paths["s0_interval_metrics.csv"], "w")
    branch_io = open(paths["s0_branch_peak_metrics.csv"], "w")
    violation_io = open(paths["s0_voltage_violations.csv"], "w")
    failure_io = open(paths["s0_solver_failures.csv"], "w")
    critical_io = open(paths["s0_critical_intervals.csv"], "w")
    summaries = NamedTuple[]
    case_solver_runtimes = Float64[]
    ac_passed_records = 0
    total_started = time()
    try
        _s0_write_csv_header(interval_io, S0_INTERVAL_METRIC_COLUMNS)
        _s0_write_csv_header(branch_io, S0_BRANCH_PEAK_COLUMNS)
        _s0_write_csv_header(violation_io, S0_VOLTAGE_VIOLATION_COLUMNS)
        _s0_write_csv_header(failure_io, S0_SOLVER_FAILURE_COLUMNS)
        _s0_write_csv_header(critical_io, S0_CRITICAL_INTERVAL_COLUMNS)

        for root_voltage_pu in config.root_voltages_pu
            println("S0 full-period solve started for V0=$(root_voltage_pu) p.u. using $(Threads.nthreads()) threads")
            summary, case_ac_passed, solver_runtime = _s0_solve_and_process_case_streamed!(
                interval_io,
                branch_io,
                violation_io,
                failure_io,
                critical_io,
                profile,
                root_voltage_pu,
                config,
            )
            push!(case_solver_runtimes, solver_runtime)
            push!(summaries, summary)
            ac_passed_records += case_ac_passed
            println(
                "S0 V0=$(root_voltage_pu) completed: solved=$(summary.solved_intervals), " *
                "failed=$(summary.solver_failed_intervals), voltage_violation_intervals=$(summary.intervals_with_voltage_violations)",
            )
            GC.gc()
        end
    finally
        close(interval_io)
        close(branch_io)
        close(violation_io)
        close(failure_io)
        close(critical_io)
    end

    total_runtime_seconds = time() - total_started
    open(paths["s0_summary.csv"], "w") do io
        _s0_write_csv_header(io, S0_SUMMARY_COLUMNS)
        for summary in summaries
            _s0_write_csv_row(io, (getfield(summary, Symbol(column)) for column in S0_SUMMARY_COLUMNS))
        end
    end
    output_filenames = sort(collect(keys(paths)))
    _s0_write_metadata(
        paths["s0_metadata.json"],
        profile,
        config,
        summaries,
        case_solver_runtimes,
        total_runtime_seconds,
        repository_commit,
        output_filenames,
    )
    all_ac_passed = ac_passed_records == 4 * length(config.root_voltages_pu)
    _s0_write_report(
        paths["s0_report.md"],
        profile,
        summaries,
        case_solver_runtimes,
        total_runtime_seconds,
        all_ac_passed,
    )

    any(summary.zero_pv_export_intervals > 0 for summary in summaries) &&
        throw(ArgumentError("zero-PV substation export detected; inspect generated S0 outputs"))
    any(summary.solver_failed_intervals > 0 for summary in summaries) &&
        @warn "S0 solver failures were recorded; the affected cases are not fully validated"
    any(summary.maximum_soc_gap_pu2 > config.soc_gap_tolerance_pu2 for summary in summaries) &&
        @warn "material S0 SOCP gap detected; affected cases are not fully validated"

    return (
        profile=profile,
        summaries=summaries,
        case_solver_runtimes=case_solver_runtimes,
        total_runtime_seconds=total_runtime_seconds,
        ac_validation_passed=all_ac_passed,
        output_paths=paths,
    )
end
