using Test
using JuMP
using CiroPVHC
using Dates

if !isdefined(Main, :S1BMethodBenchmark)
    include(joinpath(@__DIR__, "..", "src", "benchmark", "s1b_method_benchmark.jl"))
end
const S1BMB = Main.S1BMethodBenchmark

@testset "S1-B method benchmark common configuration" begin
    repository_root = normpath(joinpath(@__DIR__, ".."))
    data = S1BMB.load_benchmark_data(repository_root)
    config = S1BMB.effective_configuration(data)

    @test length(data.indices) == 48
    @test all(Date(data.profile.timestamps[index]) == S1BMB.BENCHMARK_DATE for index in data.indices)
    @test all(diff(data.profile.timestamps[data.indices]) .== Minute(30))
    @test config.candidate_buses == (13, 20, 24, 30)
    @test config.shared_capacity_vector
    @test !config.curtailment_active
    @test config.export_allowed
    @test !config.no_export_active
    @test !config.site_cap_active
    @test !config.gamma_cap_active
    @test !config.thermal_constraints_active
    @test !config.loss_cap_active
    @test !config.computational_capacity_bound_active
    @test config.squared_voltage_min == 0.90^2
    @test config.squared_voltage_max == 1.05^2
    @test config.penalty_lambdas == (0.0, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0)
end

@testset "S1-B exact AC model structure and independent replay" begin
    repository_root = normpath(joinpath(@__DIR__, ".."))
    data = S1BMB.load_benchmark_data(repository_root)
    bundle = S1BMB.build_ac_opf_model(data)
    variable_names = [name(variable) for variable in all_variables(bundle.model)]

    @test bundle.exact_current_equality
    @test bundle.interval_count == 48
    @test bundle.shared_capacity_variable_count == 4
    @test !bundle.computational_capacity_bound_active
    @test count(startswith("capacity_kw"), variable_names) == 4
    @test !any(contains("curtail"), variable_names)
    @test !any(contains("export"), variable_names)
    @test all(!has_upper_bound(bundle.capacity_kw[bus]) for bus in S1BMB.CANDIDATE_BUSES)
    @test all(!has_lower_bound(bundle.P[branch, t]) for branch in 1:32 for t in 1:48)
    @test all(!has_upper_bound(bundle.ell[branch, t]) for branch in 1:32 for t in 1:48)
    @test all(lower_bound(bundle.v[bus, t]) == 0.90^2 for bus in 1:33 for t in 1:48)
    @test all(upper_bound(bundle.v[bus, t]) == 1.05^2 for bus in 1:33 for t in 1:48)
    @test num_constraints(
        bundle.model,
        JuMP.QuadExpr,
        JuMP.MOI.EqualTo{Float64},
    ) == 32 * 48

    capacities = Dict(bus => 250.0 for bus in S1BMB.CANDIDATE_BUSES)
    replay = S1BMB.validate_capacities(data, capacities)
    @test replay.converged
    @test replay.ac_feasible
    @test replay.failed == 0
    @test replay.max_equation_residual <= 1e-10
    @test replay.max_scaled_residual <= 1e-10
    @test replay.phasor_recoverable
    @test replay.replay_passed
end

@testset "S1-B independent replay detailed residuals" begin
    buses, branches = CiroPVHC.build_ieee33_network()
    baseline = CiroPVHC.replay_s1b_interval(
        buses, branches, 1.0, 0.0, Dict{Int,Float64}();
        root_voltage_pu=1.0,
    )
    @test baseline.converged
    @test baseline.phasor_recoverable
    @test baseline.voltage_limits_satisfied
    @test baseline.minimum_voltage_bus == 18
    @test isapprox(baseline.minimum_voltage_pu, 0.913090479361; atol=1e-10)
    @test isapprox(baseline.substation_p_kw, 3917.677126456; atol=1e-6)
    @test baseline.active_balance_residual_pu <= 1e-10
    @test baseline.reactive_balance_residual_pu <= 1e-10
    @test baseline.voltage_drop_residual_pu2 <= 1e-10
    @test baseline.current_power_residual_pu2 <= 1e-10
    @test baseline.phasor_residual_pu <= 1e-10
    @test baseline.maximum_scaled_residual <= 1e-10

    repository_root = normpath(joinpath(@__DIR__, ".."))
    data = S1BMB.load_benchmark_data(repository_root)
    reference_capacities = Dict(
        13 => 733.6402572860231,
        20 => 4681.670271374159,
        24 => 3988.7739981702293,
        30 => 1276.4003193326757,
    )
    replay = S1BMB.validate_capacities(data, reference_capacities)
    @test replay.replay_passed
    @test replay.max_equation_residual <= 1e-10
    @test replay.max_scaled_residual <= 1e-10
    @test isapprox(replay.vmin, 0.974427788427; atol=1e-10)
    @test isapprox(replay.vmax, 1.050000004762; atol=1e-10)
    @test isapprox(replay.max_export_kw, 9469.200668489; atol=1e-6)
    @test replay.states[25].maximum_voltage_bus == 20
    @test Date(data.profile.timestamps[data.indices[25]]) == S1BMB.BENCHMARK_DATE
    @test Time(data.profile.timestamps[data.indices[25]]) == Time(12)
end

@testset "S1-B deterministic starts and lambda-zero regression" begin
    repository_root = normpath(joinpath(@__DIR__, ".."))
    data = S1BMB.load_benchmark_data(repository_root)
    directions_a = S1BMB.multistart_directions()
    directions_b = S1BMB.multistart_directions()
    directions_c = S1BMB.multistart_directions(; seed=S1BMB.MULTISTART_SEED + 1)

    @test directions_a == directions_b
    @test directions_a != directions_c
    @test length(directions_a) == 10
    @test all(isapprox(sum(direction), 1.0; atol=1e-12) for (_, direction) in directions_a)

    penalty = S1BMB.build_socp_penalty_model(data, 0.0)
    optimize!(penalty.bundle.model)
    standard = CiroPVHC.solve_s1b_central(data.profile, data.indices)
    @test string(termination_status(penalty.bundle.model)) in ("OPTIMAL", "ALMOST_OPTIMAL")
    @test standard.termination_status in ("OPTIMAL", "ALMOST_OPTIMAL")
    penalty_hc = sum(value(penalty.bundle.capacity_kw[bus]) for bus in S1BMB.CANDIDATE_BUSES)
    @test isapprox(penalty_hc, standard.total_capacity_kw; rtol=1e-5)
    @test penalty_hc > 20 * data.normalization_power_kw
end
