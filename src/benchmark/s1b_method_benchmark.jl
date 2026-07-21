module S1BMethodBenchmark

using CiroPVHC
using JuMP
using Ipopt
using Clarabel
using Dates
using Random
using Printf

const MOI = JuMP.MOI

CiroPVHC._load_s1b_solver!()

const BENCHMARK_DATE = Date(2010, 12, 21)
const CANDIDATE_BUSES = (13, 20, 24, 30)
const PENALTY_LAMBDAS = (0.0, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0)
const ROOT_VOLTAGE_PU = 1.0
const VMIN_PU = 0.90
const VMAX_PU = 1.05
const EXACTNESS_SOC_TOL = 1e-5
const AC_VOLTAGE_TOL = 1e-5
const SOCP_AC_VOLTAGE_TOL = 1e-4
const AC_RESIDUAL_TOL = 1e-5
const MULTISTART_SEED = 20260721

struct BenchmarkData
    profile::Any
    indices::Vector{Int}
    buses::Vector{CiroPVHC.Bus}
    branches::Vector{CiroPVHC.Branch}
    topology::Any
    r_pu::Vector{Float64}
    x_pu::Vector{Float64}
    base_power_kw::Float64
    normalization_power_kw::Float64
end

const ExactACState = CiroPVHC.S1BIndependentReplayState

function load_benchmark_data(repository_root::AbstractString)
    profile = CiroPVHC.read_s1b_profile(joinpath(
        repository_root, "data_processed", "ausgrid", "ausgrid_halfhour_normalized.csv",
    ))
    indices = findall(timestamp -> Date(timestamp) == BENCHMARK_DATE, profile.timestamps)
    length(indices) == 48 || throw(ArgumentError(
        "benchmark date $(BENCHMARK_DATE) must contain exactly 48 intervals; found $(length(indices))",
    ))
    all(diff(profile.timestamps[indices]) .== Minute(30)) ||
        throw(ArgumentError("benchmark intervals are not contiguous half-hours"))
    buses, branches = CiroPVHC.build_ieee33_network()
    topology = CiroPVHC._s0_unconstrained_topology(buses, branches; root_bus=1)
    bus_by_id = Dict(bus.id => bus for bus in buses)
    branch_by_id = Dict(branch.id => branch for branch in branches)
    r_pu = zeros(length(branches))
    x_pu = zeros(length(branches))
    for branch_id in eachindex(branches)
        branch = branch_by_id[branch_id]
        zbase = bus_by_id[topology.branch_from[branch_id]].base_kv^2 / 10.0
        r_pu[branch_id] = branch.r_ohm / zbase
        x_pu[branch_id] = branch.x_ohm / zbase
    end
    base_power_kw = 10_000.0
    normalization_power_kw = sum(bus.pd_kw for bus in buses)
    return BenchmarkData(
        profile,
        indices,
        buses,
        branches,
        topology,
        r_pu,
        x_pu,
        base_power_kw,
        normalization_power_kw,
    )
end

function effective_configuration(data::BenchmarkData)
    return (
        date=BENCHMARK_DATE,
        interval_count=length(data.indices),
        candidate_buses=CANDIDATE_BUSES,
        shared_capacity_vector=true,
        curtailment_active=false,
        export_allowed=true,
        no_export_active=false,
        site_cap_active=false,
        gamma_cap_active=false,
        thermal_constraints_active=false,
        loss_cap_active=false,
        computational_capacity_bound_active=false,
        root_voltage_pu=ROOT_VOLTAGE_PU,
        voltage_min_pu=VMIN_PU,
        voltage_max_pu=VMAX_PU,
        squared_voltage_min=VMIN_PU^2,
        squared_voltage_max=VMAX_PU^2,
        objective="maximize C13 + C20 + C24 + C30",
        ac_equality="P^2 + Q^2 = v * ell",
        socp_relaxation="P^2 + Q^2 <= v * ell",
        normalization_power_kw=data.normalization_power_kw,
        normalized_hc="sum(C) / nominal_case_active_load_kw",
        normalized_penalty="mean_interval_active_loss_kw / nominal_case_active_load_kw",
        penalty_lambdas=PENALTY_LAMBDAS,
        exactness_soc_tolerance=EXACTNESS_SOC_TOL,
        ac_voltage_tolerance_pu=AC_VOLTAGE_TOL,
        socp_ac_voltage_tolerance_pu=SOCP_AC_VOLTAGE_TOL,
        multistart_seed=MULTISTART_SEED,
    )
end

