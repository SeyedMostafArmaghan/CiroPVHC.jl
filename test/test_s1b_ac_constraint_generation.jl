using Test
using JuMP

if !isdefined(Main, :S1BMethodBenchmark)
    include(joinpath(@__DIR__, "..", "src", "benchmark", "s1b_method_benchmark.jl"))
end

@testset "S1-B production entry point preflight" begin
    repository_root = normpath(joinpath(@__DIR__, ".."))
    runner = joinpath(repository_root, "scripts", "run_s1b_ac_constraint_generation.jl")
    command = `$(Base.julia_cmd()) --project=$repository_root $runner --confirm-full-period --preflight-only`
    output = read(command, String)
    @test occursin("production_entry_point_preflight=passed", output)
    @test occursin("interval_count=52608", output)
    @test occursin("complete_day_count=1096", output)
end
const S1BCG = Main.S1BMethodBenchmark

function mock_start_result(start_id, start_name, active_count; seed=20260721)
    return (
        start_id=start_id, start_name=start_name, start_kind="test", seed=seed,
        termination_status="LOCALLY_SOLVED", primal_status="FEASIBLE_POINT",
        objective_kw=Float64(active_count), c13_kw=Float64(active_count),
        c20_kw=0.0, c24_kw=0.0, c30_kw=0.0,
        maximum_constraint_violation=0.0,
        independent_replay_max_absolute_residual=0.0,
        independent_replay_max_scaled_residual=0.0,
        independent_replay_passed=true, accepted=true, iterations=1,
        solve_time_seconds=0.01, wall_time_seconds=0.01, error_message="",
    )
end

function mock_specs(data; seed)
    return [(
        name="mock_$(index)", kind="test", seed=seed, capacities_kw=zeros(4),
        direction_limit_kw=1.0, scale_fraction=0.0,
    ) for index in 1:10]
end

function mock_solve(data, specs)
    return [mock_start_result(index, spec.name, length(data.indices); seed=spec.seed)
            for (index, spec) in enumerate(specs)]
end

function mock_replay(data, local_t, capacities)
    global_index = data.indices[local_t]
    threshold = round(Int, capacities[13])
    violation = local_t <= 3 && local_t > threshold ? 0.01 : 0.0
    return (
        global_index=global_index, timestamp=string(data.profile.timestamps[global_index]),
        converged=true, phasor_recoverable=true, maximum_equation_residual=0.0,
        maximum_scaled_residual=0.0,
        vmin_pu=0.90, vmin_bus=18, vmax_pu=1.05 + violation, vmax_bus=30,
        violation_pu=violation, violation_type=violation > 0.0 ? "maximum_voltage" : "",
        violation_bus=violation > 0.0 ? 30 : 0,
        load_multiplier=1.0, pv_factor=1.0,
        substation_p_kw=-100.0, substation_q_kvar=25.0,
        upstream_apparent_kva=hypot(100.0, 25.0),
        export_kw=100.0, export_violation_kw=0.0,
        replay_passed=violation == 0.0, failure_reason="",
    )
end

function mock_replay_with_failed_interval(data, local_t, capacities)
    global_index = data.indices[local_t]
    timestamp = string(data.profile.timestamps[global_index])
    if local_t == 1
        # A failed interval carries poisoned extremes. The substation values are
        # deliberately finite so the test proves the reductions exclude the whole
        # untrustworthy row, not merely its non-finite fields.
        return (
            global_index=global_index, timestamp=timestamp,
            converged=false, phasor_recoverable=false, maximum_equation_residual=Inf,
            maximum_scaled_residual=Inf,
            vmin_pu=NaN, vmin_bus=99, vmax_pu=NaN, vmax_bus=99,
            violation_pu=Inf, violation_type="nonconverged", violation_bus=0,
            load_multiplier=1.0, pv_factor=1.0,
            substation_p_kw=-9999.0, substation_q_kvar=9999.0,
            upstream_apparent_kva=99999.0,
            export_kw=NaN, export_violation_kw=Inf,
            replay_passed=false, failure_reason="nonconverged",
        )
    end
    vmin = local_t == 2 ? 0.93 : 0.97
    vmax = local_t == 3 ? 1.06 : 1.02
    p_kw = -100.0 - local_t
    q_kvar = 20.0 + local_t
    return (
        global_index=global_index, timestamp=timestamp,
        converged=true, phasor_recoverable=true,
        maximum_equation_residual=1e-9 * local_t,
        maximum_scaled_residual=1e-10 * local_t,
        vmin_pu=vmin, vmin_bus=local_t == 2 ? 18 : 12,
        vmax_pu=vmax, vmax_bus=local_t == 3 ? 30 : 12,
        violation_pu=0.0, violation_type="", violation_bus=0,
        load_multiplier=1.0, pv_factor=1.0,
        substation_p_kw=p_kw, substation_q_kvar=q_kvar,
        upstream_apparent_kva=hypot(p_kw, q_kvar),
        export_kw=-p_kw, export_violation_kw=0.0,
        replay_passed=true, failure_reason="",
    )
