using Dates
using Printf

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
include(joinpath(REPOSITORY_ROOT, "src", "benchmark", "s1b_method_benchmark.jl"))
using .S1BMethodBenchmark

const OUTPUT_DIRECTORY = joinpath(REPOSITORY_ROOT, "results", "s1b_method_benchmark")

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

function repository_commit()
    return try
        readchomp(`git -C $REPOSITORY_ROOT rev-parse HEAD`)
    catch
        "unknown"
    end
end

function write_configuration(path, data)
    config = effective_configuration(data)
    open(path, "w") do io
        println(io, "stage=S1-B one-day AC-vs-strengthened-SOCP diagnostic benchmark")
        println(io, "repository_commit_at_start=$(repository_commit())")
        for name in propertynames(config)
            value = getfield(config, name)
            println(io, "$(name)=$(value)")
        end
        println(io, "ipopt_version=$(Base.pkgversion(S1BMethodBenchmark.Ipopt))")
        println(io, "clarabel_version=$(Base.pkgversion(S1BMethodBenchmark.Clarabel))")
        println(io, "ac_global_optimum_claimed=false")
        println(io, "socp_lambda_zero_is_achievable_hc=false_unless_exact_and_ac_feasible")
        println(io, "three_year_validation_performed=false")
        println(io, "constraint_generation_performed=false")
    end
end

function write_ac_results(path, results)
    columns = (
        "start_id", "start_name", "start_kind", "seed",
        "initial_c13_kw", "initial_c20_kw", "initial_c24_kw", "initial_c30_kw",
        "initial_total_kw", "initial_direction_limit_kw", "initial_scale_fraction",
        "initial_ac_feasible", "termination_status", "primal_status", "objective_kw",
        "c13_kw", "c20_kw", "c24_kw", "c30_kw", "maximum_constraint_violation",
        "nlp_vmin_pu", "nlp_vmax_pu", "ac_replay_feasible", "ac_replay_vmin_pu",
        "ac_replay_vmax_pu", "ac_replay_voltage_difference_pu", "accepted",
        "iterations", "solve_time_seconds", "wall_time_seconds",
    )
    rows = [Tuple(getfield(result, Symbol(column)) for column in columns) for result in results]
    write_csv(path, columns, rows)
end

function write_best_ac(path, best, nonuniqueness)
    columns = (
        "available", "start_id", "start_name", "classification", "global_optimum_claimed",
        "c13_kw", "c20_kw", "c24_kw", "c30_kw", "total_hc_kw",
        "termination_status", "primal_status", "maximum_constraint_violation",
        "nlp_vmin_pu", "nlp_vmax_pu", "ac_vmin_pu", "ac_vmax_pu",
        "ac_voltage_violations", "ac_voltage_violation_intervals",
        "max_import_kw", "max_export_kw",
        "max_active_losses_kw", "max_reactive_losses_kvar", "max_ac_equation_residual",
        "maximum_replay_voltage_difference_pu", "near_best_start_count",
        "near_best_objective_range_kw", "maximum_allocation_spread_kw",
        "spatial_nonuniqueness_detected",
    )
    if best === nothing
        write_csv(path, columns, [(
            false, 0, "", "no accepted AC solution", false,
            NaN, NaN, NaN, NaN, NaN, "", "", Inf, NaN, NaN, NaN, NaN,
            0, 0, NaN, NaN, NaN, NaN, Inf, Inf, nonuniqueness.near_best_count,
            nonuniqueness.objective_range_kw, nonuniqueness.maximum_allocation_spread_kw,
            nonuniqueness.spatial_nonuniqueness_detected,
        )])
        return
    end
    d = best.diagnostics
    replay = d.replay
    write_csv(path, columns, [(
        true, best.start_id, best.start_name, "best locally optimal AC-feasible solution", false,
        best.c13_kw, best.c20_kw, best.c24_kw, best.c30_kw, best.objective_kw,
        best.termination_status, best.primal_status, best.maximum_constraint_violation,
        best.nlp_vmin_pu, best.nlp_vmax_pu, replay.vmin, replay.vmax,
        replay.undervoltage_count + replay.overvoltage_count,
        replay.undervoltage_intervals + replay.overvoltage_intervals,
        replay.max_import_kw, replay.max_export_kw, replay.max_active_losses_kw,
        replay.max_reactive_losses_kvar, replay.max_equation_residual,
        d.maximum_replay_voltage_difference, nonuniqueness.near_best_count,
        nonuniqueness.objective_range_kw, nonuniqueness.maximum_allocation_spread_kw,
        nonuniqueness.spatial_nonuniqueness_detected,
    )])
