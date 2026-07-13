@testset "default profiles" begin
    ts = build_default_timeseries()

    @test ts.T == 24
    @test ts.dt_hours == 1.0
    @test length(ts.load_multiplier) == ts.T
    @test length(ts.pv_profile) == ts.T
    @test length(ts.ev_availability) == ts.T
    @test length(ts.unmanaged_ev_profile) == ts.T
    @test all(x -> x >= 0.0, ts.load_multiplier)
    @test all(x -> 0.0 <= x <= 1.0, ts.pv_profile)
    @test all(x -> 0.0 <= x <= 1.0, ts.ev_availability)
    @test all(x -> x >= 0.0, ts.unmanaged_ev_profile)
    @test maximum(ts.pv_profile) > 0.95
end

@testset "custom profile horizon and DOE lengths" begin
    ts = build_default_timeseries(48)
    doe = build_default_doe(ts.T)

    @test ts.T == 48
    @test ts.dt_hours == 0.5
    @test length(doe.p_import_max_kw) == ts.T
    @test length(doe.p_export_max_kw) == ts.T
    @test all(x -> x >= 0.0, doe.p_import_max_kw)
    @test all(x -> x >= 0.0, doe.p_export_max_kw)
    @test_throws ArgumentError build_default_timeseries(0)
    @test_throws ArgumentError build_default_doe(0)
end
