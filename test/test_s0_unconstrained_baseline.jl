function _prior_s0_peak_snapshot(path, root_voltage_pu)
    lines = eachline(path)
    header = split(first(lines), ',')
    columns = Dict(name => index for (index, name) in enumerate(header))
    for line in lines
        fields = split(line, ',')
        fields[columns["timestamp"]] == "2011-02-05 18:00:00" || continue
        parse(Float64, fields[columns["root_voltage_pu"]]) == root_voltage_pu || continue
        return (
            minimum_voltage_pu=parse(Float64, fields[columns["minimum_voltage_pu"]]),
            substation_active_power_kw=parse(Float64, fields[columns["substation_active_power_kw"]]),
            substation_reactive_power_kvar=parse(Float64, fields[columns["substation_reactive_power_kvar"]]),
            active_losses_kw=parse(Float64, fields[columns["active_losses_kw"]]),
            reactive_losses_kvar=parse(Float64, fields[columns["reactive_losses_kvar"]]),
        )
    end
    error("prior peak snapshot is missing for V0=$root_voltage_pu")
end

@testset "S0 unconstrained AC peak snapshot" begin
    previous_path = normpath(joinpath(
        @__DIR__,
        "..",
        "results",
        "s0_full_period_baseline",
        "s0_interval_metrics.csv",
    ))
    buses, branches = build_ieee33_network()
    config = S0BaselineConfig()

    @test config.pv_capacity_kw == 0.0
    @test config.ev_load_kw == 0.0
    @test config.bess_charge_kw == 0.0
    @test config.bess_discharge_kw == 0.0
    @test all(branch -> branch.smax_kva == 0.0, branches)

    for root_voltage_pu in (1.00, 1.03, 1.05)
        result = solve_s0_unconstrained_snapshot(1.0, root_voltage_pu)
        previous = _prior_s0_peak_snapshot(previous_path, root_voltage_pu)

        @test result.converged
        @test result.iterations < 2000
        @test result.pv_capacity_kw == 0.0
        @test result.ev_load_kw == 0.0
        @test result.bess_charge_kw == 0.0
        @test result.bess_discharge_kw == 0.0
        @test !result.voltage_limits_applied
        @test !result.thermal_limits_applied
        @test abs(result.active_balance_residual_kw) <= 1e-6
        @test abs(result.reactive_balance_residual_kvar) <= 1e-6
        @test result.maximum_voltage_equation_residual_pu <= 5e-11
        @test result.maximum_kcl_residual_pu <= 5e-13
        @test isapprox(minimum(result.voltage_magnitudes_pu), previous.minimum_voltage_pu; atol=2e-5)
        @test isapprox(result.substation_active_power_kw, previous.substation_active_power_kw; atol=2e-2)
        @test isapprox(result.substation_reactive_power_kvar, previous.substation_reactive_power_kvar; atol=2e-2)
        @test isapprox(result.active_losses_kw, previous.active_losses_kw; atol=2e-2)
        @test isapprox(result.reactive_losses_kvar, previous.reactive_losses_kvar; atol=2e-2)
    end
end
