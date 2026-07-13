function _s1_dependencies_available()
    try
        Base.require(Base.PkgId(Base.UUID("4076af6c-e467-56ae-b986-b466b2749572"), "JuMP"))
        Base.require(Base.PkgId(Base.UUID("61c947e1-3e6d-4ee4-985a-eec8c727bd6e"), "Clarabel"))
        return true
    catch
        return false
    end
end

@testset "S1 PV-only SOCP solver" begin
    if !_s1_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        import JuMP

        data = build_case33_data()
        result = solve_s1_pv_only(data)

        @test result isa S1PVOnlyResult
        @test result.termination_status in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test isfinite(result.objective_value)
        @test result.total_pv_capacity_kw >= 0.0
        @test result.total_pv_capacity_kw <= sum(pv.pmax_kw for pv in data.pv_units) + 1e-4
        @test Set(keys(result.pv_capacity_by_unit)) == Set(pv.id for pv in data.pv_units)
        @test result.voltage_min >= data.vmin_pu - 1e-4
        @test result.voltage_max <= data.vmax_pu + 1e-4
        @test isnan(result.max_line_loading) || result.max_line_loading <= 1.0 + 1e-4
    end
end

@testset "zero MATPOWER rate does not force zero flow" begin
    if !_s1_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        import JuMP

        timeseries = TimeSeries(1, 1.0, [1.0], [0.0], [0.0], [0.0])
        data = CaseData(
            [Bus(1, 0.0, 0.0, 12.66), Bus(2, 100.0, 0.0, 12.66)],
            [Branch(1, 1, 2, 0.0, 0.0, 0.0)],
            PVUnit[],
            EVCS[],
            BESS[],
            nothing,
            timeseries,
            10.0,
            0.90,
            1.10,
        )

        model, _, network_vars = build_s1_pv_only_model(data)
        JuMP.optimize!(model)

        @test string(JuMP.termination_status(model)) in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test JuMP.value(network_vars.Pij[1, 1]) > 0.005
        @test isapprox(JuMP.value(network_vars.Pij[1, 1]), 0.01; atol=1e-5)
    end
end

@testset "no-curtailment S1 can become voltage-limited" begin
    if !_s1_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        function two_bus_pv_case(candidate_limit_kw::Float64)
            timeseries = TimeSeries(1, 1.0, [1.0], [1.0], [0.0], [0.0])
            return CaseData(
                [Bus(1, 0.0, 0.0, 12.66), Bus(2, 0.0, 0.0, 12.66)],
                [Branch(1, 1, 2, 5.0, 0.0, 0.0)],
                [PVUnit(1, 2, candidate_limit_kw, candidate_limit_kw)],
                EVCS[],
                BESS[],
                nothing,
                timeseries,
                10.0,
                0.90,
                1.10,
            )
        end

        zero_result = solve_s1_pv_only(two_bus_pv_case(0.0); curtailment_mode=:none)
        small_result = solve_s1_pv_only(two_bus_pv_case(100.0); curtailment_mode=:none)

        @test zero_result.termination_status in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test small_result.termination_status in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test isapprox(zero_result.total_pv_capacity_kw, 0.0; atol=1e-6)
        @test isapprox(small_result.total_pv_capacity_kw, 100.0; atol=1e-4)

        candidate_limit_kw = 100_000.0
        data = two_bus_pv_case(candidate_limit_kw)

        no_curtailment_result = solve_s1_pv_only(data; curtailment_mode=:none)
        free_curtailment_result = solve_s1_pv_only(data; curtailment_mode=:free)

        @test no_curtailment_result.termination_status in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test free_curtailment_result.termination_status in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test no_curtailment_result.total_pv_capacity_kw < candidate_limit_kw - 1_000.0
        @test isapprox(no_curtailment_result.voltage_max, data.vmax_pu; atol=1e-4)
        @test isapprox(free_curtailment_result.total_pv_capacity_kw, candidate_limit_kw; atol=1e-3)
    end
end

