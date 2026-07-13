function _s2_dependencies_available()
    try
        Base.require(Base.PkgId(Base.UUID("4076af6c-e467-56ae-b986-b466b2749572"), "JuMP"))
        Base.require(Base.PkgId(Base.UUID("61c947e1-3e6d-4ee4-985a-eec8c727bd6e"), "Clarabel"))
        return true
    catch
        return false
    end
end

function _case_with_evcs(data::CaseData, evcs_units::Vector{EVCS})
    return CaseData(
        data.buses,
        data.branches,
        data.pv_units,
        evcs_units,
        data.bess_units,
        data.doe,
        data.timeseries,
        data.base_mva,
        data.vmin_pu,
        data.vmax_pu,
    )
end

@testset "S2 unmanaged EV data and fixed-load model" begin
    if !_s2_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        import JuMP

        config = S2UnmanagedEVConfig()
        data = build_s2_unmanaged_ev_paper_case(config)

        @test data.timeseries.T == 1
        @test config.selected_time_index == argmax(build_case33_data().timeseries.pv_profile)
        @test check_data_consistency(data)

        ev_load = unmanaged_ev_load_by_bus(data; ev_penetration_scale=config.ev_penetration_scale)
        ev_buses = Set(evcs.bus for evcs in data.evcs_units)
        positive_ev_buses = Set(bus for (bus, series) in ev_load.p_by_bus_kw if series[1] > 1e-8)

        @test positive_ev_buses == ev_buses
        @test all(ev_load.p_by_bus_kw[bus][1] == 0.0 for bus in setdiff(Set(bus.id for bus in data.buses), ev_buses))

        for evcs in data.evcs_units
            p_ev_kw = unmanaged_ev_active_power_kw(evcs, data.timeseries, 1)
            expected_q_kvar = p_ev_kw * tan(acos(evcs.charging_power_factor))
            @test isapprox(ev_load.p_by_bus_kw[evcs.bus][1], p_ev_kw; atol=1e-8)
            @test isapprox(ev_load.q_by_bus_kvar[evcs.bus][1], expected_q_kvar; atol=1e-8)
        end

        model, _, _, _, _ = build_s2_unmanaged_ev_model(data; config=config)
        variable_names = lowercase.(JuMP.name.(JuMP.all_variables(model)))
        @test all(name -> !occursin("ev", name), variable_names)

        zero_config = S2UnmanagedEVConfig(ev_penetration_scale=0.0)
        zero_data = build_s2_unmanaged_ev_paper_case(zero_config)
        s2_model, s2_pv, _, _, _ = build_s2_unmanaged_ev_model(zero_data; config=zero_config)
        s1_model, s1_pv, _, _ = solve_s1_pv_only_paper_model(
            zero_data;
            alpha_cur=zero_config.alpha_cur,
            beta_loss=zero_config.beta_loss,
        )
        JuMP.optimize!(s2_model)

        @test string(JuMP.termination_status(s1_model)) in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test string(JuMP.termination_status(s2_model)) in ("OPTIMAL", "ALMOST_OPTIMAL")

        s1_hc_kw = sum(JuMP.value(s1_pv.capacity_kw[pv.id]) for pv in zero_data.pv_units; init=0.0)
        s2_hc_kw = sum(JuMP.value(s2_pv.capacity_kw[pv.id]) for pv in zero_data.pv_units; init=0.0)
        @test isapprox(s2_hc_kw, s1_hc_kw; atol=1e-3)

        positive_ev_kw = sum(series[1] for series in values(ev_load.p_by_bus_kw); init=0.0)
        base_load_kw = sum(bus.pd_kw * data.timeseries.load_multiplier[1] for bus in data.buses; init=0.0)
        @test positive_ev_kw > 0.0
        @test base_load_kw + positive_ev_kw > base_load_kw
    end
end

