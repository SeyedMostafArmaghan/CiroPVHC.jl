if !isdefined(Main, :DSOVPPACMapStage0)
    include(joinpath(@__DIR__, "..", "src", "benchmark", "dso_vpp_ac_map_stage0.jl"))
end

using Dates

function _independent_stage0_expected(
    repository_root,
    timestamp,
    H_kw,
    p13_vpp_kw,
    p30_vpp_kw,
)
    buses, _ = CiroPVHC.build_ieee33_network()
    source_path = joinpath(
        repository_root,
        "data_processed",
        "ausgrid",
        "ausgrid_halfhour_normalized.csv",
    )
    profile = CiroPVHC.read_s1b_profile(source_path)
    timestamp_to_index = Dict(value => index for (index, value) in pairs(profile.timestamps))
    haskey(timestamp_to_index, timestamp) ||
        throw(ArgumentError("independent expected-value timestamp is absent from source"))
    profile_index = timestamp_to_index[timestamp]
    load_factor = profile.load_multiplier[profile_index]
    pv_factor = profile.pv_profile[profile_index]
    reference_pv_kw = Float64(H_kw) * pv_factor
    reference_by_bus_kw = zeros(Float64, length(buses))
    reference_by_bus_kw[13] = reference_pv_kw
    vpp_by_bus_kw = zeros(Float64, length(buses))
    vpp_by_bus_kw[13] = Float64(p13_vpp_kw)
    vpp_by_bus_kw[30] = Float64(p30_vpp_kw)
    active_injection_by_bus_kw = reference_by_bus_kw .+ vpp_by_bus_kw
    net_demand_pu = ComplexF64[
        complex(
            bus.pd_kw * load_factor - active_injection_by_bus_kw[bus.id],
            bus.qd_kvar * load_factor,
        ) / 10_000.0
        for bus in buses
    ]
    return (
        source_profile=profile,
        source_buses=buses,
        source_timestamp=profile.timestamps[profile_index],
        load_factor=load_factor,
        pv_factor=pv_factor,
        reference_pv_kw=reference_pv_kw,
        reference_by_bus_kw=reference_by_bus_kw,
        vpp_by_bus_kw=vpp_by_bus_kw,
        active_injection_by_bus_kw=active_injection_by_bus_kw,
        net_demand_pu=net_demand_pu,
    )
end

function _assert_independent_stage0_inputs(
    evaluated,
    network,
    repository_root,
    timestamp,
    H_kw,
    p13_vpp_kw,
    p30_vpp_kw,
)
    expected = _independent_stage0_expected(
        repository_root,
        timestamp,
        H_kw,
        p13_vpp_kw,
        p30_vpp_kw,
    )
    discrepancies = NamedTuple[]
    for bus in eachindex(network.buses)
        push!(discrepancies, (
            magnitude=abs(
                evaluated.assembled_reference_pv_by_bus_kw[bus] -
                expected.reference_by_bus_kw[bus],
            ),
            bus=bus,
            component="reference_pv_kw",
        ))
        push!(discrepancies, (
            magnitude=abs(
                evaluated.assembled_vpp_injection_by_bus_kw[bus] -
                expected.vpp_by_bus_kw[bus],
            ),
            bus=bus,
            component="vpp_injection_kw",
        ))
        push!(discrepancies, (
            magnitude=abs(
                evaluated.assembled_active_injection_by_bus_kw[bus] -
                expected.active_injection_by_bus_kw[bus],
            ),
            bus=bus,
            component="total_active_injection_kw",
        ))
        push!(discrepancies, (
            magnitude=abs(
                real(evaluated.assembled_net_demand_pu[bus]) -
                real(expected.net_demand_pu[bus]),
            ),
            bus=bus,
            component="net_active_demand_pu",
        ))
        push!(discrepancies, (
            magnitude=abs(
                imag(evaluated.assembled_net_demand_pu[bus]) -
                imag(expected.net_demand_pu[bus]),
            ),
            bus=bus,
            component="net_reactive_demand_pu",
        ))
    end
    worst = discrepancies[argmax(row.magnitude for row in discrepancies)]
    @test worst.magnitude <= 1e-14
    @test expected.source_buses !== network.buses
    @test expected.source_timestamp == timestamp
    @test all(
        isapprox(
            imag(expected.net_demand_pu[bus.id]),
            bus.qd_kvar * expected.load_factor / 10_000.0;
            atol=0.0,
            rtol=0.0,
        )
        for bus in expected.source_buses
    )
    @test all(
        isapprox(
            real(expected.net_demand_pu[bus.id]),
            (
                bus.pd_kw * expected.load_factor -
                expected.active_injection_by_bus_kw[bus.id]
            ) / 10_000.0;
            atol=0.0,
            rtol=0.0,
        )
        for bus in expected.source_buses
    )
    return (
        maximum_absolute_discrepancy=worst.magnitude,
        bus=worst.bus,
        component=worst.component,
        expected=expected,
    )