end

function write_ac_operating_points(path, data, best)
    columns = (
        "interval", "timestamp", "load_multiplier", "pv_availability", "converged",
        "vmin_pu", "vmin_bus", "vmax_pu", "vmax_bus", "undervoltage_bus_count",
        "overvoltage_bus_count", "substation_p_kw", "substation_q_kvar",
        "active_losses_kw", "reactive_losses_kvar", "maximum_ac_equation_residual",
    )
    best === nothing && return write_csv(path, columns, Tuple[])
    rows = Tuple[]
    for (local_t, state) in enumerate(best.diagnostics.replay.states)
        index = data.indices[local_t]
        push!(rows, (
            local_t, timestamp_text(data.profile.timestamps[index]),
            data.profile.load_multiplier[index], data.profile.pv_profile[index], state.converged,
            minimum(state.voltage_pu), argmin(state.voltage_pu),
            maximum(state.voltage_pu), argmax(state.voltage_pu),
            count(v -> v < S1BMethodBenchmark.VMIN_PU - S1BMethodBenchmark.AC_VOLTAGE_TOL, state.voltage_pu),
            count(v -> v > S1BMethodBenchmark.VMAX_PU + S1BMethodBenchmark.AC_VOLTAGE_TOL, state.voltage_pu),
            state.substation_p_kw, state.substation_q_kvar,
            state.active_losses_kw, state.reactive_losses_kvar, state.maximum_equation_residual,
        ))
    end
    write_csv(path, columns, rows)
end

function write_socp_sweep(path, results)
    columns = (
        "lambda", "termination_status", "primal_status", "c13_kw", "c20_kw", "c24_kw",
        "c30_kw", "total_hc_kw", "normalized_hc", "normalized_penalty_measure",
        "weighted_penalty", "objective_dimensionless", "socp_vmin_pu", "socp_vmax_pu",
        "min_soc_gap_pu2", "max_soc_gap_pu2", "maximum_relative_soc_gap",
        "maximum_branch_flow_residual", "mean_active_losses_kw", "max_active_losses_kw",
        "max_reactive_losses_kvar", "worst_gap_timestamp", "worst_gap_interval",
        "worst_gap_branch",
        "ac_converged", "ac_feasible", "ac_vmin_pu", "ac_vmax_pu",
        "ac_undervoltage_count", "ac_overvoltage_count", "ac_undervoltage_intervals",
        "ac_overvoltage_intervals",
        "max_socp_ac_voltage_difference_pu", "max_import_kw", "max_export_kw",
        "ac_max_active_losses_kw", "approximately_exact", "solve_time_seconds",
        "wall_time_seconds",
    )
    rows = [Tuple(getfield(result, Symbol(column)) for column in columns) for result in results]
    write_csv(path, columns, rows)
end

function write_socp_ac_validation(path, results)
    columns = (
        "lambda", "validated_intervals", "failed_intervals", "ac_feasible",
        "ac_vmin_pu", "ac_vmax_pu", "undervoltage_bus_count", "overvoltage_bus_count",
        "undervoltage_intervals", "overvoltage_intervals",
        "max_import_kw", "max_export_kw", "max_active_losses_kw",
        "maximum_socp_ac_voltage_difference_pu", "maximum_relative_soc_gap",
        "approximately_exact",
    )
    rows = [(
        result.lambda,
        result.diagnostics === nothing ? 0 : length(result.diagnostics.replay.states),
        result.diagnostics === nothing ? 48 : result.diagnostics.replay.failed,
        result.ac_feasible, result.ac_vmin_pu, result.ac_vmax_pu,
        result.ac_undervoltage_count, result.ac_overvoltage_count,
        result.ac_undervoltage_intervals, result.ac_overvoltage_intervals,
        result.max_import_kw, result.max_export_kw, result.ac_max_active_losses_kw,
        result.max_socp_ac_voltage_difference_pu, result.maximum_relative_soc_gap,
        result.approximately_exact,
    ) for result in results]
    write_csv(path, columns, rows)
