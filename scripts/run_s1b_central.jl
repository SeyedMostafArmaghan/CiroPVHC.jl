using CiroPVHC
using JuMP
using Clarabel
using Dates
using Printf

CiroPVHC._load_s1b_solver!()

const BINDING_TOLERANCE_PU = 1e-6
const AC_VOLTAGE_TOLERANCE_PU = 1e-7
const OPTIMALITY_LOCK_TOLERANCE_KW = 1e-3
const ACCEPTED_S1B_STATUSES = Set(("OPTIMAL", "ALMOST_OPTIMAL"))

csv_value(value) = value isa AbstractString ?
    "\"" * replace(value, '"' => "\"\"") * "\"" : string(value)

function write_csv(path::AbstractString, columns, rows)
    open(path, "w") do io
        println(io, join(columns, ','))
        for row in rows
            println(io, join((csv_value(value) for value in row), ','))
        end
    end
end

timestamp_text(timestamp::DateTime) = Dates.format(timestamp, dateformat"yyyy-mm-dd HH:MM:SS")

function git_head(repository_root::AbstractString)
    return try
        readchomp(`git -C $repository_root rev-parse HEAD`)
    catch
        "unknown"
    end
end

function write_effective_configuration(
    path::AbstractString,
    profile,
    initial_indices::Vector{Int},
    repository_root::AbstractString,
)
    open(path, "w") do io
        println(io, "stage=S1-B central voltage-constrained PV hosting capacity")
        println(io, "repository_commit_at_start=$(git_head(repository_root))")
        println(io, "profile_path=$(profile.source_path)")
        println(io, "profile_sha256=$(profile.source_sha256)")
        println(io, "full_profile_intervals=$(length(profile.timestamps))")
        println(io, "initial_unique_days=32")
        println(io, "intervals_per_day=48")
        println(io, "initial_optimization_intervals=$(length(initial_indices))")
        println(io, "candidate_buses=13,20,24,30")
        println(io, "capacity_vector=one shared nonnegative vector across every modeled interval")
        println(io, "site_cap_active=false")
        println(io, "capacity_upper_bounds=absent")
        println(io, "gamma_cap_active=false")
        println(io, "curtailment_active=false")
        println(io, "pv_injection=installed_capacity_times_recorded_pv_profile")
        println(io, "no_export_active=false")
        println(io, "export_allowed=true")
        println(io, "thermal_constraints_active=false")
        println(io, "ampacity_constraints_active=false")
        println(io, "branch_smax_constraints_active=false")
        println(io, "transformer_limit_active=false")
        println(io, "synthetic_4000_kva_rating_active=false")
        println(io, "loss_cap_active=false")
        println(io, "root_voltage_pu=1.0")
        println(io, "voltage_min_pu=0.9")
        println(io, "voltage_max_pu=1.05")
        println(io, "squared_voltage_min=0.81")
        println(io, "squared_voltage_max=1.1025")
        println(io, "objective=maximize_C13_plus_C20_plus_C24_plus_C30")
        println(io, "thermal_validation_performed=false")
        println(io, "binding_tolerance_pu=$(BINDING_TOLERANCE_PU)")
        println(io, "ac_voltage_tolerance_pu=$(AC_VOLTAGE_TOLERANCE_PU)")
        println(io, "archived_2766_97_kw_used=false")
    end
end

function feasibility_diagnostic(profile, indices)
    bundle = build_s1b_central_model(profile, indices)
    @objective(bundle.model, Min, 0.0)
    optimize!(bundle.model)
    return (
        termination_status=string(termination_status(bundle.model)),
        primal_status=string(primal_status(bundle.model)),
        dual_status=string(dual_status(bundle.model)),
        has_primal=try has_values(bundle.model) catch; false end,
    )
end