function _net_load_pu(data::BenchmarkData, local_t::Int, capacities_kw::Dict{Int,Float64})
    global_index = data.indices[local_t]
    load_multiplier = data.profile.load_multiplier[global_index]
    pv_factor = data.profile.pv_profile[global_index]
    net_load = zeros(ComplexF64, length(data.buses))
    for bus in data.buses
        injection_kw = get(capacities_kw, bus.id, 0.0) * pv_factor
        net_load[bus.id] = complex(
            bus.pd_kw * load_multiplier - injection_kw,
            bus.qd_kvar * load_multiplier,
        ) / data.base_power_kw
    end
    return net_load
end

function exact_ac_state(
    data::BenchmarkData,
    local_t::Int,
    capacities_kw::Dict{Int,Float64};
    tolerance_pu::Float64=1e-12,
    maximum_iterations::Int=4000,
    damping::Float64=0.70,
)
    global_index = data.indices[local_t]
    return CiroPVHC.replay_s1b_interval(
        data.buses,
        data.branches,
        data.profile.load_multiplier[global_index],
        data.profile.pv_profile[global_index],
        capacities_kw;
        base_mva=data.base_power_kw / 1000.0,
        root_voltage_pu=ROOT_VOLTAGE_PU,
        vmin_pu=VMIN_PU,
        vmax_pu=VMAX_PU,
        tolerance_pu=tolerance_pu,
        voltage_tolerance_pu=AC_VOLTAGE_TOL,
        residual_tolerance_pu=AC_RESIDUAL_TOL,
        maximum_iterations=maximum_iterations,
        damping=damping,
    )
end

function validate_capacities(
    data::BenchmarkData,
    capacities_kw::Dict{Int,Float64};
    voltage_tolerance_pu::Float64=AC_VOLTAGE_TOL,
)
    states = [exact_ac_state(data, local_t, capacities_kw) for local_t in 1:length(data.indices)]
    converged = all(state.converged for state in states)
    if !converged
        return (
            states=states, converged=false, failed=count(state -> !state.converged, states),
            ac_feasible=false, vmin=NaN, vmax=NaN, undervoltage_count=0,
            overvoltage_count=0, undervoltage_intervals=0, overvoltage_intervals=0,
            max_import_kw=NaN, max_export_kw=NaN,
            max_active_losses_kw=NaN, max_reactive_losses_kvar=NaN,
            max_equation_residual=Inf, max_scaled_residual=Inf,
            phasor_recoverable=false, replay_passed=false,
        )
    end
    vmin = minimum(minimum(state.voltage_pu) for state in states)
    vmax = maximum(maximum(state.voltage_pu) for state in states)
    undervoltage_count = sum(
        count(v -> v < VMIN_PU - voltage_tolerance_pu, state.voltage_pu) for state in states
    )
    overvoltage_count = sum(
        count(v -> v > VMAX_PU + voltage_tolerance_pu, state.voltage_pu) for state in states
    )
    undervoltage_intervals = count(
        state -> any(v -> v < VMIN_PU - voltage_tolerance_pu, state.voltage_pu), states,
    )
    overvoltage_intervals = count(
        state -> any(v -> v > VMAX_PU + voltage_tolerance_pu, state.voltage_pu), states,
    )
    return (
        states=states,
        converged=true,
        failed=0,
        ac_feasible=undervoltage_count == 0 && overvoltage_count == 0,
        vmin=vmin,
        vmax=vmax,
        undervoltage_count=undervoltage_count,
        overvoltage_count=overvoltage_count,
        undervoltage_intervals=undervoltage_intervals,
        overvoltage_intervals=overvoltage_intervals,
        max_import_kw=maximum(max(state.substation_p_kw, 0.0) for state in states),
        max_export_kw=maximum(max(-state.substation_p_kw, 0.0) for state in states),
        max_active_losses_kw=maximum(state.active_losses_kw for state in states),
        max_reactive_losses_kvar=maximum(state.reactive_losses_kvar for state in states),
        max_equation_residual=maximum(state.maximum_equation_residual for state in states),
        max_scaled_residual=maximum(state.maximum_scaled_residual for state in states),
        phasor_recoverable=all(state.phasor_recoverable for state in states),
        replay_passed=all(
            state.voltage_limits_satisfied && state.phasor_recoverable &&
            state.maximum_equation_residual <= AC_RESIDUAL_TOL
            for state in states
        ),
    )
end

