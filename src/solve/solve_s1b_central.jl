using JuMP
using Clarabel
using Dates
using SHA

const S1B_CANDIDATE_BUSES = (13, 20, 24, 30)
const S1B_EXPECTED_FULL_INTERVALS = 52_608
const S1B_EXPECTED_INITIAL_DAYS = 32
const S1B_INTERVALS_PER_DAY = 48
const S1B_ROOT_VOLTAGE_PU = 1.00
const S1B_VMIN_PU = 0.90
const S1B_VMAX_PU = 1.05

struct S1BProfile
    timestamps::Vector{DateTime}
    load_multiplier::Vector{Float64}
    pv_profile::Vector{Float64}
    source_path::String
    source_sha256::String
end

struct S1BCentralModel
    model::JuMP.Model
    capacity_kw::Any
    network::SOCPNetworkVariables
    data::CaseData
    full_indices::Vector{Int}
end

struct S1BCentralSolution
    termination_status::String
    primal_status::String
    dual_status::String
    objective_bound::Float64
    has_primal::Bool
    capacities_kw::Dict{Int,Float64}
    total_capacity_kw::Float64
    bundle::S1BCentralModel
end

function _s1b_sha256(path::AbstractString)
    return bytes2hex(open(SHA.sha256, path))
end

function _read_s1b_profile(
    path::AbstractString;
    expected_intervals::Integer=S1B_EXPECTED_FULL_INTERVALS,
)
    isfile(path) || throw(ArgumentError("S1-B profile does not exist: $path"))
    timestamps = DateTime[]
    load_multiplier = Float64[]
    pv_profile = Float64[]
    open(path, "r") do io
        eof(io) && throw(ArgumentError("S1-B profile is empty"))
        header = split(chomp(readline(io)), ',')
        ti = findfirst(==("datetime"), header)
        li = findfirst(==("load_multiplier"), header)
        pi = findfirst(==("pv_profile"), header)
        any(isnothing, (ti, li, pi)) && throw(ArgumentError(
            "S1-B profile must contain datetime, load_multiplier, and pv_profile",
        ))
        for (row_number, line) in enumerate(eachline(io))
            fields = split(line, ',')
            length(fields) == length(header) || throw(ArgumentError(
                "S1-B profile column mismatch at row $row_number",
            ))
            timestamp = try
                DateTime(fields[ti], dateformat"yyyy-mm-dd HH:MM:SS")
            catch
                throw(ArgumentError("invalid S1-B timestamp at row $row_number"))
            end
            load = tryparse(Float64, fields[li])
            pv = tryparse(Float64, fields[pi])
            load === nothing && throw(ArgumentError("invalid load multiplier at row $row_number"))
            pv === nothing && throw(ArgumentError("invalid PV profile at row $row_number"))
            isfinite(load) && load >= 0.0 || throw(ArgumentError("invalid load multiplier at row $row_number"))
            isfinite(pv) && pv >= 0.0 || throw(ArgumentError("invalid PV profile at row $row_number"))
            push!(timestamps, timestamp)
            push!(load_multiplier, load)
            push!(pv_profile, pv)
        end
    end
    length(timestamps) == Int(expected_intervals) || throw(ArgumentError(
        "S1-B profile interval mismatch: expected $expected_intervals, found $(length(timestamps))",
    ))
    length(unique(timestamps)) == length(timestamps) || throw(ArgumentError("duplicate S1-B timestamps"))
    issorted(timestamps) || throw(ArgumentError("S1-B timestamps are not monotonic"))
    all(diff(timestamps) .== Minute(30)) || throw(ArgumentError("S1-B profile is not half-hourly"))
    return S1BProfile(
        timestamps,
        load_multiplier,
        pv_profile,
        abspath(path),
        _s1b_sha256(path),
    )
end

function _read_s1b_initial_indices(
    profile::S1BProfile,
    audit_path::AbstractString;
    expected_days::Integer=S1B_EXPECTED_INITIAL_DAYS,
)
    isfile(audit_path) || throw(ArgumentError("S1-B audit candidates do not exist: $audit_path"))
    dates = Date[]
    open(audit_path, "r") do io
        eof(io) && throw(ArgumentError("S1-B audit candidates are empty"))
        header = split(chomp(readline(io)), ',')
        date_index = findfirst(==("date"), header)
        date_index === nothing && throw(ArgumentError("S1-B audit candidates have no date column"))
        for (row_number, line) in enumerate(eachline(io))
            fields = split(line, ',')
            length(fields) == length(header) || throw(ArgumentError("audit column mismatch at row $row_number"))
            push!(dates, try
                Date(fields[date_index], dateformat"yyyy-mm-dd")
            catch
                throw(ArgumentError("invalid audit date at row $row_number"))
            end)
        end
    end
    length(dates) == Int(expected_days) || throw(ArgumentError(
        "S1-B audit must contain $expected_days rows; found $(length(dates))",
    ))
    length(unique(dates)) == length(dates) || throw(ArgumentError("S1-B audit dates are not unique"))
    wanted = Set(dates)
    indices = findall(timestamp -> Date(timestamp) in wanted, profile.timestamps)
    length(indices) == length(dates) * S1B_INTERVALS_PER_DAY || throw(ArgumentError(
        "S1-B initial set must contain $(length(dates) * S1B_INTERVALS_PER_DAY) intervals; found $(length(indices))",
    ))
    counts = Dict(date => count(i -> Date(profile.timestamps[i]) == date, indices) for date in dates)
    all(==(S1B_INTERVALS_PER_DAY), values(counts)) || throw(ArgumentError(
        "every S1-B audit day must contain exactly $S1B_INTERVALS_PER_DAY intervals",
    ))
    return sort(indices)