end

function comparison_rows(ac_results, best, socp_results)
    rows = Tuple[]
    accepted_count = count(result -> result.accepted, ac_results)
    if best !== nothing
        replay = best.diagnostics.replay
        push!(rows, (
            "AC-OPF multistart best", "best_of_$(length(ac_results))_starts", best.objective_kw,
            best.c13_kw, best.c20_kw, best.c24_kw, best.c30_kw,
            best.termination_status, replay.ac_feasible, replay.vmin, replay.vmax,
            replay.undervoltage_count + replay.overvoltage_count, 0.0,
            replay.max_active_losses_kw, replay.max_import_kw, replay.max_export_kw,
            best.maximum_constraint_violation, best.solve_time_seconds,
            "local optimum; $(accepted_count) accepted starts", "initial_point_multistart",
        ))
    end
    for result in socp_results
        push!(rows, (
            "strengthened SOCP", "lambda=$(result.lambda)", result.total_hc_kw,
            result.c13_kw, result.c20_kw, result.c24_kw, result.c30_kw,
            result.termination_status, result.ac_feasible, result.ac_vmin_pu, result.ac_vmax_pu,
            result.ac_undervoltage_count + result.ac_overvoltage_count,
            result.maximum_relative_soc_gap, result.ac_max_active_losses_kw,
            result.max_import_kw, result.max_export_kw, result.maximum_branch_flow_residual,
            result.solve_time_seconds,
            result.lambda == 0.0 ? "convex relaxation upper bound; not achievable unless exact" :
                "penalized relaxation; not an optimum certificate for original HC",
            "penalty_lambda",
        ))
    end
    return rows
end

function write_comparison(path, ac_results, best, socp_results)
    columns = (
        "method", "variant", "total_hc_kw", "c13_kw", "c20_kw", "c24_kw", "c30_kw",
        "solver_status", "ac_feasible", "ac_vmin_pu", "ac_vmax_pu",
        "ac_voltage_violation_count", "maximum_relative_soc_gap", "max_active_losses_kw",
        "max_import_kw", "max_export_kw", "maximum_residual", "solve_time_seconds",
        "local_global_status", "sensitivity_axis",
    )
    write_csv(path, columns, comparison_rows(ac_results, best, socp_results))
end

function decision_evidence(ac_results, best, socp_results, nonuniqueness)
    accepted_count = count(result -> result.accepted, ac_results)
    ac_stable = best !== nothing && accepted_count >= 3 && nonuniqueness.near_best_count >= 3
    exact_indices = findall(result -> result.approximately_exact, socp_results)
    stable_pairs = Tuple{Int,Int}[]
    for i in 1:(length(socp_results) - 1)
        if socp_results[i].approximately_exact && socp_results[i + 1].approximately_exact
            scale = best === nothing ? max(socp_results[i].total_hc_kw, 1.0) : best.objective_kw
            relative_change = abs(socp_results[i + 1].total_hc_kw - socp_results[i].total_hc_kw) / scale
            relative_change <= 0.01 && push!(stable_pairs, (i, i + 1))
        end
    end
    closest_exact = isempty(exact_indices) || best === nothing ? nothing :
        argmin(i -> abs(socp_results[i].total_hc_kw - best.objective_kw), exact_indices)
    closest_distance = closest_exact === nothing ? Inf :
        abs(socp_results[closest_exact].total_hc_kw - best.objective_kw) / best.objective_kw
    keep_socp = !isempty(stable_pairs) && closest_distance <= 0.01
    decision = keep_socp ? "retain strengthened SOCP" :
               ac_stable ? "move S1-B to AC-OPF" : "inconclusive"
    return (
        decision=decision,
        accepted_ac_starts=accepted_count,
        ac_stable=ac_stable,
        exact_lambda_count=length(exact_indices),
        stable_exact_pair_count=length(stable_pairs),
        closest_exact_index=closest_exact,
        closest_exact_distance_fraction=closest_distance,
    )