end

@testset "S1-B voltage extremes ignore failed replay intervals" begin
    repository_root = normpath(joinpath(@__DIR__, ".."))
    day = S1BCG.load_benchmark_data(repository_root)
    data = S1BCG.subset_benchmark_data(day, day.indices[1:6])
    directory = mktempdir()
    config = S1BCG.ACConstraintGenerationConfig(
        directory; batch_size=1, max_iterations=1, resume=false,
    )
    result = S1BCG.run_ac_constraint_generation(
        data, config; initial_indices=[data.indices[1]], spec_builder=mock_specs,
        solve_fn=mock_solve, replay_fn=mock_replay_with_failed_interval,
    )
    summary = result.history[1]
    @test summary.replay_failure_count == 1
    @test isfinite(summary.minimum_voltage_pu)
    @test summary.minimum_voltage_pu == 0.93
    @test summary.minimum_voltage_bus == 18
    @test summary.minimum_voltage_timestamp == string(data.profile.timestamps[data.indices[2]])
    @test isfinite(summary.maximum_voltage_pu)
    @test summary.maximum_voltage_pu == 1.06
    @test summary.maximum_voltage_bus == 30
    @test summary.maximum_voltage_timestamp == string(data.profile.timestamps[data.indices[3]])
    @test summary.minimum_voltage_bus != 99
    @test summary.maximum_voltage_bus != 99

    # Sibling extremes must also exclude the failed interval. Intervals 2..6 carry
    # p_kw = -100 - local_t and q_kvar = 20 + local_t, so the trustworthy extremes
    # are fully determined and none of them may equal the poisoned values.
    @test isfinite(summary.maximum_equation_residual)
    @test summary.maximum_equation_residual == 1e-9 * 6
    @test isfinite(summary.maximum_scaled_residual)
    @test summary.maximum_scaled_residual == 1e-10 * 6
    @test summary.minimum_substation_p_kw == -106.0
    @test summary.maximum_substation_p_kw == -102.0
    @test summary.minimum_substation_q_kvar == 22.0
    @test summary.maximum_substation_q_kvar == 26.0
    @test summary.maximum_upstream_apparent_kva == hypot(-106.0, 26.0)
    @test summary.minimum_substation_p_kw != -9999.0
    @test summary.maximum_substation_q_kvar != 9999.0
    @test summary.maximum_upstream_apparent_kva != 99999.0

    # Failure detection and violation accounting stay driven by all rows.
    @test summary.replay_count == 6
    @test !isfinite(summary.max_violation_pu)
    @test summary.violating_count >= 1
    @test summary.stop_reason == "replay_failure_limit"
end

@testset "S1-B no-export tolerance is bound to the repository tolerance" begin
    # Not a restatement of the literal: the benchmark constant must equal the
    # S2UnmanagedEVConfig default it mirrors, so a change on either side fails here.
    @test S1BCG.NO_EXPORT_TOL_KW == S1BCG.CiroPVHC.S2UnmanagedEVConfig().no_export_tol_kw
end

