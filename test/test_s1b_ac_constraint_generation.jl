using Test
using JuMP

if !isdefined(Main, :S1BMethodBenchmark)
    include(joinpath(@__DIR__, "..", "src", "benchmark", "s1b_method_benchmark.jl"))
end
const S1BCG = Main.S1BMethodBenchmark

function mock_start_result(start_id, start_name, active_count)
    return (
        start_id=start_id, start_name=start_name, start_kind="test",
        termination_status="LOCALLY_SOLVED", primal_status="FEASIBLE_POINT",
        objective_kw=Float64(active_count), c13_kw=Float64(active_count),
        c20_kw=0.0, c24_kw=0.0, c30_kw=0.0,
        independent_replay_passed=true, accepted=true, error_message="",
    )
end

function mock_specs(data; seed)
    return [(
        name="mock_$(index)", kind="test", seed=seed, capacities_kw=zeros(4),
        direction_limit_kw=1.0, scale_fraction=0.0,
    ) for index in 1:10]
end

function mock_solve(data, specs)
    return [mock_start_result(index, spec.name, length(data.indices))
            for (index, spec) in enumerate(specs)]
end

function mock_replay(data, local_t, capacities)
    global_index = data.indices[local_t]
    threshold = round(Int, capacities[13])
    violation = local_t <= 3 && local_t > threshold ? 0.01 : 0.0
    return (
        global_index=global_index, timestamp=string(data.profile.timestamps[global_index]),
        converged=true, phasor_recoverable=true, maximum_equation_residual=0.0,
        vmin_pu=0.90, vmax_pu=1.05 + violation, violation_pu=violation,
        replay_passed=violation == 0.0, failure_reason="",
    )
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
    @test resumed.history == uninterrupted.history
    @test all(diff([row.active_after for row in resumed.history]) .>= 0)
end