function substation_and_losses(bundle, local_t::Int)
    network = bundle.network
    base_kw = bundle.data.base_mva * 1000.0
    root = network.topology.root_bus
    root_branches = network.topology.outgoing_branches[root]
    p_sub = sum(value(network.Pij[branch, local_t]) for branch in root_branches) * base_kw
    q_sub = sum(value(network.Qij[branch, local_t]) for branch in root_branches) * base_kw
    p_loss = sum(
        network.r_pu[branch] * value(network.ell[branch, local_t])
        for branch in network.topology.branch_ids
    ) * base_kw
    q_loss = sum(
        network.x_pu[branch] * value(network.ell[branch, local_t])
        for branch in network.topology.branch_ids
    ) * base_kw
    return p_sub, q_sub, p_loss, q_loss
end

function socp_diagnostics(solution, profile)
    bundle = solution.bundle
    network = bundle.network
    data = bundle.data
    base_kw = data.base_mva * 1000.0
    bus_by_id = Dict(bus.id => bus for bus in data.buses)
    max_p_balance = 0.0
    max_q_balance = 0.0
    max_voltage_drop = 0.0
    max_root = 0.0
    max_soc_gap = -Inf
    min_soc_gap = Inf
    max_relative_soc_gap = 0.0
    minimum_record = nothing
    maximum_record = nothing
    binding_rows = Tuple[]

    for local_t in 1:data.timeseries.T
        global_index = bundle.full_indices[local_t]
        for bus in data.buses
            voltage = sqrt(max(0.0, value(network.v[bus.id, local_t])))
            record = (voltage, global_index, local_t, bus.id)
            minimum_record = minimum_record === nothing || voltage < minimum_record[1] ? record : minimum_record
            maximum_record = maximum_record === nothing || voltage > maximum_record[1] ? record : maximum_record
            lower_distance = voltage - CiroPVHC.S1B_VMIN_PU
            upper_distance = CiroPVHC.S1B_VMAX_PU - voltage
            if lower_distance <= BINDING_TOLERANCE_PU
                push!(binding_rows, (
                    "voltage_min", global_index, timestamp_text(profile.timestamps[global_index]),
                    bus.id, voltage, CiroPVHC.S1B_VMIN_PU, lower_distance,
                ))
            end
            if upper_distance <= BINDING_TOLERANCE_PU
                push!(binding_rows, (
                    "voltage_max", global_index, timestamp_text(profile.timestamps[global_index]),
                    bus.id, voltage, CiroPVHC.S1B_VMAX_PU, upper_distance,
                ))
            end
        end
        max_root = max(max_root, abs(value(network.v[1, local_t]) - CiroPVHC.S1B_ROOT_VOLTAGE_PU^2))
        for branch_id in network.topology.branch_ids
            i = network.topology.from_bus[branch_id]
            j = network.topology.to_bus[branch_id]
            p = value(network.Pij[branch_id, local_t])
            q = value(network.Qij[branch_id, local_t])
            ell = value(network.ell[branch_id, local_t])
            vi = value(network.v[i, local_t])
            vj = value(network.v[j, local_t])
            r = network.r_pu[branch_id]
            x = network.x_pu[branch_id]
            voltage_residual = vj - vi + 2.0 * (r * p + x * q) - (r^2 + x^2) * ell
            max_voltage_drop = max(max_voltage_drop, abs(voltage_residual))
            gap = vi * ell - p^2 - q^2
            max_soc_gap = max(max_soc_gap, gap)
            min_soc_gap = min(min_soc_gap, gap)
            max_relative_soc_gap = max(max_relative_soc_gap, abs(gap) / max(abs(vi * ell), p^2 + q^2, 1e-12))
        end
        for bus_id in network.topology.bus_ids
            bus_id == network.topology.root_bus && continue
            incoming = network.topology.incoming_branch[bus_id]
            children = network.topology.outgoing_branches[bus_id]
            child_p = sum((value(network.Pij[branch, local_t]) for branch in children); init=0.0)
            child_q = sum((value(network.Qij[branch, local_t]) for branch in children); init=0.0)
            p_injected = get(solution.capacities_kw, bus_id, 0.0) * data.timeseries.pv_profile[local_t]
            p_rhs = (bus_by_id[bus_id].pd_kw * data.timeseries.load_multiplier[local_t] - p_injected) / base_kw
            q_rhs = bus_by_id[bus_id].qd_kvar * data.timeseries.load_multiplier[local_t] / base_kw
            p_residual = value(network.Pij[incoming, local_t]) - network.r_pu[incoming] *
                         value(network.ell[incoming, local_t]) - child_p - p_rhs
            q_residual = value(network.Qij[incoming, local_t]) - network.x_pu[incoming] *
                         value(network.ell[incoming, local_t]) - child_q - q_rhs
            max_p_balance = max(max_p_balance, abs(p_residual) * base_kw)
            max_q_balance = max(max_q_balance, abs(q_residual) * base_kw)
        end
    end
    return (
        minimum_record=minimum_record,
        maximum_record=maximum_record,
        binding_rows=binding_rows,
        max_active_balance_residual_kw=max_p_balance,
        max_reactive_balance_residual_kvar=max_q_balance,
        max_voltage_drop_residual_pu2=max_voltage_drop,
        max_root_voltage_residual_pu2=max_root,
        max_soc_gap_pu2=max_soc_gap,
        min_soc_gap_pu2=min_soc_gap,
        max_relative_soc_gap=max_relative_soc_gap,
    )