function _direction_limit(data::BenchmarkData, direction::Vector{Float64})
    length(direction) == length(CANDIDATE_BUSES) || throw(ArgumentError("invalid direction"))
    isapprox(sum(direction), 1.0; atol=1e-12) || throw(ArgumentError("direction must sum to one"))
    all(x -> x >= 0.0, direction) || throw(ArgumentError("direction must be nonnegative"))
    feasible(total_kw) = validate_capacities(
        data,
        Dict(bus => total_kw * direction[i] for (i, bus) in enumerate(CANDIDATE_BUSES));
        voltage_tolerance_pu=0.0,
    ).ac_feasible
    lower = 0.0
    upper = data.normalization_power_kw
    feasible(lower) || throw(ArgumentError("zero-PV benchmark state is infeasible"))
    bracketed = false
    for _ in 1:30
        if feasible(upper)
            lower = upper
            upper *= 2.0
        else
            bracketed = true
            break
        end
    end
    bracketed || throw(ArgumentError(
        "failed to bracket an AC voltage boundary after 30 doublings; no model cap was added",
    ))
    for _ in 1:45
        middle = (lower + upper) / 2.0
        if feasible(middle)
            lower = middle
        else
            upper = middle
        end
    end
    return lower
end

function multistart_directions(; seed::Int=MULTISTART_SEED)
    rng = MersenneTwister(seed)
    prior = [0.04, 0.40, 0.41, 0.15]
    directions = Pair{String,Vector{Float64}}[
        "uniform" => fill(0.25, 4),
        "prior_socp_pattern" => prior ./ sum(prior),
        "tilt_bus13" => [0.55, 0.15, 0.15, 0.15],
        "tilt_bus20" => [0.15, 0.55, 0.15, 0.15],
        "tilt_bus24" => [0.15, 0.15, 0.55, 0.15],
        "tilt_bus30" => [0.15, 0.15, 0.15, 0.55],
    ]
    for random_index in 1:4
        raw = rand(rng, 4) .+ 0.05
        push!(directions, "random_$(random_index)" => raw ./ sum(raw))
    end
    return directions
end

function multistart_specs(data::BenchmarkData; seed::Int=MULTISTART_SEED)
    directions = multistart_directions(; seed=seed)
    limit_by_name = Dict(name => _direction_limit(data, direction) for (name, direction) in directions)
    specs = NamedTuple[]
    push!(specs, (
        name="zero_pv", kind="zero", seed=seed, capacities_kw=zeros(4),
        direction_limit_kw=limit_by_name["uniform"], scale_fraction=0.0,
    ))
    for (name, fraction, kind) in (
        ("uniform_small", 0.20, "small_feasible"),
        ("uniform_medium", 0.60, "medium_feasible"),
        ("uniform_near_boundary", 0.92, "scaled_feasible"),
    )
        direction = directions[1].second
        limit = limit_by_name["uniform"]
        push!(specs, (
            name=name, kind=kind, seed=seed,
            capacities_kw=direction .* (fraction * limit),
            direction_limit_kw=limit, scale_fraction=fraction,
        ))
    end
    for (name, direction) in directions[2:end]
        fraction = startswith(name, "random") ? 0.85 : 0.90
        limit = limit_by_name[name]
        push!(specs, (
            name=name * "_scaled", kind=startswith(name, "random") ? "seeded_perturbation" : "scaled_feasible",
            seed=seed, capacities_kw=direction .* (fraction * limit),
            direction_limit_kw=limit, scale_fraction=fraction,
        ))
    end
    length(specs) >= 10 || error("benchmark requires at least ten starts")
    return specs
end

