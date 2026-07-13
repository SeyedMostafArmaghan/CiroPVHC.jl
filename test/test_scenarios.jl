@testset "core scenarios" begin
    scenarios = build_core_scenarios()
    names = getfield.(scenarios, :name)

    @test names == [:S1, :S2, :S3, :S4, :S5, :R1, :R2, :R3]
    @test length(unique(names)) == length(names)

    scenario_by_name = Dict(s.name => s for s in scenarios)

    @test scenario_by_name[:S1].enable_pv
    @test !scenario_by_name[:S1].enable_unmanaged_ev
    @test scenario_by_name[:S2].enable_unmanaged_ev
    @test scenario_by_name[:S3].enable_smart_ev
    @test scenario_by_name[:S4].enable_bess
    @test scenario_by_name[:S5].enable_doe

    @test scenario_by_name[:R1].enable_robust
    @test scenario_by_name[:R1].uncertainty_level == :low
    @test scenario_by_name[:R2].uncertainty_level == :medium
    @test scenario_by_name[:R3].uncertainty_level == :high
    @test all(s -> !s.enable_robust, scenarios[1:5])
end
