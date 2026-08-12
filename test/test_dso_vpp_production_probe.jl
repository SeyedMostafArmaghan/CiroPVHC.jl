if !isdefined(Main, :DSOVPPProductionProbe)
    include(joinpath(@__DIR__, "..", "src", "benchmark", "dso_vpp_production_probe.jl"))
end

@testset "Production probe deterministic search helpers" begin
    probe = Main.DSOVPPProductionProbe
    config = probe.ProbeConfig()

    point(status, coordinate; vmin=0.99, vmax=1.0, vmin_bus=18, vmax_bus=1) =
        probe.PointResult(
            coordinate=Float64(coordinate), p13_abs_kw=Float64(coordinate),
            p30_abs_kw=0.0, vmin_pu=Float64(vmin), vmin_bus=vmin_bus,
            vmax_pu=Float64(vmax), vmax_bus=vmax_bus, solver_status=status,
        )

    safe0 = point("CONVERGED_FEASIBLE", 0.0)
    safe1 = point("CONVERGED_FEASIBLE", 1.0; vmax=1.049999)
    violating = point("CONVERGED_INFEASIBLE", 2.0; vmax=1.050001, vmax_bus=13)
    unresolved = point("UNRESOLVED", 3.0; vmin=NaN, vmax=NaN,
                       vmin_bus=nothing, vmax_bus=nothing)

    @test probe.first_adjacent_bracket([safe0, safe1, violating]) == (safe1, violating)
    @test probe.reentry_detected([safe0, violating, safe1])
    @test !probe.reentry_detected([safe0, safe1, violating, unresolved])
    @test probe.binding_mechanism(violating, config) == "BINDING_VMAX"
    @test probe.endpoint_voltage_close(safe1, violating, config)

    left = (binding_mechanism="BINDING_VMIN", binding_bus=18,
            official_boundary_r=0.8, status="RAY_CERTIFIED_BOUNDARY")
    right = (binding_mechanism="BINDING_VMAX", binding_bus=30,
             official_boundary_r=1.0, status="RAY_CERTIFIED_BOUNDARY")
    triggers = probe.adaptive_trigger(left, right)
    @test triggers == [
        "BOUNDARY_MECHANISM_CHANGE",
        "BINDING_BUS_CHANGE",
        "NORMALIZED_RADIUS_DIFFERENCE_GT_10_PERCENT",
    ]

    state = probe.EvaluationState()
    push!(state.accepted_neighbors, probe.AcceptedNeighbor(
        p13_abs_kw=-1.0, p30_abs_kw=0.0, logical_evaluation_id=2,
        voltage=ComplexF64[1.0 + 0.0im],
    ))
    push!(state.accepted_neighbors, probe.AcceptedNeighbor(
        p13_abs_kw=1.0, p30_abs_kw=0.0, logical_evaluation_id=1,
        voltage=ComplexF64[1.0 + 0.0im],
    ))
    selected = probe.nearest_accepted_neighbor(state, 0.0, 0.0)
    @test selected.logical_evaluation_id == 1

    @test probe.split_csv_line("a,\"b,c\",\"d\"\"e\"") == ["a", "b,c", "d\"e"]
    repository_root = normpath(joinpath(@__DIR__, ".."))
    @test length(probe.git_output(repository_root, "rev-parse", "HEAD")) == 40

    temporary_path, io = mktemp()
    try
        write(io, "alpha\r\nbeta\rgamma\n")
        close(io)
        expected = bytes2hex(probe.sha256(Vector{UInt8}(codeunits("alpha\nbeta\ngamma\n"))))
        @test probe.normalized_sha256(temporary_path) == expected
    finally
        isopen(io) && close(io)
        rm(temporary_path; force=true)
    end
end