function build_ac_opf_model(data::BenchmarkData; silent::Bool=true)
    model = Model(Ipopt.Optimizer)
    set_optimizer_attribute(model, "tol", 1e-9)
    set_optimizer_attribute(model, "constr_viol_tol", 1e-8)
    set_optimizer_attribute(model, "acceptable_tol", 1e-7)
    set_optimizer_attribute(model, "max_iter", 4000)
    set_optimizer_attribute(model, "print_level", silent ? 0 : 5)
    times = 1:length(data.indices)
    branch_ids = 1:length(data.branches)
    bus_ids = 1:length(data.buses)
    @variable(model, capacity_kw[bus in CANDIDATE_BUSES] >= 0.0)
    @variable(model, P[branch_ids, times])
    @variable(model, Q[branch_ids, times])
    @variable(model, VMIN_PU^2 <= v[bus_ids, times] <= VMAX_PU^2)
    @variable(model, ell[branch_ids, times] >= 0.0)
    for t in times
        @constraint(model, v[1, t] == ROOT_VOLTAGE_PU^2)
    end
    for branch_id in branch_ids, t in times
        i = data.topology.branch_from[branch_id]
        j = data.topology.branch_to[branch_id]
        r = data.r_pu[branch_id]
        x = data.x_pu[branch_id]
        @constraint(model,
            v[j, t] == v[i, t] - 2.0 * (r * P[branch_id, t] + x * Q[branch_id, t]) +
                       (r^2 + x^2) * ell[branch_id, t])
        @constraint(model, P[branch_id, t]^2 + Q[branch_id, t]^2 == v[i, t] * ell[branch_id, t])
    end
    bus_by_id = Dict(bus.id => bus for bus in data.buses)
    for bus_id in bus_ids
        bus_id == 1 && continue
        incoming = data.topology.parent_branch[bus_id]
        child_branches = [data.topology.parent_branch[child] for child in data.topology.children[bus_id]]
        bus = bus_by_id[bus_id]
        for t in times
            global_index = data.indices[t]
            load_multiplier = data.profile.load_multiplier[global_index]
            pv_factor = data.profile.pv_profile[global_index]
            child_p = sum((P[branch, t] for branch in child_branches); init=0.0)
            child_q = sum((Q[branch, t] for branch in child_branches); init=0.0)
            injection = bus_id in CANDIDATE_BUSES ? pv_factor * capacity_kw[bus_id] : 0.0
            @constraint(model,
                P[incoming, t] - data.r_pu[incoming] * ell[incoming, t] - child_p ==
                (bus.pd_kw * load_multiplier - injection) / data.base_power_kw)
            @constraint(model,
                Q[incoming, t] - data.x_pu[incoming] * ell[incoming, t] - child_q ==
                bus.qd_kvar * load_multiplier / data.base_power_kw)
        end
    end
    @objective(model, Max, sum(capacity_kw[bus] for bus in CANDIDATE_BUSES))
    return (
        model=model, capacity_kw=capacity_kw, P=P, Q=Q, v=v, ell=ell,
        exact_current_equality=true, interval_count=length(times),
        shared_capacity_variable_count=length(CANDIDATE_BUSES),
        computational_capacity_bound_active=false,
    )
end

function initialize_ac_model!(bundle, data::BenchmarkData, capacities::Vector{Float64})
    capacity_dict = Dict(bus => capacities[i] for (i, bus) in enumerate(CANDIDATE_BUSES))
    validation = validate_capacities(data, capacity_dict; voltage_tolerance_pu=0.0)
    validation.converged || throw(ArgumentError("AC initial point did not converge"))
    for (i, bus) in enumerate(CANDIDATE_BUSES)
        set_start_value(bundle.capacity_kw[bus], capacities[i])
    end
    for t in 1:length(data.indices)
        state = validation.states[t]
        for bus in 1:length(data.buses)
            set_start_value(bundle.v[bus, t], state.voltage_pu[bus]^2)
        end
        for branch in 1:length(data.branches)
            set_start_value(bundle.P[branch, t], state.branch_p_pu[branch])
            set_start_value(bundle.Q[branch, t], state.branch_q_pu[branch])
            set_start_value(bundle.ell[branch, t], state.branch_ell_pu2[branch])
        end
    end
    return validation
end

function _iteration_count(model::Model)
    return try
        MOI.get(backend(model), MOI.BarrierIterations())
    catch
        -1
    end
end

function _solve_time(model::Model)
    return try
        solve_time(model)
    catch
        NaN
    end
end