end

function write_report(path, data, ac_results, best, socp_results, nonuniqueness, evidence)
    lambda_zero = first(socp_results)
    exact_results = [result for result in socp_results if result.approximately_exact]
    best_gap_result = argmin(result -> result.maximum_relative_soc_gap, socp_results)
    strongest = last(socp_results)
    open(path, "w") do io
        println(io, "# S1-B one-day method decision benchmark")
        println(io)
        println(io, "## Scope and common configuration")
        println(io)
        println(io, "Both methods use all 48 half-hour intervals on $(BENCHMARK_DATE), one shared capacity vector at buses 13/20/24/30, the same load and PV availability, 10 MVA/12.66 kV bases, V0=1.00 p.u., and 0.90-1.05 p.u. voltage limits. Curtailment, site caps, gamma caps, no-export, loss caps, thermal ratings, and transformer limits are absent. This is a one-day diagnostic, not the three-year result.")
        println(io)
        println(io, "## AC-OPF multistart")
        println(io)
        println(io, "- Starts executed: $(length(ac_results)); accepted AC-feasible local solutions: $(evidence.accepted_ac_starts).")
        if best === nothing
            println(io, "- No AC solution passed the declared residual and independent replay gates.")
        else
            println(io, @sprintf("- Best locally optimal AC-feasible HC: %.9f kW (C13=%.9f, C20=%.9f, C24=%.9f, C30=%.9f).",
                best.objective_kw, best.c13_kw, best.c20_kw, best.c24_kw, best.c30_kw))
            println(io, @sprintf("- Independent replay: Vmin=%.9f, Vmax=%.9f, max import=%.6f kW, max export=%.6f kW, max active loss=%.6f kW.",
                best.diagnostics.replay.vmin, best.diagnostics.replay.vmax,
                best.diagnostics.replay.max_import_kw, best.diagnostics.replay.max_export_kw,
                best.diagnostics.replay.max_active_losses_kw))
            println(io, @sprintf("- Maximum NLP constraint residual %.3e; maximum NLP/replay voltage difference %.3e p.u.",
                best.maximum_constraint_violation, best.diagnostics.maximum_replay_voltage_difference))
            println(io, "- No global optimum is claimed.")
        end
        println(io, "- Spatial non-uniqueness among near-best starts: $(nonuniqueness.spatial_nonuniqueness_detected); maximum allocation spread=$(nonuniqueness.maximum_allocation_spread_kw) kW.")
        println(io, "  This is evidence across the declared starts, not a proof of global spatial uniqueness.")
        println(io)
        println(io, "## Strengthened SOCP sweep")
        println(io)
        println(io, "The dimensionless objective is `HC/3715 - lambda * mean_active_loss/3715`. The predeclared exactness gate requires maximum normalized SOC residual <=1e-5, zero AC voltage violations at 1e-5 p.u., and maximum SOCP/AC voltage difference <=1e-4 p.u.")
        println(io)
        println(io, @sprintf("- Lambda=0 convex relaxation objective: %.9f kW; relative SOC gap %.3e; AC feasible=%s. It is an upper bound, not achievable HC while non-exact.",
            lambda_zero.total_hc_kw, lambda_zero.maximum_relative_soc_gap,
            lambda_zero.ac_feasible ? "yes" : "no"))
        println(io, "- Approximately exact sweep points: $(length(exact_results)) of $(length(socp_results)); stable adjacent exact pairs: $(evidence.stable_exact_pair_count).")
        println(io, @sprintf("- Best gap in the sweep occurs at lambda=%g and is still %.6e; AC feasible=%s.",
            best_gap_result.lambda, best_gap_result.maximum_relative_soc_gap,
            best_gap_result.ac_feasible ? "yes" : "no"))
        println(io, @sprintf("- At lambda=%g, HC falls %.3f%% from the lambda=0 upper bound to %.6f kW, but the point remains non-exact and AC-infeasible.",
            strongest.lambda,
            100.0 * (lambda_zero.total_hc_kw - strongest.total_hc_kw) / lambda_zero.total_hc_kw,
            strongest.total_hc_kw))
        if best !== nothing
            println(io, @sprintf("- The strongest-penalty SOCP point is %.3f%% above the best AC-OPF HC, but it is not achievable under AC validation.",
                100.0 * (strongest.total_hc_kw - best.objective_kw) / best.objective_kw))
        end
        for result in socp_results
            println(io, @sprintf("- lambda=%g: HC=%.6f kW, rel_gap=%.3e, AC=%s, exact=%s, AC V=[%.6f, %.6f].",
                result.lambda, result.total_hc_kw, result.maximum_relative_soc_gap,
                result.ac_feasible ? "feasible" : "infeasible",
                result.approximately_exact ? "yes" : "no",
                result.ac_vmin_pu, result.ac_vmax_pu))
        end
        println(io)
        println(io, "## Decision")
        println(io)
        println(io, "**$(evidence.decision)**")
        println(io)
        if evidence.decision == "retain strengthened SOCP"
            println(io, "A stable adjacent lambda region passed all exactness and AC gates and stayed within 1% of the best AC-OPF solution.")
        elseif evidence.decision == "move S1-B to AC-OPF"
            println(io, "AC-OPF produced a repeatable independently replayed solution, while the penalty sweep did not provide a stable, approximately exact, AC-feasible region within 1% of it. Choosing a single penalty would therefore be fragile or would materially alter HC.")
        else
            println(io, "Neither method supplied enough stable evidence under the predeclared gates for a defensible central-method choice.")
        end
        println(io)
        println(io, "## Scientific limitations")
        println(io)
        println(io, "The AC result is local, not globally certified. This benchmark covers one critical day only and has no thermal validation because real ampacity data are absent. It does not run the 32-day design, three-year validation, constraint generation, robust optimization, S1-C, or sensitivity cases. The earlier invalid SOCP result remains preserved in its original commit and files.")
    end