end

function siting_ranges(profile, indices, total_hc_kw)
    bundle = build_s1b_central_model(profile, indices)
    total_capacity = sum(bundle.capacity_kw[bus] for bus in CiroPVHC.S1B_CANDIDATE_BUSES)
    @constraint(bundle.model, total_capacity >= total_hc_kw - OPTIMALITY_LOCK_TOLERANCE_KW)
    @constraint(bundle.model, total_capacity <= total_hc_kw + OPTIMALITY_LOCK_TOLERANCE_KW)
    ranges = Dict{Int,Tuple{Float64,Float64,String,String}}()
    for bus in CiroPVHC.S1B_CANDIDATE_BUSES
        @objective(bundle.model, Min, bundle.capacity_kw[bus])
        optimize!(bundle.model)
        min_status = string(termination_status(bundle.model))
        min_value = min_status in ACCEPTED_S1B_STATUSES ? value(bundle.capacity_kw[bus]) : NaN
        @objective(bundle.model, Max, bundle.capacity_kw[bus])
        optimize!(bundle.model)
        max_status = string(termination_status(bundle.model))
        max_value = max_status in ACCEPTED_S1B_STATUSES ? value(bundle.capacity_kw[bus]) : NaN
        ranges[bus] = (min_value, max_value, min_status, max_status)
    end
    return ranges
end

function write_empty_or_unbounded_outputs(output_directory, solution, diagnostic, initial_count)
    write_csv(joinpath(output_directory, "pv_capacity_by_bus.csv"),
              ("bus", "capacity_kw", "minimum_optimal_kw", "maximum_optimal_kw", "siting_unique"), Tuple[])
    write_csv(joinpath(output_directory, "binding_constraints.csv"),
              ("constraint", "interval_index", "timestamp", "bus", "value_pu", "limit_pu", "distance_pu"), Tuple[])
    write_csv(joinpath(output_directory, "critical_operating_point.csv"),
              ("kind", "interval_index", "timestamp", "bus", "voltage_pu", "limit_pu", "distance_pu", "substation_p_kw", "substation_q_kvar", "active_losses_kw", "reactive_losses_kvar"), Tuple[])
    write_csv(joinpath(output_directory, "socp_diagnostics.csv"),
              ("metric", "value", "unit"), [
                  ("feasibility_termination_status", diagnostic.termination_status, "status"),
                  ("feasibility_primal_status", diagnostic.primal_status, "status"),
                  ("feasibility_dual_status", diagnostic.dual_status, "status"),
                  ("feasibility_has_primal", diagnostic.has_primal, "boolean"),
              ])
    write_csv(joinpath(output_directory, "ac_voltage_violations.csv"),
              ("interval_index", "timestamp", "bus", "voltage_pu", "limit_type", "limit_pu", "violation_pu"), Tuple[])
    write_csv(joinpath(output_directory, "constraint_generation_history.csv"),
              ("iteration", "optimization_intervals", "hc_kw", "solver_status", "ac_under_intervals", "ac_over_intervals", "ac_failed_intervals", "added_intervals", "added_timestamps", "outcome"), [
                  (1, initial_count, "", solution.termination_status, "", "", "", 0, "", "nonfinite_or_unbounded"),
              ])
    open(joinpath(output_directory, "ac_validation_summary.txt"), "w") do io
        println(io, "performed=false")
        println(io, "reason=no finite S1-B capacity vector is available")
        println(io, "thermal_validation_performed=false")
    end