function ac_solution_diagnostics(bundle, data::BenchmarkData)
    capacities = Dict(bus => value(bundle.capacity_kw[bus]) for bus in CANDIDATE_BUSES)
    max_active_balance = 0.0
    max_reactive_balance = 0.0
    max_voltage_drop = 0.0
    max_current_equality = 0.0
    max_root = 0.0
    vmin = Inf
    vmax = -Inf
    nlp_voltage = Vector{Vector{Float64}}(undef, length(data.indices))
    for t in 1:length(data.indices)
        nlp_voltage[t] = [sqrt(max(0.0, value(bundle.v[bus, t]))) for bus in 1:length(data.buses)]
        vmin = min(vmin, minimum(nlp_voltage[t]))
        vmax = max(vmax, maximum(nlp_voltage[t]))
        max_root = max(max_root, abs(value(bundle.v[1, t]) - ROOT_VOLTAGE_PU^2))
        for branch in 1:length(data.branches)
            i = data.topology.branch_from[branch]
            j = data.topology.branch_to[branch]
            p = value(bundle.P[branch, t])
            q = value(bundle.Q[branch, t])
            ell = value(bundle.ell[branch, t])
            vi = value(bundle.v[i, t])
            vj = value(bundle.v[j, t])
            r = data.r_pu[branch]
            x = data.x_pu[branch]
            max_voltage_drop = max(max_voltage_drop,
                abs(vj - vi + 2.0 * (r * p + x * q) - (r^2 + x^2) * ell))
            max_current_equality = max(max_current_equality, abs(p^2 + q^2 - vi * ell))
        end
        global_index = data.indices[t]
        load_multiplier = data.profile.load_multiplier[global_index]
        pv_factor = data.profile.pv_profile[global_index]
        bus_by_id = Dict(bus.id => bus for bus in data.buses)
        for bus_id in 2:length(data.buses)
            incoming = data.topology.parent_branch[bus_id]
            child_branches = [data.topology.parent_branch[child] for child in data.topology.children[bus_id]]
            child_p = sum((value(bundle.P[branch, t]) for branch in child_branches); init=0.0)
            child_q = sum((value(bundle.Q[branch, t]) for branch in child_branches); init=0.0)
            injection_kw = get(capacities, bus_id, 0.0) * pv_factor
            active_residual = value(bundle.P[incoming, t]) - data.r_pu[incoming] *
                              value(bundle.ell[incoming, t]) - child_p -
                              (bus_by_id[bus_id].pd_kw * load_multiplier - injection_kw) /
                              data.base_power_kw
            reactive_residual = value(bundle.Q[incoming, t]) - data.x_pu[incoming] *
                                value(bundle.ell[incoming, t]) - child_q -
                                bus_by_id[bus_id].qd_kvar * load_multiplier /
                                data.base_power_kw
            max_active_balance = max(max_active_balance, abs(active_residual))
            max_reactive_balance = max(max_reactive_balance, abs(reactive_residual))
        end
    end
    replay = validate_capacities(data, capacities)
    max_voltage_difference = replay.converged ? maximum(
        abs(nlp_voltage[t][bus] - replay.states[t].voltage_pu[bus])
        for t in 1:length(data.indices), bus in 1:length(data.buses)
    ) : Inf
    maximum_constraint_violation = max(
        max_active_balance, max_reactive_balance, max_voltage_drop, max_current_equality, max_root,
    )
    accepted = replay.replay_passed &&
               maximum_constraint_violation <= AC_RESIDUAL_TOL &&
               max_voltage_difference <= SOCP_AC_VOLTAGE_TOL
    return (
        capacities_kw=capacities,
        total_hc_kw=sum(values(capacities)),
        vmin=vmin,
        vmax=vmax,
        maximum_constraint_violation=maximum_constraint_violation,
        maximum_active_balance_residual=max_active_balance,
        maximum_reactive_balance_residual=max_reactive_balance,
        maximum_voltage_drop_residual=max_voltage_drop,
        maximum_current_equality_residual=max_current_equality,
        maximum_root_residual=max_root,
        replay=replay,
        maximum_replay_voltage_difference=max_voltage_difference,
        accepted=accepted,
    )
end