end

function main()
    mkpath(OUTPUT_DIRECTORY)
    data = load_benchmark_data(REPOSITORY_ROOT)
    write_configuration(joinpath(OUTPUT_DIRECTORY, "effective_configuration.txt"), data)
    println("Effective configuration written before solve")
    println("date=$(BENCHMARK_DATE) intervals=$(length(data.indices)) site_cap=false no_export=false curtailment=false thermal=false loss_cap=false")

    specs = multistart_specs(data)
    ac_results = solve_ac_multistart(data, specs)
    best = best_ac_result(ac_results)
    nonuniqueness = multistart_nonuniqueness(ac_results)
    socp_results = solve_socp_penalty_sweep(data)
    evidence = decision_evidence(ac_results, best, socp_results, nonuniqueness)

    write_ac_results(joinpath(OUTPUT_DIRECTORY, "ac_multistart_results.csv"), ac_results)
    write_best_ac(joinpath(OUTPUT_DIRECTORY, "ac_best_solution.csv"), best, nonuniqueness)
    write_ac_operating_points(joinpath(OUTPUT_DIRECTORY, "ac_operating_point_diagnostics.csv"), data, best)
    write_socp_sweep(joinpath(OUTPUT_DIRECTORY, "socp_penalty_sweep.csv"), socp_results)
    write_socp_ac_validation(joinpath(OUTPUT_DIRECTORY, "socp_ac_validation.csv"), socp_results)
    write_comparison(joinpath(OUTPUT_DIRECTORY, "method_comparison.csv"), ac_results, best, socp_results)
    write_report(
        joinpath(OUTPUT_DIRECTORY, "s1b_method_decision_report.md"),
        data, ac_results, best, socp_results, nonuniqueness, evidence,
    )
    println("decision=$(evidence.decision)")
    best === nothing || @printf("best_ac_hc_kw=%.9f\n", best.objective_kw)
    println("outputs=$(abspath(OUTPUT_DIRECTORY))")
end

main()