end

function _s1b_case(profile::S1BProfile, full_indices::Vector{Int})
    isempty(full_indices) && throw(ArgumentError("S1-B optimization set cannot be empty"))
    all(i -> 1 <= i <= length(profile.timestamps), full_indices) ||
        throw(ArgumentError("S1-B optimization index is outside the profile"))
    length(unique(full_indices)) == length(full_indices) || throw(ArgumentError("duplicate S1-B indices"))
    buses, branches = build_ieee33_network()
    timeseries = TimeSeries(
        length(full_indices),
        0.5,
        profile.load_multiplier[full_indices],
        profile.pv_profile[full_indices],
        zeros(length(full_indices)),
        zeros(length(full_indices)),
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
        S1B_VMIN_PU,
        S1B_VMAX_PU,
    )
    check_data_consistency(data)
    return data
end

function _build_s1b_central_model(
    profile::S1BProfile,
    full_indices::AbstractVector{<:Integer};
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
)
    indices = sort(unique(Int.(full_indices)))
    data = _s1b_case(profile, indices)
    model = JuMP.Model(optimizer)
    silent && JuMP.set_silent(model)
    @variable(model, pv_capacity_kw[bus in S1B_CANDIDATE_BUSES] >= 0.0)
    times = 1:data.timeseries.T
    injection_by_bus_kw = Dict(
        bus.id => [JuMP.AffExpr(0.0) for _ in times]
        for bus in data.buses
    )
    for bus in S1B_CANDIDATE_BUSES, t in times
        injection_by_bus_kw[bus][t] = data.timeseries.pv_profile[t] * pv_capacity_kw[bus]
    end
    network = add_socp_branch_flow_constraints!(
        model,
        data,
        injection_by_bus_kw;
        root_bus=1,
        root_voltage_pu=S1B_ROOT_VOLTAGE_PU,
    )
    @objective(model, Max, sum(pv_capacity_kw[bus] for bus in S1B_CANDIDATE_BUSES))
    return S1BCentralModel(model, pv_capacity_kw, network, data, indices)
end

function _s1b_has_primal(model::JuMP.Model)
    return try
        JuMP.has_values(model)
    catch
        false
    end
end

function _solve_s1b_central(
    profile::S1BProfile,
    full_indices::AbstractVector{<:Integer};
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
)
    bundle = _build_s1b_central_model(profile, full_indices; optimizer=optimizer, silent=silent)
    JuMP.optimize!(bundle.model)
    has_primal = _s1b_has_primal(bundle.model)
    capacities = has_primal ? Dict(
        bus => Float64(JuMP.value(bundle.capacity_kw[bus]))
        for bus in S1B_CANDIDATE_BUSES
    ) : Dict{Int,Float64}()
    bound = try
        Float64(JuMP.objective_bound(bundle.model))
    catch
        NaN
    end
    if !isfinite(bound) && has_primal
        bound = try
            Float64(JuMP.objective_value(bundle.model))
        catch
            NaN
        end
    end
    return S1BCentralSolution(
        string(JuMP.termination_status(bundle.model)),
        string(JuMP.primal_status(bundle.model)),
        string(JuMP.dual_status(bundle.model)),
        bound,
        has_primal,
        capacities,
        has_primal ? sum(values(capacities)) : NaN,
        bundle,
    )
end