@testset "S1 paper-policy constraints" begin
    if !_s1_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        import JuMP

        alpha_cur = 0.05
        timeseries = TimeSeries(1, 1.0, [1.0], [1.0], [0.0], [0.0])
        data = CaseData(
            [Bus(1, 0.0, 0.0, 12.66), Bus(2, 1000.0, 0.0, 12.66)],
            [Branch(1, 1, 2, 0.1, 0.05, 2000.0)],
            [PVUnit(1, 2, 5000.0, 5000.0)],
            EVCS[],
            BESS[],
            nothing,
            timeseries,
            10.0,
            0.95,
            1.05,
        )

        model, pv_vars, network_vars, _ = solve_s1_pv_only_paper_model(data; alpha_cur=alpha_cur)

        @test string(JuMP.termination_status(model)) in ("OPTIMAL", "ALMOST_OPTIMAL")

        base_kw = data.base_mva * 1000.0
        p_sub_kw = JuMP.value(network_vars.Pij[1, 1]) * base_kw
        available_energy_kwh = JuMP.value(pv_vars.available_kw[1, 1]) * data.timeseries.dt_hours
        curtailed_energy_kwh = JuMP.value(pv_vars.curtailment_kw[1, 1]) * data.timeseries.dt_hours
        voltage_values = [sqrt(max(0.0, JuMP.value(network_vars.v[bus.id, 1]))) for bus in data.buses]
        line_loading = hypot(JuMP.value(network_vars.Pij[1, 1]), JuMP.value(network_vars.Qij[1, 1])) /
                       network_vars.smax_pu[1]
        ell_loading = JuMP.value(network_vars.ell[1, 1]) / network_vars.smax_pu[1]^2

        @test p_sub_kw >= -1e-4
        @test curtailed_energy_kwh <= alpha_cur * available_energy_kwh + 1e-4
        @test minimum(voltage_values) >= data.vmin_pu - 1e-5
        @test maximum(voltage_values) <= data.vmax_pu + 1e-5
        @test line_loading <= 1.0 + 1e-5
        @test ell_loading <= 1.0 + 1e-5
    end
end

@testset "S1 paper-policy loss sanity constraint" begin
    if !_s1_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        import JuMP

        alpha_cur = 0.05
        beta_loss = 0.10
        timeseries = TimeSeries(1, 1.0, [1.0], [1.0], [0.0], [0.0])
        data = CaseData(
            [Bus(1, 0.0, 0.0, 12.66), Bus(2, 1000.0, 0.0, 12.66)],
            [Branch(1, 1, 2, 0.01, 0.0, 200000.0)],
            [PVUnit(1, 2, 5000.0, 5000.0)],
            EVCS[],
            BESS[],
            nothing,
            timeseries,
            10.0,
            0.95,
            1.05,
        )

        tight_model, tight_pv, tight_network, tight_policy =
            solve_s1_pv_only_paper_model(data; alpha_cur=alpha_cur, beta_loss=beta_loss)
        loose_model, loose_pv, _, _ =
            solve_s1_pv_only_paper_model(data; alpha_cur=alpha_cur, beta_loss=1.0)

        @test string(JuMP.termination_status(tight_model)) in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test string(JuMP.termination_status(loose_model)) in ("OPTIMAL", "ALMOST_OPTIMAL")

        tight_capacity_kw = JuMP.value(tight_pv.capacity_kw[1])
        loose_capacity_kw = JuMP.value(loose_pv.capacity_kw[1])
        total_load_kw = 1000.0
        modeled_losses_kw = JuMP.value(tight_policy.loss_sanity.total_network_losses_kw[1])
        implied_losses_kw = JuMP.value(tight_network.Pij[1, 1]) * data.base_mva * 1000.0 +
                            JuMP.value(tight_pv.injection_kw[1, 1]) -
                            total_load_kw
        policy_bound_kw = beta_loss * total_load_kw
        hosting_bound_kw = (total_load_kw + policy_bound_kw) / (1.0 - alpha_cur)

        @test modeled_losses_kw <= policy_bound_kw + 1e-3
        @test isapprox(implied_losses_kw, modeled_losses_kw; atol=1e-3)
        @test tight_capacity_kw <= hosting_bound_kw + 1e-3
        @test loose_capacity_kw > tight_capacity_kw + 100.0
    end
end

