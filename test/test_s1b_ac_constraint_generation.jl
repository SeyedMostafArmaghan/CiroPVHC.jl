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