function solve_ac_multistart(data::BenchmarkData, specs=multistart_specs(data))
    results = NamedTuple[]
    for (start_id, spec) in enumerate(specs)
        bundle = build_ac_opf_model(data)
        initial_validation = initialize_ac_model!(bundle, data, spec.capacities_kw)
        started = time()
        optimize!(bundle.model)
        elapsed = time() - started
        status = string(termination_status(bundle.model))
        primal = string(primal_status(bundle.model))
        has_primal = try has_values(bundle.model) catch; false end
        diagnostics = has_primal ? ac_solution_diagnostics(bundle, data) : nothing
        capacities = diagnostics === nothing ? Dict(bus => NaN for bus in CANDIDATE_BUSES) : diagnostics.capacities_kw
        push!(results, (
            start_id=start_id,
            start_name=spec.name,
            start_kind=spec.kind,
            seed=spec.seed,
            initial_c13_kw=spec.capacities_kw[1],
            initial_c20_kw=spec.capacities_kw[2],
            initial_c24_kw=spec.capacities_kw[3],
            initial_c30_kw=spec.capacities_kw[4],
            initial_total_kw=sum(spec.capacities_kw),
            initial_direction_limit_kw=spec.direction_limit_kw,
            initial_scale_fraction=spec.scale_fraction,
            initial_ac_feasible=initial_validation.ac_feasible,
            termination_status=status,
            primal_status=primal,
            objective_kw=diagnostics === nothing ? NaN : diagnostics.total_hc_kw,
            c13_kw=capacities[13], c20_kw=capacities[20],
            c24_kw=capacities[24], c30_kw=capacities[30],
            maximum_constraint_violation=diagnostics === nothing ? Inf : diagnostics.maximum_constraint_violation,
            nlp_vmin_pu=diagnostics === nothing ? NaN : diagnostics.vmin,
            nlp_vmax_pu=diagnostics === nothing ? NaN : diagnostics.vmax,
            ac_replay_feasible=diagnostics === nothing ? false : diagnostics.replay.ac_feasible,
            ac_replay_vmin_pu=diagnostics === nothing ? NaN : diagnostics.replay.vmin,
            ac_replay_vmax_pu=diagnostics === nothing ? NaN : diagnostics.replay.vmax,
            ac_replay_voltage_difference_pu=diagnostics === nothing ? Inf : diagnostics.maximum_replay_voltage_difference,
            independent_replay_max_absolute_residual=diagnostics === nothing ? Inf : diagnostics.replay.max_equation_residual,
            independent_replay_max_scaled_residual=diagnostics === nothing ? Inf : diagnostics.replay.max_scaled_residual,
            independent_replay_phasor_recoverable=diagnostics === nothing ? false : diagnostics.replay.phasor_recoverable,
            independent_replay_passed=diagnostics === nothing ? false : diagnostics.replay.replay_passed,
            accepted=diagnostics === nothing ? false : diagnostics.accepted && status in ("LOCALLY_SOLVED", "ALMOST_LOCALLY_SOLVED"),
            iterations=_iteration_count(bundle.model),
            solve_time_seconds=isfinite(_solve_time(bundle.model)) ? _solve_time(bundle.model) : elapsed,
            wall_time_seconds=elapsed,
            diagnostics=diagnostics,
        ))
        @printf("AC start %d/%d %-28s status=%s HC=%.6f accepted=%s\n",
                start_id, length(specs), spec.name, status,
                diagnostics === nothing ? NaN : diagnostics.total_hc_kw,
                results[end].accepted ? "true" : "false")
    end
    return results
end

function best_ac_result(results)
    accepted = [result for result in results if result.accepted]
    isempty(accepted) && return nothing
    return argmax(result -> result.objective_kw, accepted)
end

function _socp_diagnostics(bundle, data::BenchmarkData, capacities::Dict{Int,Float64})
    network = bundle.network
    local_count = length(data.indices)
    min_gap = Inf
    max_gap = -Inf
    max_relative_gap = 0.0
    worst_gap = (-Inf, 0, 0)
    max_voltage_drop = 0.0
    vmin = Inf
    vmax = -Inf
    socp_voltage = Vector{Vector{Float64}}(undef, local_count)
    active_losses = zeros(local_count)
    reactive_losses = zeros(local_count)
    for t in 1:local_count
        socp_voltage[t] = [sqrt(max(0.0, value(network.v[bus, t]))) for bus in 1:length(data.buses)]
        vmin = min(vmin, minimum(socp_voltage[t]))
        vmax = max(vmax, maximum(socp_voltage[t]))
        active_losses[t] = sum(data.r_pu[branch] * value(network.ell[branch, t])
                               for branch in 1:length(data.branches)) * data.base_power_kw
        reactive_losses[t] = sum(data.x_pu[branch] * value(network.ell[branch, t])
                                 for branch in 1:length(data.branches)) * data.base_power_kw
        for branch in 1:length(data.branches)
            i = data.topology.branch_from[branch]
            j = data.topology.branch_to[branch]
            p = value(network.Pij[branch, t])
            q = value(network.Qij[branch, t])
            ell = value(network.ell[branch, t])
            vi = value(network.v[i, t])
            vj = value(network.v[j, t])
            gap = vi * ell - p^2 - q^2
            relative = abs(gap) / max(abs(vi * ell), p^2 + q^2, 1e-12)
            min_gap = min(min_gap, gap)
            max_gap = max(max_gap, gap)
            if relative > worst_gap[1]
                worst_gap = (relative, t, branch)
            end
            max_relative_gap = max(max_relative_gap, relative)
            r = data.r_pu[branch]
            x = data.x_pu[branch]
            max_voltage_drop = max(max_voltage_drop,
                abs(vj - vi + 2.0 * (r * p + x * q) - (r^2 + x^2) * ell))
        end
    end
    replay = validate_capacities(data, capacities)
    max_voltage_difference = replay.converged ? maximum(
        abs(socp_voltage[t][bus] - replay.states[t].voltage_pu[bus])
        for t in 1:local_count, bus in 1:length(data.buses)
    ) : Inf
    approximately_exact = max_relative_gap <= EXACTNESS_SOC_TOL &&
                          replay.ac_feasible &&
                          max_voltage_difference <= SOCP_AC_VOLTAGE_TOL
    return (
        vmin=vmin, vmax=vmax, min_gap=min_gap, max_gap=max_gap,
        max_relative_gap=max_relative_gap,
        maximum_branch_flow_residual=max_voltage_drop,
        mean_active_losses_kw=sum(active_losses) / local_count,
        max_active_losses_kw=maximum(active_losses),
        max_reactive_losses_kvar=maximum(reactive_losses),
        worst_gap_local_t=worst_gap[2],
        worst_gap_branch=worst_gap[3],
        replay=replay,
        maximum_socp_ac_voltage_difference=max_voltage_difference,
        approximately_exact=approximately_exact,
    )