end

function write_finite_outputs(output_directory, profile, solution, diagnostics, ac, history, ranges, blocker)
    capacity_rows = [
        (bus, solution.capacities_kw[bus], ranges[bus][1], ranges[bus][2],
         isfinite(ranges[bus][1]) && isfinite(ranges[bus][2]) && ranges[bus][2] - ranges[bus][1] <= 2e-3)
        for bus in CiroPVHC.S1B_CANDIDATE_BUSES
    ]
    write_csv(joinpath(output_directory, "pv_capacity_by_bus.csv"),
              ("bus", "capacity_kw", "minimum_optimal_kw", "maximum_optimal_kw", "siting_unique"), capacity_rows)
    write_csv(joinpath(output_directory, "binding_constraints.csv"),
              ("constraint", "interval_index", "timestamp", "bus", "value_pu", "limit_pu", "distance_pu"), diagnostics.binding_rows)

    critical_rows = Tuple[]
    for (kind, record, limit) in (
        ("minimum_voltage", diagnostics.minimum_record, CiroPVHC.S1B_VMIN_PU),
        ("maximum_voltage", diagnostics.maximum_record, CiroPVHC.S1B_VMAX_PU),
    )
        voltage, global_index, local_t, bus = record
        p_sub, q_sub, p_loss, q_loss = substation_and_losses(solution.bundle, local_t)
        push!(critical_rows, (
            kind, global_index, timestamp_text(profile.timestamps[global_index]), bus, voltage,
            limit, abs(voltage - limit), p_sub, q_sub, p_loss, q_loss,
        ))
    end
    write_csv(joinpath(output_directory, "critical_operating_point.csv"),
              ("kind", "interval_index", "timestamp", "bus", "voltage_pu", "limit_pu", "distance_pu", "substation_p_kw", "substation_q_kvar", "active_losses_kw", "reactive_losses_kvar"), critical_rows)
    write_csv(joinpath(output_directory, "socp_diagnostics.csv"),
              ("metric", "value", "unit"), [
                  ("maximum_active_balance_residual", diagnostics.max_active_balance_residual_kw, "kW"),
                  ("maximum_reactive_balance_residual", diagnostics.max_reactive_balance_residual_kvar, "kvar"),
                  ("maximum_voltage_drop_residual", diagnostics.max_voltage_drop_residual_pu2, "p.u.^2"),
                  ("maximum_root_voltage_residual", diagnostics.max_root_voltage_residual_pu2, "p.u.^2"),
                  ("maximum_soc_gap", diagnostics.max_soc_gap_pu2, "p.u.^2"),
                  ("minimum_soc_gap", diagnostics.min_soc_gap_pu2, "p.u.^2"),
                  ("maximum_relative_soc_gap", diagnostics.max_relative_soc_gap, "ratio"),
              ])

    violation_rows = Tuple[]
    for index in union(ac.under_indices, ac.over_indices)
        state = ac.states[index]
        under_buses = [bus for bus in eachindex(state.voltages)
                       if state.voltages[bus] < CiroPVHC.S1B_VMIN_PU - AC_VOLTAGE_TOLERANCE_PU]
        over_buses = [bus for bus in eachindex(state.voltages)
                      if state.voltages[bus] > CiroPVHC.S1B_VMAX_PU + AC_VOLTAGE_TOLERANCE_PU]
        if !isempty(under_buses)
            bus = argmin(bus -> state.voltages[bus], under_buses)
            voltage = state.voltages[bus]
            push!(violation_rows, (index, timestamp_text(profile.timestamps[index]), bus, voltage,
                "minimum", CiroPVHC.S1B_VMIN_PU, CiroPVHC.S1B_VMIN_PU - voltage, length(under_buses)))
        end
        if !isempty(over_buses)
            bus = argmax(bus -> state.voltages[bus], over_buses)
            voltage = state.voltages[bus]
            push!(violation_rows, (index, timestamp_text(profile.timestamps[index]), bus, voltage,
                "maximum", CiroPVHC.S1B_VMAX_PU, voltage - CiroPVHC.S1B_VMAX_PU, length(over_buses)))
        end
    end
    write_csv(joinpath(output_directory, "ac_voltage_violations.csv"),
              ("interval_index", "timestamp", "worst_bus", "worst_voltage_pu", "limit_type", "limit_pu", "worst_violation_pu", "bus_time_violation_count"), violation_rows)
    write_csv(joinpath(output_directory, "constraint_generation_history.csv"),
              ("iteration", "optimization_intervals", "hc_kw", "solver_status", "ac_under_intervals", "ac_over_intervals", "ac_failed_intervals", "added_intervals", "added_timestamps", "outcome"), history)

    min_state = ac.states[ac.global_min_index]
    max_state = ac.states[ac.global_max_index]
    import_state = ac.states[ac.max_import_index]
    export_state = ac.states[ac.max_export_index]
    loss_state = ac.states[ac.max_loss_index]
    ratio_state = ac.states[ac.max_loss_ratio_index]
    under_bus_time = sum((row[8] for row in violation_rows if row[5] == "minimum"); init=0)
    over_bus_time = sum((row[8] for row in violation_rows if row[5] == "maximum"); init=0)
    open(joinpath(output_directory, "ac_validation_summary.txt"), "w") do io
        println(io, "performed=true")
        println(io, "method=independent nonlinear radial backward-forward sweep")
        println(io, "intervals=$(length(profile.timestamps))")
        println(io, "converged=$(length(ac.converged_indices))")
        println(io, "failed=$(length(ac.failed_indices))")
        println(io, "global_vmin_pu=$(min_state.vmin)")
        println(io, "global_vmin_bus=$(min_state.vmin_bus)")
        println(io, "global_vmin_timestamp=$(timestamp_text(profile.timestamps[ac.global_min_index]))")
        println(io, "global_vmax_pu=$(max_state.vmax)")
        println(io, "global_vmax_bus=$(max_state.vmax_bus)")
        println(io, "global_vmax_timestamp=$(timestamp_text(profile.timestamps[ac.global_max_index]))")
        println(io, "undervoltage_intervals=$(length(ac.under_indices))")
        println(io, "overvoltage_intervals=$(length(ac.over_indices))")
        println(io, "undervoltage_bus_time_violations=$under_bus_time")
        println(io, "overvoltage_bus_time_violations=$over_bus_time")
        println(io, "maximum_import_kw=$(max(import_state.substation_p_kw, 0.0))")
        println(io, "maximum_import_timestamp=$(timestamp_text(profile.timestamps[ac.max_import_index]))")
        println(io, "maximum_export_kw=$(max(-export_state.substation_p_kw, 0.0))")
        println(io, "maximum_export_timestamp=$(timestamp_text(profile.timestamps[ac.max_export_index]))")
        println(io, "maximum_active_losses_kw=$(loss_state.active_losses_kw)")
        println(io, "maximum_active_losses_timestamp=$(timestamp_text(profile.timestamps[ac.max_loss_index]))")
        println(io, "maximum_active_loss_ratio_percent=$(ratio_state.loss_ratio_percent)")
        println(io, "maximum_active_loss_ratio_timestamp=$(timestamp_text(profile.timestamps[ac.max_loss_ratio_index]))")
        println(io, "undefined_active_loss_ratio_intervals=$(length(ac.undefined_loss_ratio_indices))")
        println(io, "thermal_validation_performed=false")
        println(io, "blocker=$(blocker)")
    end
