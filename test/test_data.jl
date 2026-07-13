@testset "case data consistency" begin
    data = build_case33_data()

    @test length(data.buses) == 33
    @test length(data.branches) == 32
    @test length(data.pv_units) == 5
    @test length(data.evcs_units) == 4
    @test length(data.bess_units) == 2
    @test data.doe !== nothing
    @test check_data_consistency(data)
end

@testset "case data validation catches invalid inputs" begin
    data = build_case33_data()

    duplicate_buses = copy(data.buses)
    duplicate_buses[2] = Bus(1, 100.0, 60.0, 12.66)
    @test_throws ArgumentError check_data_consistency(CaseData(
        duplicate_buses,
        data.branches,
        data.pv_units,
        data.evcs_units,
        data.bess_units,
        data.doe,
        data.timeseries,
        data.base_mva,
        data.vmin_pu,
        data.vmax_pu,
    ))

    bad_endpoint = copy(data.branches)
    bad_endpoint[1] = Branch(1, 1, 999, 0.0922, 0.0470, 4000.0)
    @test_throws ArgumentError check_data_consistency(CaseData(
        data.buses,
        bad_endpoint,
        data.pv_units,
        data.evcs_units,
        data.bess_units,
        data.doe,
        data.timeseries,
        data.base_mva,
        data.vmin_pu,
        data.vmax_pu,
    ))

    bad_pv = copy(data.pv_units)
    bad_pv[1] = PVUnit(1, 6, -1.0, 390.0)
    @test_throws ArgumentError check_data_consistency(CaseData(
        data.buses,
        data.branches,
        bad_pv,
        data.evcs_units,
        data.bess_units,
        data.doe,
        data.timeseries,
        data.base_mva,
        data.vmin_pu,
        data.vmax_pu,
    ))

    bad_bess = copy(data.bess_units)
    bad_bess[1] = BESS(1, 14, 250.0, 250.0, 100.0, 1000.0, 1200.0, 0.95, 0.95, 300.0)
    @test_throws ArgumentError check_data_consistency(CaseData(
        data.buses,
        data.branches,
        data.pv_units,
        data.evcs_units,
        bad_bess,
        data.doe,
        data.timeseries,
        data.base_mva,
        data.vmin_pu,
        data.vmax_pu,
    ))

    bad_doe = DOE(1, fill(1000.0, data.timeseries.T - 1), fill(500.0, data.timeseries.T))
    @test_throws ArgumentError check_data_consistency(CaseData(
        data.buses,
        data.branches,
        data.pv_units,
        data.evcs_units,
        data.bess_units,
        bad_doe,
        data.timeseries,
        data.base_mva,
        data.vmin_pu,
        data.vmax_pu,
    ))
end