end

@testset "Stage-0 independent physical-input propagation" begin
    module_ref = Main.DSOVPPACMapStage0
    repository_root = normpath(joinpath(@__DIR__, ".."))
    profile = module_ref.load_profile(repository_root)
    indices = module_ref.select_pilot_indices(profile)
    network = module_ref.build_pilot_network()
    daytime_index = indices[argmax(profile.pv_profile[indices])]
    nighttime_index = indices[argmin(profile.pv_profile[indices])]
    H_kw = 850.0
    delta_kw = 100.0
    balance_tolerance_kw = module_ref.RESIDUAL_TOLERANCE_PU * module_ref.BASE_KW
    evaluated_cases = NamedTuple[]

    forbidden_helper = join(("assemble", "stage0", "inputs"), "_")
    independent_lowered = Base.code_lowered(
        _independent_stage0_expected,
        Tuple{String,Dates.DateTime,Float64,Float64,Float64},
    )
    @test !occursin(forbidden_helper, sprint(show, independent_lowered))
    independently_read = _independent_stage0_expected(
        repository_root,
        profile.timestamps[daytime_index],
        H_kw,
        0.0,
        0.0,
    )
    @test independently_read.source_profile !== profile
    @test independently_read.source_buses !== network.buses

    with_reference = module_ref.evaluate_point(
        network, profile, daytime_index, 0.0, 0.0;
        reference_pv_capacity_kw=H_kw,
    )
    without_reference = module_ref.evaluate_point(
        network, profile, daytime_index, 0.0, 0.0;
        reference_pv_capacity_kw=0.0,
    )
    append!(evaluated_cases, (with_reference, without_reference))
    with_input_check = _assert_independent_stage0_inputs(
        with_reference,
        network,
        repository_root,
        profile.timestamps[daytime_index],
        H_kw,
        0.0,
        0.0,
    )
    _assert_independent_stage0_inputs(
        without_reference,
        network,
        repository_root,
        profile.timestamps[daytime_index],
        0.0,
        0.0,
        0.0,
    )
    expected_reference_pv_kw = H_kw * profile.pv_profile[daytime_index]
    delta_p_sub_kw =
        without_reference.substation_p_kw - with_reference.substation_p_kw
    delta_p_loss_kw =
        with_reference.active_losses_kw - without_reference.active_losses_kw
    @test expected_reference_pv_kw > 1e-9
    @test abs(delta_p_sub_kw + delta_p_loss_kw - expected_reference_pv_kw) <=
          balance_tolerance_kw
    @test abs(delta_p_sub_kw) > 0.5 * expected_reference_pv_kw
    @test isapprox(
        with_reference.actual_reference_pv_kw,
        expected_reference_pv_kw;
        atol=1e-10,
        rtol=1e-12,
    )
    @test with_input_check.maximum_absolute_discrepancy == 0.0

    @test profile.pv_profile[nighttime_index] <= 1e-12
    night_with_H = module_ref.evaluate_point(
        network, profile, nighttime_index, 0.0, 0.0;
        reference_pv_capacity_kw=H_kw,
    )
    night_without_H = module_ref.evaluate_point(
        network, profile, nighttime_index, 0.0, 0.0;
        reference_pv_capacity_kw=0.0,
    )
    append!(evaluated_cases, (night_with_H, night_without_H))
    _assert_independent_stage0_inputs(
        night_with_H,
        network,
        repository_root,
        profile.timestamps[nighttime_index],
        H_kw,
        0.0,
        0.0,
    )
    _assert_independent_stage0_inputs(
        night_without_H,
        network,
        repository_root,
        profile.timestamps[nighttime_index],
        0.0,
        0.0,
        0.0,
    )
    @test night_with_H.actual_reference_pv_kw == 0.0
    @test night_without_H.actual_reference_pv_kw == 0.0
    @test isapprox(
        night_with_H.substation_p_kw,
        night_without_H.substation_p_kw;
        atol=1e-10,
        rtol=0.0,
    )
    @test maximum(
        abs.(night_with_H.primary_voltage_complex_pu .-
             night_without_H.primary_voltage_complex_pu),
    ) <= 1e-12

    zero_H = module_ref.evaluate_point(
        network, profile, daytime_index, 0.0, 0.0;
        reference_pv_capacity_kw=0.0,
    )
    bus13 = module_ref.evaluate_point(
        network, profile, daytime_index, delta_kw, 0.0;
        reference_pv_capacity_kw=0.0,
    )
    bus30 = module_ref.evaluate_point(
        network, profile, daytime_index, 0.0, delta_kw;
        reference_pv_capacity_kw=0.0,
    )
    append!(evaluated_cases, (zero_H, bus13, bus30))
    bus13_check = _assert_independent_stage0_inputs(
        bus13,
        network,
        repository_root,
        profile.timestamps[daytime_index],
        0.0,
        delta_kw,
        0.0,
    )
    bus30_check = _assert_independent_stage0_inputs(
        bus30,
        network,
        repository_root,
        profile.timestamps[daytime_index],
        0.0,
        0.0,
        delta_kw,
    )
    delta13 = bus13.assembled_active_injection_by_bus_kw .-
              zero_H.assembled_active_injection_by_bus_kw
    delta30 = bus30.assembled_active_injection_by_bus_kw .-
              zero_H.assembled_active_injection_by_bus_kw
    @test findall(x -> !iszero(x), delta13) == [13]
    @test delta13[13] == delta_kw
    @test findall(x -> !iszero(x), delta30) == [30]
    @test delta30[30] == delta_kw
    for injected in (bus13, bus30)
        injection_response_kw = zero_H.substation_p_kw - injected.substation_p_kw
        loss_change_kw = injected.active_losses_kw - zero_H.active_losses_kw
        @test abs(injection_response_kw + loss_change_kw - delta_kw) <=
              balance_tolerance_kw
        @test maximum(
            abs.(abs.(injected.primary_voltage_complex_pu) .-
                 abs.(zero_H.primary_voltage_complex_pu)),
        ) > 1e-8
        @test injected.replay_status == "PASSED"
    end
    @test bus13_check.maximum_absolute_discrepancy == 0.0
    @test bus30_check.maximum_absolute_discrepancy == 0.0

    combined13 = module_ref.evaluate_point(
        network, profile, daytime_index, delta_kw, 0.0;
        reference_pv_capacity_kw=H_kw,
    )
    simultaneous = module_ref.evaluate_point(
        network, profile, daytime_index, 75.0, 125.0;
        reference_pv_capacity_kw=H_kw,
    )
    append!(evaluated_cases, (combined13, simultaneous))
    combined13_check = _assert_independent_stage0_inputs(
        combined13,
        network,
        repository_root,
        profile.timestamps[daytime_index],
        H_kw,
        delta_kw,
        0.0,
    )
    simultaneous_check = _assert_independent_stage0_inputs(
        simultaneous,
        network,
        repository_root,
        profile.timestamps[daytime_index],
        H_kw,
        75.0,
        125.0,
    )
    @test combined13.assembled_reference_pv_by_bus_kw[13] ==
          expected_reference_pv_kw
    @test combined13.assembled_vpp_injection_by_bus_kw[13] == delta_kw
    @test combined13.assembled_active_injection_by_bus_kw[13] ==
          expected_reference_pv_kw + delta_kw
    @test simultaneous.assembled_active_injection_by_bus_kw[13] ==
          expected_reference_pv_kw + 75.0
    @test simultaneous.assembled_active_injection_by_bus_kw[30] == 125.0
    @test combined13_check.maximum_absolute_discrepancy == 0.0
    @test simultaneous_check.maximum_absolute_discrepancy == 0.0

    old_cases = [
        (
            timestamp=Dates.DateTime(2012, 10, 15, 0, 0),
            p13=0.0,
            p30=0.0,
            p_sub=536.292807618,
            vmin=0.98833988186,
            vmax=1.0,
        ),
        (
            timestamp=Dates.DateTime(2012, 10, 15, 0, 0),
            p13=2000.0,
            p30=500.0,
            p_sub=-1810.89732789,
            vmin=1.0,
            vmax=1.07760756188,
        ),
        (
            timestamp=Dates.DateTime(2012, 10, 15, 2, 30),
            p13=1138.671875,
            p30=-2475.30864198,
            p_sub=2013.4334324,
            vmin=0.919383801412,
            vmax=1.00390611118,
        ),
    ]
    for old in old_cases
        profile_index = findfirst(==(old.timestamp), profile.timestamps)
        @test profile_index !== nothing
        reproduced = module_ref.evaluate_point(
            network, profile, profile_index, old.p13, old.p30;
            reference_pv_capacity_kw=0.0,
        )
        push!(evaluated_cases, reproduced)
        @test isapprox(reproduced.substation_p_kw, old.p_sub; atol=1e-8, rtol=0.0)
        @test isapprox(reproduced.minimum_voltage_pu, old.vmin; atol=1e-11, rtol=0.0)
        @test isapprox(reproduced.maximum_voltage_pu, old.vmax; atol=1e-11, rtol=0.0)
    end

    @test all(case.power_flow_status == "CONVERGED" for case in evaluated_cases)
    @test all(case.replay_status == "PASSED" for case in evaluated_cases)
    @test maximum(case.maximum_absolute_residual for case in evaluated_cases) <=
          module_ref.RESIDUAL_TOLERANCE_PU
end
