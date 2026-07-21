using Dates

function _s0_test_dependencies_available()
    try
        Base.require(Base.PkgId(Base.UUID("4076af6c-e467-56ae-b986-b466b2749572"), "JuMP"))
        Base.require(Base.PkgId(Base.UUID("61c947e1-3e6d-4ee4-985a-eec8c727bd6e"), "Clarabel"))
        return true
    catch
        return false
    end
end

@testset "S0 Ausgrid full-period input" begin
    input_path = normpath(joinpath(@__DIR__, "..", "data_processed", "ausgrid", "ausgrid_halfhour_normalized.csv"))
    profile = read_ausgrid_s0_load_profile(input_path)

    @test length(profile.timestamps) == 52_608
    @test length(profile.load_multipliers) == 52_608
    @test profile.dt_hours == 0.5
    @test issorted(profile.timestamps)
    @test length(unique(profile.timestamps)) == 52_608
    @test all(diff(profile.timestamps) .== Minute(30))
    @test all(isfinite, profile.load_multipliers)
    @test all(>=(0.0), profile.load_multipliers)
end

@testset "S0 configuration and calculations" begin
    config = S0BaselineConfig()
    bus = Bus(2, 100.0, 60.0, 12.66)
    scaled = s0_scaled_bus_load(bus, 0.4)

    @test scaled.active_power_kw == 40.0
    @test scaled.reactive_power_kvar == 24.0
    @test config.pv_capacity_kw == 0.0
    @test config.ev_load_kw == 0.0
    @test config.bess_charge_kw == 0.0
    @test config.bess_discharge_kw == 0.0
    @test !config.no_export_constraint_active
    @test !config.loss_cap_constraint_active
    @test s0_root_voltage_squared(1.00) == 1.00^2
    @test s0_root_voltage_squared(1.03) == 1.03^2
    @test s0_root_voltage_squared(1.05) == 1.05^2
    @test s0_apparent_power(3.0, 4.0) == 5.0

    violations = s0_voltage_violation_counts([0.94, 0.95, 1.00, 1.05, 1.06], 0.95, 1.05)
    @test violations.undervoltage == 1
    @test violations.overvoltage == 1
    @test violations.total == 2

    timestamps = DateTime(2020, 1, 1):Minute(30):DateTime(2020, 1, 1, 1)
    peak = s0_branch_peak([1.0, 3.0, 3.0], collect(timestamps))
    @test peak.index == 2
    @test peak.value == 3.0
    @test peak.timestamp == DateTime(2020, 1, 1, 0, 30)

    @test s0_assert_full_interval_coverage(3, 3, 1)
    @test_throws ArgumentError s0_assert_full_interval_coverage(3, 2, 0)
    @test "substation_apparent_power_kva" in S0_INTERVAL_METRIC_COLUMNS
    @test "maximum_soc_gap_pu2" in S0_SUMMARY_COLUMNS
    @test "peak_current_a" in S0_BRANCH_PEAK_COLUMNS
    @test "failure_reason" in S0_SOLVER_FAILURE_COLUMNS
end

@testset "S0 input rejects duplicate and nonmonotonic timestamps" begin
    mktempdir() do directory
        duplicate_path = joinpath(directory, "duplicate.csv")
        write(
            duplicate_path,
            "datetime,load_multiplier\n" *
            "2011-07-01 00:00:00,0.5\n" *
            "2011-07-01 00:00:00,0.6\n",
        )
        @test_throws ArgumentError read_ausgrid_s0_load_profile(
            duplicate_path;
            expected_intervals=2,
            expected_dt_hours=0.5,
        )

        reversed_path = joinpath(directory, "reversed.csv")
        write(
            reversed_path,
            "datetime,load_multiplier\n" *
            "2011-07-01 00:30:00,0.5\n" *
            "2011-07-01 00:00:00,0.6\n",
        )
        @test_throws ArgumentError read_ausgrid_s0_load_profile(
            reversed_path;
            expected_intervals=2,
            expected_dt_hours=0.5,
        )
    end
end

@testset "S0 reusable SOCP model" begin
    if !_s0_test_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        config = S0BaselineConfig()
        operational = build_s0_baseline_model(1.03; config=config)
        diagnostic = build_s0_baseline_model(
            1.03;
            config=config,
            enforce_operational_voltage_limits=false,
        )
        result = solve_s0_load_state(operational, diagnostic, 0.5; config=config)
        failed = CiroPVHC._s0_failed_state(0.5, "FAILED", "FAILED", "test_failure")

        @test !operational.no_export_constraint_active
        @test !operational.loss_cap_constraint_active
        @test isempty(operational.data.pv_units)
        @test isempty(operational.data.evcs_units)
        @test isempty(operational.data.bess_units)
        @test operational.data.doe === nothing
        @test result.operational_solver_status in ("OPTIMAL", "ALMOST_OPTIMAL")
        @test result.primal_available
        @test result.numerical_validation_passed
        @test !failed.primal_available
        @test failed.failure_reason == "test_failure"
        @test isnan(failed.substation_reactive_balance_residual_kvar)
        @test isapprox(result.voltages_pu[1]^2, 1.03^2; atol=config.root_voltage_tolerance_pu2)
        @test isapprox(
            result.substation_apparent_power_kva,
            hypot(result.substation_active_power_kw, result.substation_reactive_power_kvar);
            atol=1e-10,
        )
    end
end
