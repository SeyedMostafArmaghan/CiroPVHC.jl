if !isdefined(Main, :DSOVPPExportSideAxisScan)
    include(joinpath(@__DIR__, "..", "src", "benchmark",
                     "dso_vpp_export_side_axis_scan.jl"))
end

using Dates

@testset "Permanent export-side AC axis scan" begin
    module_ref = Main.DSOVPPExportSideAxisScan
    repository_root = normpath(joinpath(@__DIR__, ".."))
    smoke_parent = joinpath(repository_root, "results")
    mktempdir(smoke_parent; prefix="phaseb_test_") do output_directory
        config = module_ref.ScanConfig(
            repository_root=repository_root,
            output_directory=output_directory,
            maximum_intervals=1,
            overwrite=false,
            exact_command="permanent-test-smoke",
        )
        result = module_ref.run_scan(config)

        @test length(result.capacity_rows) == 2
        @test all(row.axis_status == "VALID_REFINED_BOUND" for row in result.capacity_rows)
        @test all(row.axis_injection_kW >= 0 for row in result.point_rows)

        rows13 = [row for row in result.point_rows if row.axis_bus == 13]
        rows30 = [row for row in result.point_rows if row.axis_bus == 30]
        @test all(row.vpp_p30_kw == 0.0 for row in rows13)
        @test all(row.vpp_p13_kw == 0.0 for row in rows30)
        @test all(row.vpp_p13_kw >= 0.0 && row.vpp_p30_kw >= 0.0
                  for row in result.point_rows)

        expected_reference = 850.0 * result.data.profile.pv_profile[first(result.data.indices)]
        @test all(row.H_kW == 850.0 for row in result.point_rows)
        @test all(isapprox(row.reference_pv_kw, expected_reference; atol=0.0, rtol=0.0)
                  for row in result.point_rows)

        for axis_rows in (rows13, rows30)
            @test first(axis_rows).search_phase == "baseline"
            @test first(axis_rows).axis_injection_kW == 0.0
            @test all(row.axis_injection_kW > 0 for row in axis_rows[2:end])
            doubling = [row.axis_injection_kW for row in axis_rows
                        if row.search_phase == "doubling"]
            @test issorted(doubling)
            @test all(doubling[i] == 2 * doubling[i - 1]
                      for i in 2:length(doubling))
        end

        for capacity in result.capacity_rows
            @test capacity.axis_capacity_kW == capacity.safe_lower_kW
            @test capacity.safe_lower_kW < capacity.violating_upper_kW
            @test capacity.binding_tolerance_pu == config.binding_tolerance_pu
            @test capacity.monotonic_Vmax_check
            @test capacity.monotonic_status_check
        end

        @test all(field in propertynames(first(result.capacity_rows))
                  for field in module_ref.CAPACITY_FIELDS)
        @test all(field in propertynames(first(result.point_rows))
                  for field in module_ref.SCAN_FIELDS)
        @test isfile(result.paths.capacity)
        @test isfile(result.paths.manifest)
        @test_throws ArgumentError module_ref.run_scan(config)

        report = read(result.paths.report, String)
        @test occursin("Cartesian product is not a certified", report)
        @test !occursin("Cartesian product is certified", report)
        @test occursin("No LinDistFlow model is implemented", report)
    end

    synthetic(status, p, vmax) = (
        power_flow_status=status == :unresolved ? "NONCONVERGED" : "CONVERGED",
        replay_status=status == :unresolved ? "PRIMARY_NOT_CONVERGED" : "PASSED",
        voltage_status=status == :safe ? "WITHIN_LIMITS" :
                       status == :upper ? "UPPER_VOLTAGE_VIOLATION" :
                       status == :lower ? "LOWER_VOLTAGE_VIOLATION" :
                       status == :both ? "BOTH_LIMITS_VIOLATED" : "NOT_EVALUATED",
        axis_injection_kw=Float64(p), maximum_voltage_pu=Float64(vmax),
    )
    @test module_ref.verify_one_transition([:safe, :safe, :upper, :upper])
    @test !module_ref.verify_one_transition([:safe, :upper, :safe, :upper])
    @test !module_ref.verify_one_transition([:safe, :unresolved, :upper])
    @test module_ref.verify_voltage_monotonicity([
        synthetic(:safe, 0, 1.0), synthetic(:safe, 1, 1.01),
        synthetic(:upper, 2, 1.06),
    ])
    @test !module_ref.verify_voltage_monotonicity([
        synthetic(:safe, 0, 1.0), synthetic(:safe, 1, 1.02),
        synthetic(:upper, 2, 1.01),
    ])

    unresolved_evaluator = function(command, phase, source, source_name)
        return command == 0 ? synthetic(:safe, command, 1.0) :
               synthetic(:unresolved, command, NaN)
    end
    unresolved = module_ref.adaptive_coarse_doubling(
        unresolved_evaluator, 1.0, 4,
    )
    @test unresolved.status == "AXIS_UNRESOLVED_BEFORE_VOLTAGE_BOUND"
    @test !occursin("INFEASIBLE", unresolved.status)

    refinement_config = module_ref.ScanConfig(
        repository_root=repository_root,
        capacity_tolerance_kw=0.1,
        voltage_margin_tolerance_pu=0.01,
    )
    visited = Float64[]
    refinement_evaluator = function(command, phase, source, source_name)
        push!(visited, command)
        return command <= 5.0 ? synthetic(:safe, command, 1.049) :
               synthetic(:upper, command, 1.051)
    end
    refined = module_ref.refine_bracket(
        refinement_evaluator, synthetic(:safe, 0, 1.0),
        synthetic(:upper, 10, 1.06), refinement_config,
    )
    @test all(0.0 < command < 10.0 for command in visited)
    @test refined.safe.axis_injection_kw < refined.violating.axis_injection_kw
    @test refined.status == "VALID_REFINED_BOUND"
    @test refined.safe.axis_injection_kw == 5.0

    binding_config = module_ref.ScanConfig(
        repository_root=repository_root, binding_tolerance_pu=1e-4,
    )
    sets = module_ref.binding_bus_sets([1.0, 1.04995, 1.04990, 1.02], binding_config)
    @test sets.near_maximum == [2, 3]
    @test sets.near_upper_limit == [2, 3]
    @test module_ref.format_bus_set([30, 13, 30]) == "13;30"

    canonical = module_ref.load_canonical_data(module_ref.ScanConfig(
        repository_root=repository_root, maximum_intervals=1,
    ))
    @test module_ref.validate_radial_topology(canonical.network)
    @test module_ref.topology_coefficient(canonical.network, 13, 13) > 0
    @test module_ref.topology_coefficient(canonical.network, 30, 30) > 0
end