@testset "S1 final physical validity gate" begin
    if !_s1_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        build_s1_pv_only_paper_case()

        base_kwargs = (
            stage1_status="OPTIMAL",
            stage2_status="OPTIMAL",
            p_sub_kw=0.0,
            curtailment_percentage=5.0,
            alpha_cur=0.05,
            implied_loss_percentage=10.0,
            beta_loss=0.10,
            voltage_min=0.95,
            voltage_max=1.05,
            vmin_pu=0.95,
            vmax_pu=1.05,
            line_loading=1.0,
            ell_loading=1.0,
            soc_gap_max_positive=0.0,
            soc_gap_most_negative=0.0,
        )

        @test CiroPVHC._s1_paper_snapshot_physical_validity_flag(; base_kwargs...)

        failing_cases = (
            (stage2_status="ALMOST_OPTIMAL",),
            (p_sub_kw=-0.01,),
            (curtailment_percentage=5.2,),
            (implied_loss_percentage=10.2,),
            (voltage_min=0.949,),
            (voltage_max=1.051,),
            (line_loading=1.01,),
            (ell_loading=1.01,),
            (soc_gap_max_positive=1e-3,),
            (soc_gap_most_negative=-1e-3,),
        )

        for overrides in failing_cases
            @test !CiroPVHC._s1_paper_snapshot_physical_validity_flag(; merge(base_kwargs, overrides)...)
        end
    end
end

@testset "S1 paper-policy lexicographic loss tightening" begin
    if !_s1_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        import JuMP

        function compact_policy_case()
            timeseries = TimeSeries(1, 1.0, [1.0], [1.0], [0.0], [0.0])
            return CaseData(
                [Bus(1, 0.0, 0.0, 12.66), Bus(2, 1000.0, 0.0, 12.66)],
                [Branch(1, 1, 2, 0.01, 0.005, 10000.0)],
                [PVUnit(1, 2, 5000.0, 5000.0)],
                EVCS[],
                BESS[],
                nothing,
                timeseries,
                10.0,
                0.95,
                1.05,
            )
        end

        function total_capacity_expr(data, pv_vars)
            return sum((pv_vars.capacity_kw[pv.id] for pv in data.pv_units); init=0.0)
        end

        function loss_expr(network_vars)
            return sum(
                network_vars.r_pu[branch_id] * network_vars.ell[branch_id, 1]
                for branch_id in network_vars.topology.branch_ids;
                init=0.0,
            )
        end

        data = compact_policy_case()
        stage1_model, stage1_pv, _, _ = solve_s1_pv_only_paper_model(data; alpha_cur=0.05)
        @test string(JuMP.termination_status(stage1_model)) in ("OPTIMAL", "ALMOST_OPTIMAL")

        stage1_hc_kw = sum(JuMP.value(stage1_pv.capacity_kw[pv.id]) for pv in data.pv_units)
        stage2_model, stage2_pv, stage2_network, _ = build_s1_pv_only_paper_model(data; alpha_cur=0.05)
        JuMP.@constraint(stage2_model, total_capacity_expr(data, stage2_pv) >= stage1_hc_kw - 1e-2)
        JuMP.@objective(stage2_model, Min, loss_expr(stage2_network))
        JuMP.optimize!(stage2_model)

        @test string(JuMP.termination_status(stage2_model)) in ("OPTIMAL", "ALMOST_OPTIMAL")

        stage2_hc_kw = sum(JuMP.value(stage2_pv.capacity_kw[pv.id]) for pv in data.pv_units)
        base_kw = data.base_mva * 1000.0
        p_sub_kw = JuMP.value(stage2_network.Pij[1, 1]) * base_kw
        injected_kw = sum(JuMP.value(stage2_pv.injection_kw[pv.id, 1]) for pv in data.pv_units)
        load_kw = sum(bus.pd_kw for bus in data.buses)
        implied_losses_kw = p_sub_kw + injected_kw - load_kw
        modeled_losses_kw = JuMP.value(loss_expr(stage2_network)) * base_kw
        loss_percentage = implied_losses_kw / load_kw * 100.0

        @test stage2_hc_kw >= stage1_hc_kw - 2e-2
        @test isapprox(implied_losses_kw, modeled_losses_kw; atol=1e-3)
        @test 0.0 <= loss_percentage <= 1.0
        @test JuMP.value(stage2_network.ell[1, 1]) <= stage2_network.smax_pu[1]^2 + 1e-6
    end
end