end

function build_socp_penalty_model(data::BenchmarkData, lambda::Real)
    lambda_value = Float64(lambda)
    lambda_value >= 0.0 && isfinite(lambda_value) ||
        throw(ArgumentError("SOCP penalty lambda must be finite and nonnegative"))
    bundle = CiroPVHC.build_s1b_central_model(data.profile, data.indices)
    total_capacity = sum(bundle.capacity_kw[bus] for bus in CANDIDATE_BUSES)
    total_loss_pu = sum(
        bundle.network.r_pu[branch] * bundle.network.ell[branch, t]
        for branch in bundle.network.topology.branch_ids, t in 1:length(data.indices)
    )
    normalized_hc = total_capacity / data.normalization_power_kw
    normalized_loss = total_loss_pu * data.base_power_kw /
                      (length(data.indices) * data.normalization_power_kw)
    @objective(bundle.model, Max, normalized_hc - lambda_value * normalized_loss)
    return (
        bundle=bundle,
        lambda=lambda_value,
        total_capacity=total_capacity,
        normalized_hc=normalized_hc,
        normalized_loss=normalized_loss,
    )
end

function solve_socp_penalty_sweep(data::BenchmarkData; lambdas=PENALTY_LAMBDAS)
    results = NamedTuple[]
    for lambda in lambdas
        penalty_model = build_socp_penalty_model(data, lambda)
        bundle = penalty_model.bundle
        started = time()
        optimize!(bundle.model)
        elapsed = time() - started
        status = string(termination_status(bundle.model))
        primal = string(primal_status(bundle.model))
        has_primal = try has_values(bundle.model) catch; false end
        capacities = has_primal ? Dict(
            bus => value(bundle.capacity_kw[bus]) for bus in CANDIDATE_BUSES
        ) : Dict(bus => NaN for bus in CANDIDATE_BUSES)
        diagnostics = has_primal ? _socp_diagnostics(bundle, data, capacities) : nothing
        penalty_value = has_primal ? value(penalty_model.normalized_loss) : NaN
        objective_value_dimensionless = has_primal ? objective_value(bundle.model) : NaN
        push!(results, (
            lambda=Float64(lambda),
            termination_status=status,
            primal_status=primal,
            c13_kw=capacities[13], c20_kw=capacities[20],
            c24_kw=capacities[24], c30_kw=capacities[30],
            total_hc_kw=has_primal ? sum(values(capacities)) : NaN,
            normalized_hc=has_primal ? sum(values(capacities)) / data.normalization_power_kw : NaN,
            normalized_penalty_measure=penalty_value,
            weighted_penalty=lambda * penalty_value,
            objective_dimensionless=objective_value_dimensionless,
            socp_vmin_pu=diagnostics === nothing ? NaN : diagnostics.vmin,
            socp_vmax_pu=diagnostics === nothing ? NaN : diagnostics.vmax,
            min_soc_gap_pu2=diagnostics === nothing ? NaN : diagnostics.min_gap,
            max_soc_gap_pu2=diagnostics === nothing ? NaN : diagnostics.max_gap,
            maximum_relative_soc_gap=diagnostics === nothing ? Inf : diagnostics.max_relative_gap,
            maximum_branch_flow_residual=diagnostics === nothing ? Inf : diagnostics.maximum_branch_flow_residual,
            mean_active_losses_kw=diagnostics === nothing ? NaN : diagnostics.mean_active_losses_kw,
            max_active_losses_kw=diagnostics === nothing ? NaN : diagnostics.max_active_losses_kw,
            max_reactive_losses_kvar=diagnostics === nothing ? NaN : diagnostics.max_reactive_losses_kvar,
            worst_gap_timestamp=diagnostics === nothing ? "" :
                Dates.format(data.profile.timestamps[data.indices[diagnostics.worst_gap_local_t]], dateformat"yyyy-mm-dd HH:MM:SS"),
            worst_gap_interval=diagnostics === nothing ? 0 : diagnostics.worst_gap_local_t,
            worst_gap_branch=diagnostics === nothing ? 0 : diagnostics.worst_gap_branch,
            ac_converged=diagnostics === nothing ? false : diagnostics.replay.converged,
            ac_feasible=diagnostics === nothing ? false : diagnostics.replay.ac_feasible,
            ac_vmin_pu=diagnostics === nothing ? NaN : diagnostics.replay.vmin,
            ac_vmax_pu=diagnostics === nothing ? NaN : diagnostics.replay.vmax,
            ac_undervoltage_count=diagnostics === nothing ? 0 : diagnostics.replay.undervoltage_count,
            ac_overvoltage_count=diagnostics === nothing ? 0 : diagnostics.replay.overvoltage_count,
            ac_undervoltage_intervals=diagnostics === nothing ? 0 : diagnostics.replay.undervoltage_intervals,
            ac_overvoltage_intervals=diagnostics === nothing ? 0 : diagnostics.replay.overvoltage_intervals,
            max_socp_ac_voltage_difference_pu=diagnostics === nothing ? Inf : diagnostics.maximum_socp_ac_voltage_difference,
            max_import_kw=diagnostics === nothing ? NaN : diagnostics.replay.max_import_kw,
            max_export_kw=diagnostics === nothing ? NaN : diagnostics.replay.max_export_kw,
            ac_max_active_losses_kw=diagnostics === nothing ? NaN : diagnostics.replay.max_active_losses_kw,
            approximately_exact=diagnostics === nothing ? false : diagnostics.approximately_exact,
            solve_time_seconds=isfinite(_solve_time(bundle.model)) ? _solve_time(bundle.model) : elapsed,
            wall_time_seconds=elapsed,
            diagnostics=diagnostics,
        ))
        @printf("SOCP lambda=%-8g status=%s HC=%.6f rel_gap=%.3e AC=%s exact=%s\n",
                lambda, status, results[end].total_hc_kw,
                results[end].maximum_relative_soc_gap,
                results[end].ac_feasible ? "feasible" : "infeasible",
                results[end].approximately_exact ? "true" : "false")
    end
    return results