function _s1b_ac_state(
    profile::S1BProfile,
    index::Int,
    capacities_kw::Dict{Int,Float64};
    tolerance_pu::Float64=1e-11,
    maximum_iterations::Int=2000,
    damping::Float64=0.70,
)
    buses, branches = build_ieee33_network()
    topology = _s0_unconstrained_topology(buses, branches; root_bus=1)
    base_kw = 10_000.0
    bus_by_id = Dict(bus.id => bus for bus in buses)
    branch_by_id = Dict(branch.id => branch for branch in branches)
    net_load_pu = zeros(ComplexF64, length(buses))
    for bus in buses
        injected_kw = get(capacities_kw, bus.id, 0.0) * profile.pv_profile[index]
        net_load_pu[bus.id] = complex(
            bus.pd_kw * profile.load_multiplier[index] - injected_kw,
            bus.qd_kvar * profile.load_multiplier[index],
        ) / base_kw
    end
    impedance_pu = zeros(ComplexF64, length(branches))
    for branch_id in eachindex(impedance_pu)
        branch = branch_by_id[branch_id]
        zbase = bus_by_id[topology.branch_from[branch_id]].base_kv^2 / 10.0
        impedance_pu[branch_id] = complex(branch.r_ohm, branch.x_ohm) / zbase
    end
    voltage = fill(complex(S1B_ROOT_VOLTAGE_PU, 0.0), length(buses))
    converged = false
    iterations = 0
    for iteration in 1:maximum_iterations
        iterations = iteration
        currents = _s0_unconstrained_branch_currents(topology, voltage, net_load_pu)
        currents === nothing && break
        branch_current, _ = currents
        fixed = _s0_unconstrained_forward_voltage(
            topology, impedance_pu, branch_current, S1B_ROOT_VOLTAGE_PU,
        )
        update = maximum(abs.(fixed .- voltage))
        voltage .= damping .* fixed .+ (1.0 - damping) .* voltage
        voltage[1] = complex(S1B_ROOT_VOLTAGE_PU, 0.0)
        if update <= tolerance_pu
            voltage .= fixed
            converged = true
            break
        end
    end
    if !converged
        return (
            index=index, converged=false, iterations=iterations, voltages=abs.(voltage),
            vmin=minimum(abs.(voltage)), vmin_bus=argmin(abs.(voltage)),
            vmax=maximum(abs.(voltage)), vmax_bus=argmax(abs.(voltage)),
            substation_p_kw=NaN, substation_q_kvar=NaN,
            active_losses_kw=NaN, reactive_losses_kvar=NaN, loss_ratio_percent=NaN,
        )
    end
    branch_current, _ = something(_s0_unconstrained_branch_currents(topology, voltage, net_load_pu))
    branch_power = zeros(ComplexF64, length(branches))
    losses = 0.0 + 0.0im
    for branch_id in eachindex(branch_current)
        from_bus = topology.branch_from[branch_id]
        branch_power[branch_id] = voltage[from_bus] * conj(branch_current[branch_id]) * base_kw
        losses += impedance_pu[branch_id] * abs2(branch_current[branch_id]) * base_kw
    end
    root_branches = [topology.parent_branch[child] for child in topology.children[1]]
    substation = sum(branch_power[root_branches])
    total_load_kw = sum(bus.pd_kw for bus in buses) * profile.load_multiplier[index]
    magnitudes = abs.(voltage)
    return (
        index=index, converged=true, iterations=iterations, voltages=magnitudes,
        vmin=minimum(magnitudes), vmin_bus=argmin(magnitudes),
        vmax=maximum(magnitudes), vmax_bus=argmax(magnitudes),
        substation_p_kw=real(substation), substation_q_kvar=imag(substation),
        active_losses_kw=real(losses), reactive_losses_kvar=imag(losses),
        loss_ratio_percent=100.0 * real(losses) / total_load_kw,
    )
end

function _validate_s1b_ac(
    profile::S1BProfile,
    capacities_kw::Dict{Int,Float64};
    voltage_tolerance_pu::Real=1e-7,
)
    tolerance = Float64(voltage_tolerance_pu)
    states = Vector{Any}(undef, length(profile.timestamps))
    Threads.@threads for index in eachindex(profile.timestamps)
        states[index] = _s1b_ac_state(profile, index, capacities_kw)
    end
    converged_indices = [i for i in eachindex(states) if states[i].converged]
    failed_indices = [i for i in eachindex(states) if !states[i].converged]
    under_indices = [i for i in converged_indices if states[i].vmin < S1B_VMIN_PU - tolerance]
    over_indices = [i for i in converged_indices if states[i].vmax > S1B_VMAX_PU + tolerance]
    global_min_index = isempty(converged_indices) ? 0 : argmin(i -> states[i].vmin, converged_indices)
    global_max_index = isempty(converged_indices) ? 0 : argmax(i -> states[i].vmax, converged_indices)
    max_import_index = isempty(converged_indices) ? 0 : argmax(i -> states[i].substation_p_kw, converged_indices)
    max_export_index = isempty(converged_indices) ? 0 : argmin(i -> states[i].substation_p_kw, converged_indices)
    max_loss_index = isempty(converged_indices) ? 0 : argmax(i -> states[i].active_losses_kw, converged_indices)
    finite_loss_ratio_indices = [
        i for i in converged_indices if isfinite(states[i].loss_ratio_percent)
    ]
    max_loss_ratio_index = isempty(finite_loss_ratio_indices) ? 0 :
                           argmax(i -> states[i].loss_ratio_percent, finite_loss_ratio_indices)
    return (
        states=states,
        converged_indices=converged_indices,
        failed_indices=failed_indices,
        under_indices=under_indices,
        over_indices=over_indices,
        global_min_index=global_min_index,
        global_max_index=global_max_index,
        max_import_index=max_import_index,
        max_export_index=max_export_index,
        max_loss_index=max_loss_index,
        max_loss_ratio_index=max_loss_ratio_index,
        undefined_loss_ratio_indices=[
            i for i in converged_indices if !isfinite(states[i].loss_ratio_percent)
        ],
    )
end
