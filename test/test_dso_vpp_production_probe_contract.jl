if !isdefined(Main, :DSOVPPProductionProbeContract)
    include(joinpath(@__DIR__, "..", "src", "benchmark",
                     "dso_vpp_production_probe_contract.jl"))
end

@testset "Production probe boundary contract" begin
    contract = Main.DSOVPPProductionProbeContract

    endpoint(status, coordinate; vmin=0.99, vmin_bus=18, vmax=1.0, vmax_bus=1) =
        contract.BoundaryEndpoint(
            coordinate=Float64(coordinate), p13_abs_kw=Float64(coordinate),
            p30_abs_kw=0.0, vmin_pu=Float64(vmin), vmin_bus=vmin_bus,
            vmax_pu=Float64(vmax), vmax_bus=vmax_bus, solver_status=status,
        )

    @test contract.finite_valid_axis_status("AXIS_CERTIFIED_BOUNDARY")
    @test !contract.finite_valid_axis_status("AXIS_UNBOUNDED_WITHIN_GUARD")
    @test !contract.finite_valid_axis_status("AXIS_UNRESOLVED")
    @test !contract.finite_valid_axis_status("AXIS_REENTRY_DETECTED")

    safe = endpoint("CONVERGED_FEASIBLE", 4.0; vmax=1.049)
    violating_max = endpoint("CONVERGED_INFEASIBLE", 5.0; vmax=1.051, vmax_bus=13)
    violating_min = endpoint("CONVERGED_INFEASIBLE", 5.0; vmin=0.899, vmin_bus=30)
    nonconverged = endpoint("NONCONVERGED_AFTER_RETRY", 5.0; vmin=NaN, vmax=NaN,
                            vmin_bus=nothing, vmax_bus=nothing)
    mislabeled = endpoint("CONVERGED_INFEASIBLE", 5.0; vmin=0.99, vmax=1.01)

    @test contract.valid_voltage_bracket(safe, violating_max)
    @test contract.valid_voltage_bracket(safe, violating_min)
    @test !contract.valid_voltage_bracket(safe, nonconverged)
    @test !contract.valid_voltage_bracket(safe, mislabeled)
    @test contract.transition_outcome(:axis, safe, nonconverged) == "AXIS_UNRESOLVED"
    @test contract.transition_outcome(:ray, safe, nonconverged) == "RAY_UNRESOLVED"
    @test contract.transition_outcome(:axis, safe, violating_max) == "AXIS_BRACKET_CERTIFIED"

    plan = contract.retry_plan(nearest_accepted_neighbor_available=true)
    @test length(plan) == 2
    @test plan[1].initialization == "FLAT_START"
    @test plan[2].initialization == "NEAREST_ACCEPTED_NEIGHBOR_START"
    @test plan[1].initialization != plan[2].initialization
    @test length(contract.retry_plan(nearest_accepted_neighbor_available=false)) == 1

    @test contract.binding_invariant("BINDING_VMAX", violating_max)
    @test contract.binding_invariant("BINDING_VMIN", violating_min)
    @test !contract.binding_invariant("BINDING_VMAX", nonconverged)
    @test !contract.binding_invariant("BINDING_VMIN", mislabeled)
    @test contract.official_boundary_coordinate(safe, violating_max) == safe.coordinate
    @test_throws ArgumentError contract.official_boundary_coordinate(safe, nonconverged)
end