@testset "S1-B no-export sign convention, units, and backward compatibility" begin
    repository_root = normpath(joinpath(@__DIR__, ".."))
    day = S1BCG.load_benchmark_data(repository_root)
    one = S1BCG.subset_benchmark_data(day, [day.indices[25]])

    # Backward compatibility: the default build is byte-identical in policy terms
    # to the pre-change model — no no-export rows at all.
    open_bundle = S1BCG.build_ac_opf_model(one)
    @test open_bundle.no_export_active == false
    @test open_bundle.no_export_constraint_count == 0
    @test S1BCG.effective_configuration(one).export_allowed == true
    @test S1BCG.effective_configuration(one).no_export_active == false

    ne = S1BCG.build_ac_opf_model(one; no_export_active=true)
    @test ne.no_export_active == true
    @test ne.no_export_constraint_count == length(one.indices)
    @test S1BCG.effective_configuration(one; no_export_active=true).export_allowed == false
    @test S1BCG.effective_configuration(one; no_export_active=true).no_export_active == true

    # Units: the model bound is the dimensionless zero, so no kW value is ever
    # placed next to the per-unit variable P. The kW audit tolerance is reported
    # in per unit too, and that conversion divides by base power rather than
    # using the raw kW number.
    @test ne.no_export_bound_pu == 0.0
    @test ne.no_export_tol_pu == S1BCG.NO_EXPORT_TOL_KW / one.base_power_kw
    @test ne.no_export_tol_pu != S1BCG.NO_EXPORT_TOL_KW
    @test one.base_power_kw > 1.0
    # The audit tolerance must never become the model bound: if it did, the
    # optimum would sit on it and the replay would flag numerical noise forever.
    @test ne.no_export_bound_pu != -ne.no_export_tol_pu

    # Sign convention: root branch flow positive means import. With zero PV at a
    # loaded interval the feeder must import, so substation_p_kw > 0 and the
    # export magnitude used by the replay is its negation.
    zero_caps = Dict(bus => 0.0 for bus in S1BCG.CANDIDATE_BUSES)
    st = S1BCG.exact_ac_state(one, 1, zero_caps)
    @test st.substation_p_kw > 0.0
    @test S1BCG.root_branch_ids(one) == ne.root_branches
    row = S1BCG._cg_replay_interval(one, 1, zero_caps; no_export_active=true)
    @test row.export_kw == -st.substation_p_kw
    @test row.export_kw < 0.0
    @test row.export_violation_kw == 0.0
    @test row.replay_passed
end

@testset "S1-B no-export constraint actually binds the optimum" begin
    repository_root = normpath(joinpath(@__DIR__, ".."))
    day = S1BCG.load_benchmark_data(repository_root)
    peak_pv = day.indices[argmax(day.profile.pv_profile[day.indices])]
    one = S1BCG.subset_benchmark_data(day, [peak_pv])

    function solve_with(no_export)
        bundle = S1BCG.build_ac_opf_model(one; no_export_active=no_export)
        S1BCG.initialize_ac_model!(bundle, one, zeros(4))
        optimize!(bundle.model)
        caps = Dict(bus => value(bundle.capacity_kw[bus]) for bus in S1BCG.CANDIDATE_BUSES)
        return caps, S1BCG.exact_ac_state(one, 1, caps)
    end

    open_caps, open_state = solve_with(false)
    ne_caps, ne_state = solve_with(true)

    # Without the constraint the optimum exports heavily at peak PV.
    @test open_state.substation_p_kw < -1.0
    # With it, the independently replayed upstream flow stays at or above zero
    # within tolerance. This is the regression the whole change exists for.
    @test ne_state.substation_p_kw >= -1.0
    # And the constraint is genuinely active, not inert.
    @test sum(values(ne_caps)) < sum(values(open_caps))

    ne_row = S1BCG._cg_replay_interval(one, 1, ne_caps; no_export_active=true)
    @test ne_row.export_violation_kw == 0.0
    open_row = S1BCG._cg_replay_interval(one, 1, open_caps; no_export_active=true)
    @test open_row.export_violation_kw > 0.0
    @test !open_row.replay_passed
    # Same capacities judged under the old policy must still pass: parameterising
    # must not retroactively invalidate export-allowed results.
    @test S1BCG._cg_replay_interval(one, 1, open_caps; no_export_active=false).replay_passed
end

