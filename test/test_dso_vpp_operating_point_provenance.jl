using Test
using Dates

@testset "DSO-VPP operating-point provenance" begin
    module_path = joinpath(@__DIR__, "..", "src", "benchmark",
                           "dso_vpp_operating_point_provenance.jl")
    module_ref = Module(:DSOVPPOperatingPointProvenanceTestHarness)
    Base.include(module_ref, module_path)
    P = getfield(module_ref, :DSOVPPOperatingPointProvenance)
    root = normpath(joinpath(@__DIR__, ".."))

    profile = P.read_primary_profile(joinpath(root, "data_processed", "ausgrid",
                                               "ausgrid_halfhour_normalized.csv"))
    @test [row.timestamp for row in profile.rows] == collect(P.TARGET_TIMESTAMPS)
    @test [row.slot for row in profile.rows] == [25, 26, 27]
    @test [row.source_data_row for row in profile.rows] == [40202, 40203, 40204]
    @test [row.source_file_line for row in profile.rows] == [40203, 40204, 40205]
    @test profile.rows[1].reconstructed_pv_factor == 0.9282211452522351
    @test profile.rows[2].reconstructed_pv_factor == 0.9149568739021162
    @test profile.rows[3].reconstructed_pv_factor == 0.8875029793258973
    @test all(row.reconstructed_pv_factor == row.stored_pv_factor for row in profile.rows)
    @test all(row.reconstructed_load_multiplier == row.stored_load_multiplier for row in profile.rows)
    @test all(Dates.format(row.timestamp, dateformat"yyyy-mm-dd HH:MM:SS") ==
              row.canonical_timestamp for row in profile.rows)
    @test occursin("timezone-naive", P.TIMEZONE_STATEMENT)
    @test !occursin("UTC+", P.TIMEZONE_STATEMENT)

    case_data = P.parse_case33bw(joinpath(root, "data_raw", "case33bw.m"))
    @test case_data.base_mva == 10.0
    @test only(unique(bus.base_kv for bus in case_data.buses)) == 12.66
    target = profile.rows[2]
    independent = P.independent_vectors(case_data, target)
    @test independent.p_multiplier == target.reconstructed_load_multiplier
    @test independent.q_multiplier == target.reconstructed_load_multiplier
    @test independent.reference_pv_kw == 850.0 * target.reconstructed_pv_factor
    @test sum(case_data.buses[i].pd_kw for i in 14:18) == 390.0
    @test sum(case_data.buses[i].qd_kvar for i in 14:18) == 170.0

    result = P.run_provenance_audit(root)
    @test P.CLASSIFICATION == "ADJACENT_TIMESTAMP_HISTORICAL_TEXT_ERROR"
    @test result.phase_b.timestamp == "2012-10-15 13:00:00"
    @test result.analytical_audit.baseline.timestamp == result.phase_b.timestamp
    @test result.phase_b.pv_factor == target.reconstructed_pv_factor
    @test result.analytical_audit.baseline.pv_factor == target.reconstructed_pv_factor
    @test P.classify_scaling(case_data, target, P.production_vectors(result.phase_b)) ==
          "P_AND_Q_SCALED_IDENTICALLY"
    production = P.production_vectors(result.phase_b)
    @test maximum(abs.(production.p_load .- independent.p_load)) <= 1e-12
    @test maximum(abs.(production.q_load .- independent.q_load)) <= 1e-12
    @test maximum(abs.(production.p_injection .- independent.p_injection)) <= 1e-12
    @test maximum(abs.(production.q_injection .- independent.q_injection)) <= 1e-12
    @test all(row.classification in ("EXACT_MATCH", "NOT_APPLICABLE")
              for row in result.comparisons)

    @test result.nearest_inactive.bus == 14
    @test result.nearest_inactive.margin_v2 > 0
    @test result.active_inactive_separation > 0
    summary = Dict(row.key => row.value for row in result.summary)
    @test haskey(summary, "nearest_inactive_margin_v2")
    @test haskey(summary, "active_inactive_separation_v2")
    @test summary["nearest_inactive_margin_v2"] != ""
    @test summary["active_inactive_separation_definition"] ==
          "nearest inactive positive margin minus maximum absolute active-set residual"
    @test parse(Float64, summary["raw_delta_v13"]) == result.analytical_audit.envelope.rhs[1]
    @test parse(Float64, summary["raw_delta_v30"]) == result.analytical_audit.envelope.rhs[2]
    @test isapprox(parse(Float64, summary["baseline_squared_voltage_separation_v13_minus_v14"]),
                   result.nearest_inactive.margin_v2; atol=1e-14, rtol=0)

    expected_coefficients = Dict("c13_30" => 0.268450094711859,
                                 "c13_13" => 0.893822890071851,
                                 "c30_30" => 0.625073311221421)
    for row in result.coefficients
        @test isapprox(row.reconstructed_coefficient, expected_coefficients[row.coefficient];
                       atol=5e-16, rtol=0)
        @test isapprox(row.reconstructed_coefficient, row.production_coefficient;
                       atol=5e-16, rtol=0)
        @test row.absolute_difference <= 5e-16
        @test !isempty(row.exact_shared_path)
        @test !isempty(row.case33bw_source_lines)
    end

    # Negative controls: exact timestamp keys detect shift and reversal.
    canonical = Dict(row.canonical_timestamp => row.reconstructed_pv_factor
                     for row in profile.rows)
    shifted_values = circshift([row.reconstructed_pv_factor for row in profile.rows], 1)
    reversed_values = reverse([row.reconstructed_pv_factor for row in profile.rows])
    @test any(canonical[profile.rows[i].canonical_timestamp] != shifted_values[i]
              for i in eachindex(profile.rows))
    @test any(canonical[profile.rows[i].canonical_timestamp] != reversed_values[i]
              for i in eachindex(profile.rows))
    p_only = P.independent_vectors(case_data, target; q_scale=1.0)
    @test P.classify_scaling(case_data, target, p_only) == "ONLY_P_SCALED"
    @test P.vector_sha256(p_only.q_load) != result.hashes.q_load

    @test result.radial_or_direction_probe_executed == false
    @test result.analytical_audit.radial_or_direction_probe_executed == false
    @test result.analytical_audit.baseline_call_count == 1
    @test all(row.classification != "SCIENTIFIC_ABSOLUTE_PATH_DEFECT"
              for row in result.path_audit)
    exact_occurrences = [row for row in result.occurrences if row.match_type == "EXACT_STRING"]
    @test length(exact_occurrences) == 6
    @test sum(length(split(row.lines, ';')) for row in exact_occurrences) == 9
    @test all(row.matched_value == "0.9282211452522351" for row in exact_occurrences)
    @test any(row.match_type == "CLOSE_UNRELATED_VOLTAGE" for row in result.occurrences)

    primary = mktempdir()
    duplicate = mktempdir()
    first_run = P.write_artifacts(primary; repository_root=root)
    second_run = P.write_artifacts(duplicate; repository_root=root)
    check_path = joinpath(primary, "repro.csv")
    comparisons = P.compare_artifacts(primary, duplicate, check_path)
    @test all(row.scientific_mismatches == 0 for row in comparisons)
    @test all(row.byte_identical for row in comparisons)
    @test all(!occursin(uppercase(replace(root, '/' => '\\')), uppercase(read(path, String)))
              for path in values(first_run.paths) if isfile(path) && path != first_run.paths.reproducibility)
    @test second_run.lambda_lin == first_run.lambda_lin
end
