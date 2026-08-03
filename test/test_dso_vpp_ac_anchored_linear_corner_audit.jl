using Test
using CiroPVHC

if !isdefined(Main, :DSOVPPACAnchoredLinearCornerAudit)
    include(joinpath(@__DIR__, "..", "src", "benchmark",
                     "dso_vpp_ac_anchored_linear_corner_audit.jl"))
end

using Dates

function _independent_audit_baseline(repository_root, timestamp, H_kw)
    module_ref = Main.DSOVPPACAnchoredLinearCornerAudit
    stage0 = module_ref.Stage0
    buses, _ = CiroPVHC.build_ieee33_network()
    source_path = joinpath(
        repository_root, "data_processed", "ausgrid",
        "ausgrid_halfhour_normalized.csv",
    )
    profile = CiroPVHC.read_s1b_profile(source_path)
    profile_index = findfirst(==(timestamp), profile.timestamps)
    profile_index === nothing && throw(ArgumentError("timestamp absent from primary data"))
    load_factor = profile.load_multiplier[profile_index]
    pv_factor = profile.pv_profile[profile_index]
    reference_pv_kw = H_kw * pv_factor
    net_demand_pu = ComplexF64[
        complex(
            bus.pd_kw * load_factor - (bus.id == 13 ? reference_pv_kw : 0.0),
            bus.qd_kvar * load_factor,
        ) / 10_000.0
        for bus in buses
    ]
    network = stage0.build_pilot_network()
    independent_inputs = (net_demand_pu=net_demand_pu,)
    solved = stage0.primary_power_flow(
        network, load_factor, 0.0, 0.0;
        pv_factor=pv_factor,
        reference_pv_capacity_kw=H_kw,
        assembled_inputs=independent_inputs,
    )
    return (
        solved=solved, profile=profile, profile_index=profile_index,
        buses=buses, network=network, load_factor=load_factor,
        pv_factor=pv_factor, reference_pv_kw=reference_pv_kw,
        net_demand_pu=net_demand_pu,
    )
end

function _manual_common_path_coefficient(network, candidate_bus, injection_bus)
    function branch_path(bus)
        path = Int[]
        current = bus
        while current != 1
            branch = network.topology.parent_branch[current]
            push!(path, branch)
            current = network.topology.branch_from[branch]
        end
        return Set(path)
    end
    common = intersect(branch_path(candidate_bus), branch_path(injection_bus))
    return 2 * sum(
        branch -> real(network.impedance_pu[branch]), common; init=0.0,
    )
end

