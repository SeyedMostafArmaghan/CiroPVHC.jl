if !isdefined(Main, :DSOVPPACMapStage0)
    include(joinpath(@__DIR__, "..", "src", "benchmark", "dso_vpp_ac_map_stage0.jl"))
end

using Dates

function _timestamp_pv_vectors_match(expected, actual; atol=1e-12, rtol=1e-12)
    length(expected) == length(actual) || return false
    [row.timestamp for row in expected] == [row.timestamp for row in actual] ||
        return false
    return all(
        isapprox(expected_row.pv_kw, actual_row.pv_kw; atol=atol, rtol=rtol)
        for (expected_row, actual_row) in zip(expected, actual)
    )
end

@testset "Stage-0 timestamp-keyed 96-interval PV propagation" begin
    module_ref = Main.DSOVPPACMapStage0
    repository_root = normpath(joinpath(@__DIR__, ".."))
    production_profile = module_ref.load_profile(repository_root)
    production_indices = module_ref.select_pilot_indices(production_profile)
    production_network = module_ref.build_pilot_network()

    independent_profile = CiroPVHC.read_s1b_profile(joinpath(
        repository_root,
        "data_processed",
        "ausgrid",
        "ausgrid_halfhour_normalized.csv",
    ))
    independent_indices = findall(
        timestamp -> Dates.Date(timestamp) in module_ref.PILOT_DATES,
        independent_profile.timestamps,
    )
    independent_by_timestamp = Dict(
        independent_profile.timestamps[index] => independent_profile.pv_profile[index]
        for index in independent_indices
    )
    H_kw = 850.0
    expected = [
        (
            timestamp=timestamp,
            pv_kw=H_kw * independent_by_timestamp[timestamp],
        )
        for timestamp in independent_profile.timestamps[independent_indices]
    ]
    actual = [
        begin
            evaluated = module_ref.evaluate_point(
                production_network,
                production_profile,
                index,
                0.0,
                0.0;
                reference_pv_capacity_kw=H_kw,
            )
            (
                timestamp=production_profile.timestamps[index],
                pv_kw=evaluated.actual_reference_pv_kw,
            )
        end
        for index in production_indices
    ]

    expected_timestamps = [row.timestamp for row in expected]
    actual_timestamps = [row.timestamp for row in actual]
    expected_values = [row.pv_kw for row in expected]
    actual_values = [row.pv_kw for row in actual]
    night_indices = findall(
        index -> independent_profile.pv_profile[independent_indices[index]] <= 1e-12,
        eachindex(independent_indices),
    )
    expected_peak_index = argmax(expected_values)
    actual_peak_index = argmax(actual_values)

    @test independent_profile !== production_profile
    @test length(expected) == 96
    @test length(actual) == 96
    @test length(unique(expected_timestamps)) == 96
    @test length(unique(actual_timestamps)) == 96
    @test Set(expected_timestamps) == Set(actual_timestamps)
    @test expected_timestamps == actual_timestamps
    @test first(actual_timestamps) == Dates.DateTime(2012, 10, 15, 0, 0)
    @test last(actual_timestamps) == Dates.DateTime(2012, 10, 16, 23, 30)
    @test _timestamp_pv_vectors_match(expected, actual)
    @test length(unique(actual_values)) > 1
    @test !isempty(night_indices)
    @test all(iszero, actual_values[night_indices])
    @test expected_timestamps[expected_peak_index] ==
          actual_timestamps[actual_peak_index]
    @test isapprox(
        expected_values[expected_peak_index],
        actual_values[actual_peak_index];
        atol=1e-12,
        rtol=1e-12,
    )

    shifted_values = circshift(actual_values, 1)
    shifted = [
        (timestamp=actual[index].timestamp, pv_kw=shifted_values[index])
        for index in eachindex(actual)
    ]
    reversed_order = reverse(actual)
    constant_peak = [
        (timestamp=row.timestamp, pv_kw=maximum(actual_values))
        for row in actual
    ]
    @test !_timestamp_pv_vectors_match(expected, shifted)
    @test !_timestamp_pv_vectors_match(expected, reversed_order)
    @test !_timestamp_pv_vectors_match(expected, constant_peak)
end