@testset "S1-B addition selection keeps both categories independent" begin
    mk(gi, vpu, ekw; passed=false) = (
        global_index=gi, violation_pu=vpu, export_violation_kw=ekw,
        replay_passed=passed,
    )
    open_config = S1BCG.ACConstraintGenerationConfig(mktempdir(); batch_size=3, no_export_active=false)
    ne_config = S1BCG.ACConstraintGenerationConfig(mktempdir(); batch_size=3, no_export_active=true)

    # Worst voltage and worst export are different intervals: one of each, and the
    # voltage offender is not starved by the much larger export number.
    rows = [
        mk(2, 0.05, 0.0),
        mk(3, 0.0, 900.0),
        mk(4, 0.01, 10.0),
        mk(5, 0.0, 0.0; passed=true),
    ]
    @test S1BCG.select_constraint_additions(rows, Int[], ne_config) == [3, 2]

    # Same interval worst on both counts: added once, not twice.
    both = [mk(7, 0.09, 500.0), mk(8, 0.01, 1.0)]
    @test S1BCG.select_constraint_additions(both, Int[], ne_config) == [7]

    # Already-active intervals are never re-added; the next-worst offender of the
    # export category (interval 4) takes over, and the voltage pick is unaffected.
    @test S1BCG.select_constraint_additions(rows, [3], ne_config) == [4, 2]
    # With every export offender active, only the voltage category contributes.
    @test S1BCG.select_constraint_additions(rows, [3, 4], ne_config) == [2]

    # Untrustworthy intervals outrank both categories.
    failed = [mk(9, Inf, Inf), mk(10, 0.5, 800.0)]
    @test first(S1BCG.select_constraint_additions(failed, Int[], ne_config)) == 9

    # Export-allowed mode reproduces the previous ranking behaviour exactly.
    @test S1BCG.select_constraint_additions(rows, Int[], open_config) ==
          [row.global_index for row in S1BCG.rank_replay_violations(rows, Int[])][1:3]
end

@testset "S1-B boundary bracketing and direction validation" begin
    bracket = S1BCG._bisect_feasible_limit(x -> x <= 7.25, 1.0; bisections=50)
    @test bracket.feasible_lower_kw <= 7.25 < bracket.infeasible_upper_kw
    @test isapprox(bracket.limit_kw, 7.25; atol=1e-12)
    @test_throws ArgumentError S1BCG._bisect_feasible_limit(x -> true, 1.0; max_doublings=2)
    @test_throws ArgumentError S1BCG._bisect_feasible_limit(x -> x > 0.0, 1.0)
    @test_throws ArgumentError S1BCG._validate_direction(zeros(4))
    @test_throws ArgumentError S1BCG._validate_direction([1.1, -0.1, 0.0, 0.0])
    @test_throws ArgumentError S1BCG._validate_direction([NaN, 0.0, 0.0, 1.0])
    @test S1BCG._validate_direction([1.0, 0.0, 0.0, 0.0]) == [1.0, 0.0, 0.0, 0.0]
    near_zero = [1.0 - 3e-14, 1e-14, 1e-14, 1e-14]
    @test S1BCG._validate_direction(near_zero) == near_zero
end

@testset "S1-B warm starts remain starts and best selection is strict" begin
    repository_root = normpath(joinpath(@__DIR__, ".."))
    day = S1BCG.load_benchmark_data(repository_root)
    one = S1BCG.subset_benchmark_data(day, [day.indices[25]])
    bundle = S1BCG.build_ac_opf_model(one)
    S1BCG.initialize_ac_model!(bundle, one, zeros(4))
    @test all(!is_fixed(bundle.capacity_kw[bus]) for bus in S1BCG.CANDIDATE_BUSES)

    valid = mock_start_result(1, "valid", 4)
    false_accept = merge(valid, (start_name="failed_replay", objective_kw=999.0,
                                 independent_replay_passed=false))
    failed_status = merge(valid, (start_name="failed_status", objective_kw=888.0,
                                  termination_status="SOLVER_ERROR"))
    nonfinite = merge(valid, (start_name="nonfinite", objective_kw=Inf))
    @test S1BCG.best_ac_result([false_accept, failed_status, nonfinite, valid]).start_name == "valid"

    invalid_spec = (
        name="invalid_length", kind="test_failure", seed=1,
        capacities_kw=zeros(3), direction_limit_kw=0.0, scale_fraction=0.0,
    )
    valid_spec = (
        name="valid_after_failure", kind="test_recovery", seed=1,
        capacities_kw=zeros(4), direction_limit_kw=0.0, scale_fraction=0.0,
    )
    recovery_results = S1BCG.solve_ac_multistart(one, [invalid_spec, valid_spec])
    @test length(recovery_results) == 2
    @test recovery_results[1].termination_status == "INITIALIZATION_FAILED"
    @test !recovery_results[1].accepted
    @test recovery_results[2].termination_status != "INITIALIZATION_FAILED"