end

function multistart_nonuniqueness(results; objective_tolerance_kw::Float64=0.1, allocation_tolerance_kw::Float64=1.0)
    accepted = [result for result in results if result.accepted]
    isempty(accepted) && return (
        status="not_testable", near_best_count=0, objective_range_kw=NaN,
        maximum_allocation_spread_kw=NaN, spatial_nonuniqueness_detected=false,
    )
    best = maximum(result.objective_kw for result in accepted)
    near_best = [result for result in accepted if best - result.objective_kw <= objective_tolerance_kw]
    objective_range = maximum(result.objective_kw for result in near_best) -
                      minimum(result.objective_kw for result in near_best)
    spreads = [
        maximum(getfield(result, Symbol("c$(bus)_kw")) for result in near_best) -
        minimum(getfield(result, Symbol("c$(bus)_kw")) for result in near_best)
        for bus in CANDIDATE_BUSES
    ]
    max_spread = maximum(spreads)
    return (
        status=length(near_best) >= 2 ? "evaluated_among_multistarts" : "single_near_best_solution",
        near_best_count=length(near_best),
        objective_range_kw=objective_range,
        maximum_allocation_spread_kw=max_spread,
        spatial_nonuniqueness_detected=length(near_best) >= 2 && max_spread > allocation_tolerance_kw,
    )
end

export BenchmarkData,
    ExactACState,
    BENCHMARK_DATE,
    CANDIDATE_BUSES,
    PENALTY_LAMBDAS,
    load_benchmark_data,
    effective_configuration,
    exact_ac_state,
    validate_capacities,
    multistart_directions,
    multistart_specs,
    build_ac_opf_model,
    build_socp_penalty_model,
    initialize_ac_model!,
    ac_solution_diagnostics,
    solve_ac_multistart,
    best_ac_result,
    solve_socp_penalty_sweep,
    multistart_nonuniqueness

end
