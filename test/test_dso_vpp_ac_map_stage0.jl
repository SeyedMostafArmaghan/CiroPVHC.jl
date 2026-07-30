if !isdefined(Main, :DSOVPPACMapStage0)
    include(joinpath(@__DIR__, "..", "src", "benchmark", "dso_vpp_ac_map_stage0.jl"))
end

@testset "DSO-VPP Stage-0 pilot selection and exact AC classification" begin
    module_ref = Main.DSOVPPACMapStage0
    repository_root = normpath(joinpath(@__DIR__, ".."))
    profile = module_ref.load_profile(repository_root)
    indices = module_ref.select_pilot_indices(profile)
    network = module_ref.build_pilot_network()

    @test length(indices) == 96
    @test length(unique(profile.timestamps[indices])) == 96
    @test all(diff(profile.timestamps[indices]) .== Dates.Minute(30))
    @test all(isfinite, profile.load_multiplier[indices])
    @test all(isfinite, profile.pv_profile[indices])

    index = indices[argmax(profile.load_multiplier[indices])]
    zero = module_ref.evaluate_point(network, profile, index, 0.0, 0.0)
    injection = module_ref.evaluate_point(network, profile, index, 100.0, 0.0)
    consumption = module_ref.evaluate_point(network, profile, index, -100.0, 0.0)
    @test zero.classification == "FEASIBLE"
    @test zero.solver_status == "CONVERGED"
    @test zero.replay_status == "PASSED"
    @test injection.substation_p_kw < zero.substation_p_kw
    @test consumption.substation_p_kw > zero.substation_p_kw
    @test zero.primary_replay_max_voltage_difference_pu <=
          module_ref.REPLAY_VOLTAGE_MATCH_TOLERANCE_PU

    voltage_cases = [
        module_ref.evaluate_point(network, profile, first(indices), p, p)
        for p in (8_000.0, 12_000.0, -8_000.0)
    ]
    @test any(row -> row.classification == "INFEASIBLE_VOLTAGE", voltage_cases)

    unknown = module_ref.evaluate_point(
        network,
        profile,
        index,
        0.0,
        0.0;
        primary_maximum_iterations=1,
    )
    @test unknown.classification == "UNRESOLVED_AC_NONCONVERGENCE"
    @test unknown.solver_status == "NONCONVERGED"
    @test unknown.power_flow_status == "NONCONVERGED"
    @test unknown.voltage_status == "NOT_EVALUATED"

    plan_a = module_ref.sample_plan(indices; count=1000)
    plan_b = module_ref.sample_plan(indices; count=1000)
    @test plan_a == plan_b
    @test all(point -> point.p13_vpp_kw == 0.0 && point.p30_vpp_kw == 0.0, plan_a[1:96])

    source = read(joinpath(
        repository_root,
        "src",
        "benchmark",
        "dso_vpp_ac_map_stage0.jl",
    ), String)
    rejected_authority_name = join(("so", "cp"))
    @test !occursin(rejected_authority_name, lowercase(source))
end