@testset "S2 unmanaged EV solver result checks" begin
    if !_s2_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        baseline = S1ComparisonBaseline(2000.0, 10.0, 0.97, 0.20)
        config = S2UnmanagedEVConfig()
        result = solve_s2_unmanaged_ev(
            config;
            comparison_baseline=baseline,
            compute_comparison_baseline=false,
        )

        @test result isa S2UnmanagedEVResult
        @test result.stage1_termination_status in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test result.stage2_termination_status in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test result.base_load_kw > 0.0
        @test result.unmanaged_ev_load_kw > 0.0
        @test isapprox(result.total_load_kw, result.base_load_kw + result.unmanaged_ev_load_kw; atol=1e-6)
        @test result.voltage_min >= config.vmin_pu - 1e-4
        @test result.voltage_max <= config.vmax_pu + 1e-4
        @test result.substation_active_power_kw >= -config.no_export_tol_kw
        @test result.total_pv_curtailed_kw <= config.alpha_cur * result.total_pv_available_kw + 1e-3
        @test isapprox(
            result.pv_curtailment_percentage,
            100.0 * result.total_pv_curtailed_kw / result.total_pv_available_kw;
            atol=1e-6,
        )
        @test result.loss_percentage <= 100.0 * config.beta_loss + 1e-3
        @test result.physical_validity_flag

        @test isapprox(result.delta_HC_kw, result.stage2_accepted_hc_kw - baseline.hc_kw; atol=1e-6)
        @test isapprox(result.delta_HC_percent, 100.0 * result.delta_HC_kw / baseline.hc_kw; atol=1e-6)
        @test isapprox(result.delta_losses_kw, result.network_losses_kw - baseline.network_losses_kw; atol=1e-6)
        @test isapprox(result.delta_voltage_min, result.voltage_min - baseline.voltage_min; atol=1e-6)
        @test isapprox(
            result.delta_max_line_loading,
            result.max_line_loading - baseline.max_line_loading;
            atol=1e-6,
        )
    end
end

@testset "S2 EV input validation" begin
    config = S2UnmanagedEVConfig()
    data = build_s2_unmanaged_ev_paper_case(config)

    bad_bus = copy(data.evcs_units)
    bad_bus[1] = EVCS(
        id=bad_bus[1].id,
        bus=999,
        pmax_kw=bad_bus[1].pmax_kw,
        eta=bad_bus[1].eta,
        required_energy_kwh=bad_bus[1].required_energy_kwh,
        charger_count=bad_bus[1].charger_count,
        charging_power_factor=bad_bus[1].charging_power_factor,
        reactive_power_convention=bad_bus[1].reactive_power_convention,
        unmanaged_profile_scale=bad_bus[1].unmanaged_profile_scale,
        ev_penetration_scale=bad_bus[1].ev_penetration_scale,
    )
    @test_throws ArgumentError check_data_consistency(_case_with_evcs(data, bad_bus))

    bad_power = copy(data.evcs_units)
    bad_power[1] = EVCS(
        id=bad_power[1].id,
        bus=bad_power[1].bus,
        pmax_kw=-1.0,
        eta=bad_power[1].eta,
        required_energy_kwh=bad_power[1].required_energy_kwh,
        charger_count=bad_power[1].charger_count,
        charging_power_factor=bad_power[1].charging_power_factor,
        reactive_power_convention=bad_power[1].reactive_power_convention,
        unmanaged_profile_scale=bad_power[1].unmanaged_profile_scale,
        ev_penetration_scale=bad_power[1].ev_penetration_scale,
    )
    @test_throws ArgumentError check_data_consistency(_case_with_evcs(data, bad_power))

    bad_pf = copy(data.evcs_units)
    bad_pf[1] = EVCS(
        id=bad_pf[1].id,
        bus=bad_pf[1].bus,
        pmax_kw=bad_pf[1].pmax_kw,
        eta=bad_pf[1].eta,
        required_energy_kwh=bad_pf[1].required_energy_kwh,
        charger_count=bad_pf[1].charger_count,
        charging_power_factor=1.01,
        reactive_power_convention=bad_pf[1].reactive_power_convention,
        unmanaged_profile_scale=bad_pf[1].unmanaged_profile_scale,
        ev_penetration_scale=bad_pf[1].ev_penetration_scale,
    )
    @test_throws ArgumentError check_data_consistency(_case_with_evcs(data, bad_pf))