end

@testset "S1-B replay ranking and checkpoint resume equivalence" begin
    repository_root = normpath(joinpath(@__DIR__, ".."))
    day = S1BCG.load_benchmark_data(repository_root)
    data = S1BCG.subset_benchmark_data(day, day.indices[1:6])
    rows = [
        (global_index=2, replay_passed=false, violation_pu=0.01),
        (global_index=3, replay_passed=false, violation_pu=Inf),
        (global_index=4, replay_passed=false, violation_pu=0.02),
        (global_index=5, replay_passed=false, violation_pu=0.02),
    ]
    @test getfield.(S1BCG.rank_replay_violations(rows, [2]), :global_index) == [3, 4, 5]

    interrupted_directory = mktempdir()
    first_config = S1BCG.ACConstraintGenerationConfig(
        interrupted_directory; batch_size=1, max_iterations=1, resume=false,
    )
    first = S1BCG.run_ac_constraint_generation(
        data, first_config; initial_indices=[data.indices[1]], spec_builder=mock_specs,
        solve_fn=mock_solve, replay_fn=mock_replay,
    )
    @test first.status == "max_iterations"
    resumed_config = S1BCG.ACConstraintGenerationConfig(
        interrupted_directory; batch_size=1, max_iterations=3, resume=true,
    )
    resumed = S1BCG.run_ac_constraint_generation(
        data, resumed_config; initial_indices=[data.indices[1]], spec_builder=mock_specs,
        solve_fn=mock_solve, replay_fn=mock_replay,
    )
    uninterrupted_directory = mktempdir()
    uninterrupted_config = S1BCG.ACConstraintGenerationConfig(
        uninterrupted_directory; batch_size=1, max_iterations=3, resume=false,
    )
    uninterrupted = S1BCG.run_ac_constraint_generation(
        data, uninterrupted_config; initial_indices=[data.indices[1]], spec_builder=mock_specs,
        solve_fn=mock_solve, replay_fn=mock_replay,
    )
    @test resumed.resumed
    @test resumed.status == uninterrupted.status == "converged"
    @test resumed.active_indices == uninterrupted.active_indices
    @test resumed.capacities_kw == uninterrupted.capacities_kw
    @test isapprox(sum(values(resumed.capacities_kw)), resumed.history[end].objective_kw)
    deterministic_history_fields = (
        :iteration, :active_before, :active_after, :accepted_start_count,
        :objective_kw, :c13_kw, :c20_kw, :c24_kw, :c30_kw,
        :replay_count, :replay_failure_count, :violating_count, :max_violation_pu,
        :worst_violation_bus, :added_indices, :added_timestamps, :stop_reason,
    )
    project_history(history) = [Tuple(getproperty(row, field) for field in deterministic_history_fields)
                                for row in history]
    @test project_history(resumed.history) == project_history(uninterrupted.history)
    @test all(diff([row.active_after for row in resumed.history]) .>= 0)
    @test resumed.history[1].worst_violation_bus == 30
    @test resumed.history[1].maximum_upstream_apparent_kva == hypot(100.0, 25.0)
    @test occursin("|test|20260721|LOCALLY_SOLVED|true|true|", resumed.history[1].start_summary)
    starts_header = readlines(joinpath(interrupted_directory, "checkpoints", "iteration_001_starts.csv"))[1]
    replay_header = readlines(joinpath(interrupted_directory, "checkpoints", "iteration_001_replay.csv"))[1]
    @test occursin("seed", starts_header)
    @test occursin("solve_time_seconds", starts_header)
    @test occursin("upstream_apparent_kva", replay_header)
    @test occursin("violation_bus", replay_header)
end