@testset "AC-anchored all-bus linear-corner audit" begin
    module_ref = Main.DSOVPPACAnchoredLinearCornerAudit
    repository_root = normpath(joinpath(@__DIR__, ".."))
    config = module_ref.AuditConfig(repository_root=repository_root)

    baseline_calls = Ref(0)
    checked_evaluator = function(network, profile, profile_index, supplied_config)
        baseline_calls[] += 1
        return module_ref.default_baseline_evaluator(
            network, profile, profile_index, supplied_config,
        )
    end
    result = module_ref.run_analytical_audit(
        config; baseline_evaluator=checked_evaluator,
    )
    envelope = result.envelope

    @test baseline_calls[] == 1
    @test result.baseline_call_count == 1
    @test !result.radial_or_direction_probe_executed
    @test module_ref.DIAGNOSTIC_VARIANT == "AC_ANCHORED_LINDISTFLOW"
    @test result.baseline.p13_vpp_kw == 0.0
    @test result.baseline.p30_vpp_kw == 0.0
    @test result.baseline.reference_pv_capacity_kw == 850.0
    @test result.baseline.timestamp == "2012-10-15 13:00:00"
    @test result.baseline.power_flow_status == "CONVERGED"
    @test result.baseline.replay_status == "PASSED"

    independent = _independent_audit_baseline(
        repository_root, module_ref.LIMITING_TIMESTAMP, 850.0,
    )
    @test independent.solved.converged
    @test independent.profile !== result.data.profile
    @test independent.buses !== result.data.network.buses
    @test independent.reference_pv_kw == 850.0 * independent.pv_factor
    @test maximum(abs.(
        abs2.(independent.solved.voltage_complex_pu) .- result.baseline_v2
    )) <= 1e-13
    @test maximum(abs.(
        independent.net_demand_pu .- result.baseline.assembled_net_demand_pu
    )) <= 1e-15
    @test findall(
        value -> !iszero(value),
        result.baseline.assembled_vpp_injection_by_bus_kw,
    ) == Int[]

    @test length(result.all_bus_rows) == 33
    @test Set(row.bus for row in result.all_bus_rows) == Set(1:33)
    for row in result.all_bus_rows
        @test row.coefficient_13_pu_per_pu == _manual_common_path_coefficient(
            result.data.network, row.bus, 13,
        )
        @test row.coefficient_30_pu_per_pu == _manual_common_path_coefficient(
            result.data.network, row.bus, 30,
        )
    end
    @test first(envelope.ranking13.rows).bus in envelope.ranking13.tie_buses
    @test first(envelope.ranking30.rows).bus in envelope.ranking30.tie_buses
    @test envelope.ranking13.tie_buses == [13]
    @test envelope.ranking30.tie_buses == [30]
    @test envelope.axis13_classification == "LINEAR_AXIS_13_SELF_BINDS"
    @test envelope.axis30_classification == "LINEAR_AXIS_30_SELF_BINDS"
    @test length(envelope.ranking13.rows) == 33
    @test length(envelope.ranking30.rows) == 33
    @test issorted([row.linear_axis_limit_kw for row in envelope.ranking13.rows])
    @test issorted([row.linear_axis_limit_kw for row in envelope.ranking30.rows])

    tied = module_ref.axis_ranking(
        [1, 2, 3], [1.0, 1.0 + 5e-10, 2.0], [1.0, 1.0, 1.0],
        1e-14, 1e-5,
    )
    @test tied.tie_buses == [1, 2]
    @test module_ref.axis_classification(13, [13, 14]) ==
          "LINEAR_AXIS_13_AMBIGUOUS_TIE"

    @test envelope.well_conditioned
    @test envelope.positive_quadrant
    @test all(isfinite, envelope.p_kw)
    @test maximum(envelope.normalized_residual) <= 1e-13
    @test envelope.cross_axis_inequalities.bus13_beats_bus30_on_axis13
    @test envelope.cross_axis_inequalities.bus30_beats_bus13_on_axis30
    @test envelope.classification == "EXPOSED_LINEAR_CORNER_13_30"
    @test envelope.near_binding_buses == [13, 30]
    @test isempty(envelope.violated_buses)
    @test envelope.next_smallest_positive_margin_v2 > config.near_binding_tolerance_v2
    @test envelope.active_inactive_separation_v2 > 0
    @test isapprox(
        envelope.normalized_angle_rad,
        atan(
            envelope.p_kw[2] / result.capacity.scales_kw[30],
            envelope.p_kw[1] / result.capacity.scales_kw[13],
        ); atol=0.0, rtol=0.0,
    )
    @test isapprox(
        envelope.raw_kw_angle_rad, atan(envelope.p_kw[2], envelope.p_kw[1]);
        atol=0.0, rtol=0.0,
    )
    @test abs(envelope.raw_kw_angle_rad - envelope.normalized_angle_rad) > 1e-3

    capacity = module_ref.committed_capacity_data(config)
    @test capacity.sha256 == module_ref.EXPECTED_CAPACITY_SHA256
    @test capacity.scales_kw[13] == 681.370544434
    @test capacity.scales_kw[30] == 1739.59228516

    cut_off = module_ref.analyze_envelope(
        [13, 30, 99], [1.0, 1.0, 0.9],
        [1.0, 0.2, 0.6], [0.2, 1.0, 0.6],
        Dict(13 => 1.0, 30 => 1.0),
    )
    @test cut_off.positive_quadrant
    @test cut_off.violated_buses == [99]
    @test cut_off.classification == "CANDIDATE_INTERSECTION_CUT_OFF_BY_OTHER_BUS"

    ill_conditioned = module_ref.analyze_envelope(
        [13, 30], [1.0, 2.0], [1.0, 2.0], [1.0, 2.0],
        Dict(13 => 1.0, 30 => 1.0),
    )
    @test !ill_conditioned.well_conditioned
    @test ill_conditioned.classification == "ILL_CONDITIONED_INTERSECTION"

    negative_quadrant = module_ref.analyze_envelope(
        [13, 30], [2.0, 0.1], [1.0, 0.2], [0.2, 1.0],
        Dict(13 => 1.0, 30 => 1.0),
    )
    @test !negative_quadrant.positive_quadrant
    @test negative_quadrant.classification == "NO_POSITIVE_13_30_INTERSECTION"

    scratch_root = joinpath(repository_root, ".tmp-python")
    mkpath(scratch_root)
    mktempdir(scratch_root; prefix="linear_corner_test_a_") do first_directory
        mktempdir(scratch_root; prefix="linear_corner_test_b_") do second_directory
            fixed_command = "deterministic-linear-corner-test"
            first_result = module_ref.write_audit_artifacts(module_ref.AuditConfig(
                repository_root=repository_root,
                output_directory=first_directory,
                exact_command=fixed_command,
            ))
            second_result = module_ref.write_audit_artifacts(module_ref.AuditConfig(
                repository_root=repository_root,
                output_directory=second_directory,
                exact_command=fixed_command,
            ))
            @test read(first_result.paths.report) == read(second_result.paths.report)
            comparisons = module_ref.write_reproducibility_check(
                first_directory, second_directory,
                first_result.paths.reproducibility,
            )
            @test length(comparisons) == length(module_ref.SCIENTIFIC_OUTPUTS)
            @test sum(row.scientific_mismatches for row in comparisons) == 0
        end
    end

    implementation = read(joinpath(
        repository_root, "src", "benchmark",
        "dso_vpp_ac_anchored_linear_corner_audit.jl",
    ), String)
    runner = read(joinpath(
        repository_root, "scripts",
        "run_dso_vpp_ac_anchored_linear_corner_audit.jl",
    ), String)
    prohibited_calls = (
        "run_scan(", "scan_one_axis(", "evaluate_axis_point(",
        "adaptive_coarse_doubling(", "refine_bracket(",
        "replay_s1b_interval(", "jacobian_sensitivity(", "run_doe(",
        "optimize!(",
    )
    for call in prohibited_calls
        @test !occursin(call, implementation)
        @test !occursin(call, runner)
    end
end