end

@testset "S2 unmanaged EV sensitivity" begin
    if !_s2_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        scales = [0.0, 0.5, 1.0]
        locked_baseline = S1ComparisonBaseline(
            S1_LOCKED_STAGE2_ACCEPTED_HC_KW,
            NaN,
            NaN,
            NaN,
        )
        results = solve_s2_unmanaged_ev_sensitivity(
            scales;
            comparison_baseline=locked_baseline,
            compute_comparison_baseline=false,
        )

        @test length(results) == length(scales)
        @test [result.ev_penetration_scale for result in results] == scales
        @test all(result -> result isa S2UnmanagedEVResult, results)

        zero_result, half_result, unit_result = results
        @test zero_result.physical_validity_flag
        @test isapprox(
            zero_result.stage2_accepted_hc_kw,
            S1_LOCKED_STAGE2_ACCEPTED_HC_KW;
            atol=0.25,
        )
        @test isapprox(zero_result.unmanaged_ev_load_kw, 0.0; atol=1e-8)
        @test isapprox(zero_result.total_ev_reactive_power_kvar, 0.0; atol=1e-8)
        @test isapprox(
            half_result.unmanaged_ev_load_kw,
            0.5 * unit_result.unmanaged_ev_load_kw;
            atol=1e-8,
        )
        @test isapprox(
            half_result.total_ev_reactive_power_kvar,
            0.5 * unit_result.total_ev_reactive_power_kvar;
            atol=1e-8,
        )

        for result in results
            @test result.s1_baseline_hc_kw == S1_LOCKED_STAGE2_ACCEPTED_HC_KW
            @test isapprox(
                result.delta_HC_kw,
                result.stage2_accepted_hc_kw - S1_LOCKED_STAGE2_ACCEPTED_HC_KW;
                atol=1e-6,
            )
            @test isapprox(
                result.delta_HC_percent,
                100.0 * result.delta_HC_kw / S1_LOCKED_STAGE2_ACCEPTED_HC_KW;
                atol=1e-6,
            )
        end

        csv_path = joinpath(mktempdir(), "nested", "s2_unmanaged_ev_sensitivity.csv")
        written_path = write_s2_unmanaged_ev_sensitivity_csv(csv_path, results)
        @test isfile(written_path)
        csv_contents = read(written_path, String)
        for required_column in (
            "EV scale",
            "EV load kW",
            "Total load kW",
            "Accepted HC kW",
            "Delta HC vs S1 kW",
            "Delta HC vs S1 %",
            "Losses kW",
            "Loss %",
            "Vmin p.u.",
            "Vmax p.u.",
            "Max line loading %",
            "Max current loading %",
            "Curtailment %",
            "Physical validity",
            "Classification",
        )
            @test occursin(required_column, csv_contents)
        end

        @test_throws ArgumentError S2UnmanagedEVConfig(ev_penetration_scale=-0.1)
        @test_throws ArgumentError solve_s2_unmanaged_ev_sensitivity([-0.1])

        infeasible_config = S2UnmanagedEVConfig(synthetic_smax_kva=1.0)
        infeasible_result = only(
            solve_s2_unmanaged_ev_sensitivity(
                [0.0];
                config=infeasible_config,
                comparison_baseline=locked_baseline,
                compute_comparison_baseline=false,
            ),
        )
        @test !infeasible_result.physical_validity_flag
        @test isnan(infeasible_result.stage2_accepted_hc_kw)
        @test infeasible_result.stage2_termination_status in ("NOT_RUN", "NO_PHYSICAL_SOLUTION")
        @test infeasible_result.result_classification in (
            "infeasible",
            "no physical solution",
            "solver-error",
        )
    end
end