end

function write_solver_summary(path, solution, feasibility, initial_count, final_count, iterations, blocker)
    open(path, "w") do io
        println(io, "termination_status=$(solution.termination_status)")
        println(io, "primal_status=$(solution.primal_status)")
        println(io, "dual_status=$(solution.dual_status)")
        println(io, "objective_bound=$(solution.objective_bound)")
        println(io, "has_primal=$(solution.has_primal)")
        println(io, "initial_optimization_intervals=$initial_count")
        println(io, "final_optimization_intervals=$final_count")
        println(io, "constraint_generation_iterations=$iterations")
        println(io, "feasibility_diagnostic_status=$(feasibility === nothing ? "not_required" : feasibility.termination_status)")
        println(io, "feasibility_diagnostic_has_primal=$(feasibility === nothing ? "not_required" : feasibility.has_primal)")
        println(io, "blocker=$blocker")
    end
end

function write_decision_report(path, solution, initial_count, final_count, iterations, blocker)
    open(path, "w") do io
        println(io, "# S1-B central decision report")
        println(io)
        println(io, "This run evaluates voltage-constrained PV hosting capacity only. It does not establish thermal hosting capacity.")
        println(io)
        println(io, "## Mathematical status")
        println(io)
        println(io, "- Solver termination: `$(solution.termination_status)`")
        println(io, "- Primal status: `$(solution.primal_status)`")
        println(io, "- Dual status: `$(solution.dual_status)`")
        println(io, "- Initial/final optimization intervals: $initial_count / $final_count")
        println(io, "- Constraint-generation iterations: $iterations")
        if solution.has_primal
            println(io, "- Voltage-constrained HC: $(solution.total_capacity_kw) kW")
            for bus in CiroPVHC.S1B_CANDIDATE_BUSES
                println(io, "- Bus $bus capacity: $(solution.capacities_kw[bus]) kW")
            end
        else
            println(io, "- No finite HC value is reported because no primal optimum is available.")
        end
        println(io)
        println(io, "## Scope confirmation")
        println(io)
        println(io, "Site caps, gamma caps, no-export policy, curtailment, loss caps, thermal limits, ampacity limits, transformer limits, and the synthetic 4 MVA rating are absent. The shared capacity vector is applied without curtailment. Export is allowed. AC validation performs no thermal check.")
        println(io)
        println(io, "## Remaining blocker")
        println(io)
        println(io, isempty(blocker) ? "None recorded." : blocker)
    end
