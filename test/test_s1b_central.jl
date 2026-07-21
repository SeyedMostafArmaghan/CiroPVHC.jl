using Test
using Dates
using CiroPVHC

function _s1b_dependencies_available()
    try
        CiroPVHC._load_s1b_solver!()
        return true
    catch
        return false
    end
end

@testset "S1-B central configuration and model" begin
    if !_s1b_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        import JuMP

        timestamps = [DateTime(2012, 1, 1, 0, 0), DateTime(2012, 1, 1, 0, 30)]
        profile = CiroPVHC.S1BProfile(
            timestamps,
            [0.4, 0.3],
            [0.5, 0.8],
            "synthetic.csv",
            "synthetic",
        )
        bundle = build_s1b_central_model(profile, [1, 2])

        @test bundle.full_indices == [1, 2]
        @test bundle.data.timeseries.T == 2
        @test bundle.data.vmin_pu^2 == 0.90^2
        @test bundle.data.vmax_pu^2 == 1.05^2
        @test all(branch.smax_kva == 0.0 for branch in bundle.data.branches)
        @test all(!JuMP.has_upper_bound(bundle.capacity_kw[bus]) for bus in CiroPVHC.S1B_CANDIDATE_BUSES)
        names = [JuMP.name(variable) for variable in JuMP.all_variables(bundle.model)]
        @test count(startswith("pv_capacity_kw"), names) == 4
        @test all(!JuMP.has_lower_bound(bundle.network.Pij[branch, t])
                  for branch in bundle.network.topology.branch_ids for t in 1:2)
        @test all(!JuMP.has_upper_bound(bundle.network.ell[branch, t])
                  for branch in bundle.network.topology.branch_ids for t in 1:2)
        @test all(JuMP.lower_bound(bundle.network.v[bus, t]) == 0.90^2
                  for bus in bundle.network.topology.bus_ids for t in 1:2)
        @test all(JuMP.upper_bound(bundle.network.v[bus, t]) == 1.05^2
                  for bus in bundle.network.topology.bus_ids for t in 1:2)
        @test JuMP.objective_sense(bundle.model) == JuMP.MOI.MAX_SENSE

        @test !any(contains("curtail"), names)
        @test !any(contains("gamma"), names)
        @test !any(contains("export"), names)

        for bus in CiroPVHC.S1B_CANDIDATE_BUSES, t in 1:2
            expr = bundle.network === nothing ? nothing : bundle
            @test expr !== nothing
            @test profile.pv_profile[t] >= 0.0
        end
    end
end

@testset "S1-B audit selection is shared and complete" begin
    if !_s1b_dependencies_available()
        @test_skip "JuMP and Clarabel are not available in this Julia environment"
    else
        repository_root = normpath(joinpath(@__DIR__, ".."))
        profile = read_s1b_profile(joinpath(
            repository_root, "data_processed", "ausgrid", "ausgrid_halfhour_normalized.csv",
        ))
        indices = read_s1b_initial_indices(
            profile,
            joinpath(repository_root, "results", "pre_s1_audit", "critical_day_candidates.csv"),
        )
        @test length(indices) == 32 * 48 == 1_536
        @test length(unique(Date(profile.timestamps[i]) for i in indices)) == 32
        @test all(count(i -> Date(profile.timestamps[i]) == day, indices) == 48
                  for day in unique(Date(profile.timestamps[i]) for i in indices))
    end
end
