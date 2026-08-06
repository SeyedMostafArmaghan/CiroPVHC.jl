using Dates

@testset "Command and absolute-PCC coordinate semantics" begin
    transform = audited_pilot_interface_transform()
    operating_point = transform.operating_point

    @test operating_point.timestamp == DateTime(2012, 10, 15, 13, 0, 0)
    @test [interface.id for interface in operating_point.interfaces] == [:PCC_13, :PCC_30]
    @test [interface.bus_id for interface in operating_point.interfaces] == [13, 30]
    @test operating_point.p_pcc_base_kw == [777.7133428167988, 0.0]
    @test all(
        reactive_policy_name(interface.reactive_policy) == "UNITY_POWER_FACTOR"
        for interface in operating_point.interfaces
    )
    @test REFERENCE_PV_OWNERSHIP == :REFERENCE_PV_850_KW_IS_TVPP_OWNED
    @test REFERENCE_PV_CAPACITY_ACCOUNTING_STATUS ==
          :REFERENCE_PV_CAPACITY_ACCOUNTING_REQUIRES_FINAL_HC_FORMULATION_DECISION
    @test BUS_13_CASE_LOAD_OWNERSHIP == :BUS_13_CASE_LOAD_IS_DSO_BACKGROUND
    @test BUS_30_CASE_LOAD_OWNERSHIP == :BUS_30_CASE_LOAD_IS_DSO_BACKGROUND

    command = CommandInjection(operating_point.interfaces, [156.89470053621986, 1610.2756675516089])
    absolute = command_to_absolute(transform, command)
    @test absolute.interface_ids == [:PCC_13, :PCC_30]
    @test absolute.bus_ids == [13, 30]
    @test absolute.p_pcc_abs_kw == [934.6080433530186, 1610.2756675516089]
    @test absolute.q_pcc_kvar == [0.0, 0.0]
    round_trip = absolute_to_command(transform, absolute)
    @test round_trip.interface_ids == command.interface_ids
    @test round_trip.bus_ids == command.bus_ids
    @test all(isapprox.(
        round_trip.p_command_kw,
        command.p_command_kw;
        atol=1e-12,
        rtol=0.0,
    ))

    reordered_interfaces = [
        InterfaceDefinition(:PCC_C, 24),
        InterfaceDefinition(:PCC_A, 13),
        InterfaceDefinition(:PCC_B, 30),
    ]
    reordered_transform = InterfaceCoordinateTransform(InterfaceOperatingPoint(
        DateTime(2026, 1, 1),
        reordered_interfaces,
        [3.0, 1.0, 2.0],
    ))
    reordered_command = CommandInjection(reordered_interfaces, [30.0, 10.0, 20.0])
    reordered_absolute = command_to_absolute(reordered_transform, reordered_command)
    @test reordered_absolute.interface_ids == [:PCC_C, :PCC_A, :PCC_B]
    @test reordered_absolute.bus_ids == [24, 13, 30]
    @test reordered_absolute.p_pcc_abs_kw == [33.0, 11.0, 22.0]
    @test absolute_to_command(reordered_transform, reordered_absolute).p_command_kw ==
          [30.0, 10.0, 20.0]

    @test_throws DimensionMismatch CommandInjection([:PCC_13], [13, 30], [0.0])
    @test_throws DimensionMismatch InterfaceOperatingPoint(
        DateTime(2026, 1, 1), reordered_interfaces, [1.0, 2.0],
    )
    wrong_order = CommandInjection([:PCC_30, :PCC_13], [30, 13], [0.0, 0.0])
    @test_throws ArgumentError command_to_absolute(transform, wrong_order)
    wrong_bus = CommandInjection([:PCC_13, :PCC_30], [13, 31], [0.0, 0.0])
    @test_throws ArgumentError command_to_absolute(transform, wrong_bus)

    zero_command = CommandInjection(operating_point.interfaces, [0.0, 0.0])
    pilot_absolute = command_to_absolute(transform, zero_command)
    @test pilot_absolute.p_pcc_abs_kw == [AUDITED_REFERENCE_PV_INJECTION_KW, 0.0]
    load_multiplier = 0.15594037439888725
    passive_p = Dict(13 => 60.0 * load_multiplier, 30 => 200.0 * load_multiplier)
    passive_q = Dict(13 => 35.0 * load_multiplier, 30 => 600.0 * load_multiplier)
    p_net = assemble_bus_net_active_demand_kw(passive_p, pilot_absolute)
    q_net = assemble_bus_net_reactive_demand_kvar(passive_q, pilot_absolute)
    @test pilot_absolute.p_pcc_abs_kw[1] == AUDITED_REFERENCE_PV_INJECTION_KW
    @test p_net[13] == passive_p[13] - AUDITED_REFERENCE_PV_INJECTION_KW
    @test p_net[30] == passive_p[30]
    @test pilot_absolute.q_pcc_kvar == [0.0, 0.0]
    @test q_net == passive_q

    aggregate = AggregateResourcePower([:PCC_13, :PCC_30], [13, 30], [1.0, -2.0])
    @test aggregate.p_agg_kw == [1.0, -2.0]
    @test !(aggregate isa CommandInjection)
    @test !(aggregate isa AbsolutePCCInjection)
end

@testset "Coordinate layer preserves the locked command-space AC path" begin
    if !isdefined(Main, :DSOVPPACMapStage0)
        include(joinpath(@__DIR__, "..", "src", "benchmark", "dso_vpp_ac_map_stage0.jl"))
    end
    stage0 = Main.DSOVPPACMapStage0
    repository_root = normpath(joinpath(@__DIR__, ".."))
    profile = stage0.load_profile(repository_root)
    profile_index = findfirst(==(AUDITED_PCC_TIMESTAMP), profile.timestamps)
    @test profile_index !== nothing
    network = stage0.build_pilot_network()
    p13_command_kw = 25.0
    p30_command_kw = 40.0
    legacy = stage0.evaluate_point(
        network, profile, profile_index, p13_command_kw, p30_command_kw,
    )
    transform = audited_pilot_interface_transform()
    command = CommandInjection(
        transform.operating_point.interfaces,
        [p13_command_kw, p30_command_kw],
    )
    absolute = command_to_absolute(transform, command)

    @test legacy.power_flow_status == "CONVERGED"
    @test legacy.replay_status == "PASSED"
    @test legacy.p13_vpp_kw == p13_command_kw
    @test legacy.p30_vpp_kw == p30_command_kw
    @test legacy.actual_reference_pv_kw == AUDITED_REFERENCE_PV_INJECTION_KW
    @test legacy.assembled_active_injection_by_bus_kw[13] == absolute.p_pcc_abs_kw[1]
    @test legacy.assembled_active_injection_by_bus_kw[30] == absolute.p_pcc_abs_kw[2]
    @test legacy.q13_vpp_kvar == absolute.q_pcc_kvar[1]
    @test legacy.q30_vpp_kvar == absolute.q_pcc_kvar[2]
end