end

function main()
    repository_root = normpath(joinpath(@__DIR__, ".."))
    profile_path = joinpath(repository_root, "data_processed", "ausgrid", "ausgrid_halfhour_normalized.csv")
    audit_path = joinpath(repository_root, "results", "pre_s1_audit", "critical_day_candidates.csv")
    output_directory = joinpath(repository_root, "results", "s1b_central")
    mkpath(output_directory)

    profile = read_s1b_profile(profile_path)
    initial_indices = read_s1b_initial_indices(profile, audit_path)
    write_effective_configuration(
        joinpath(output_directory, "effective_configuration.txt"), profile, initial_indices, repository_root,
    )
    println("S1-B effective configuration written before solve")
    println("site_cap=false no_export=false curtailment=false thermal=false gamma_cap=false")
    println("initial_intervals=$(length(initial_indices)) full_ac_intervals=$(length(profile.timestamps))")

    optimization_indices = copy(initial_indices)
    history = Tuple[]
    solution = solve_s1b_central(profile, optimization_indices)
    feasibility = nothing
    blocker = ""
    iteration = 1
    ac = nothing

    if !(solution.termination_status in ACCEPTED_S1B_STATUSES && solution.has_primal)
        feasibility = feasibility_diagnostic(profile, optimization_indices)
        blocker = "No finite primal optimum. The feasibility model status is $(feasibility.termination_status); no artificial capacity cap was introduced."
        write_empty_or_unbounded_outputs(output_directory, solution, feasibility, length(initial_indices))
    else
        while true
            @printf("S1-B iteration %d solved: intervals=%d HC=%.9f kW status=%s\n",
                    iteration, length(optimization_indices), solution.total_capacity_kw, solution.termination_status)
            ac = validate_s1b_ac(profile, solution.capacities_kw;
                                 voltage_tolerance_pu=AC_VOLTAGE_TOLERANCE_PU)
            candidate_additions = Int[]
            isempty(ac.under_indices) || push!(candidate_additions, argmin(i -> ac.states[i].vmin, ac.under_indices))
            isempty(ac.over_indices) || push!(candidate_additions, argmax(i -> ac.states[i].vmax, ac.over_indices))
            unique!(candidate_additions)
            new_indices = [i for i in candidate_additions if !(i in optimization_indices)]
            outcome = isempty(ac.failed_indices) && isempty(ac.under_indices) && isempty(ac.over_indices) ?
                      "ac_feasible" : isempty(new_indices) ? "existing_interval_blocker" : "intervals_added"
            push!(history, (
                iteration, length(optimization_indices), solution.total_capacity_kw, solution.termination_status,
                length(ac.under_indices), length(ac.over_indices), length(ac.failed_indices), length(new_indices),
                join((timestamp_text(profile.timestamps[i]) for i in new_indices), ';'), outcome,
            ))
            if !isempty(ac.failed_indices)
                blocker = "Independent AC power flow failed to converge for $(length(ac.failed_indices)) intervals."
                break
            elseif isempty(ac.under_indices) && isempty(ac.over_indices)
                break
            elseif isempty(new_indices)
                blocker = "AC voltage violations remain at interval(s) already present in the SOCP. This is an SOCP-relaxation/AC consistency blocker; no hidden voltage margin was applied."
                break
            end
            append!(optimization_indices, new_indices)
            sort!(unique!(optimization_indices))
            iteration += 1
            solution = solve_s1b_central(profile, optimization_indices)
            if !(solution.termination_status in ACCEPTED_S1B_STATUSES && solution.has_primal)
                feasibility = feasibility_diagnostic(profile, optimization_indices)
                blocker = "Constraint generation produced no finite primal optimum; feasibility status=$(feasibility.termination_status)."
                break
            end
        end

        if solution.has_primal && ac !== nothing
            diagnostics = socp_diagnostics(solution, profile)
            println("Running optimal-face siting non-uniqueness diagnostic")
            ranges = siting_ranges(profile, optimization_indices, solution.total_capacity_kw)
            write_finite_outputs(output_directory, profile, solution, diagnostics, ac, history, ranges, blocker)
        else
            feasibility === nothing && (feasibility = feasibility_diagnostic(profile, optimization_indices))
            write_empty_or_unbounded_outputs(output_directory, solution, feasibility, length(initial_indices))
        end
    end

    write_solver_summary(
        joinpath(output_directory, "solver_summary.txt"), solution, feasibility,
        length(initial_indices), length(optimization_indices), iteration, blocker,
    )
    write_decision_report(
        joinpath(output_directory, "s1b_decision_report.md"), solution,
        length(initial_indices), length(optimization_indices), iteration, blocker,
    )
    println("S1-B outputs=$(abspath(output_directory))")
    println("termination_status=$(solution.termination_status) primal_status=$(solution.primal_status) dual_status=$(solution.dual_status)")
    solution.has_primal && println("total_voltage_constrained_hc_kw=$(solution.total_capacity_kw)")
    isempty(blocker) || println("blocker=$blocker")
end

main()
