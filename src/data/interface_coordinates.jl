abstract type InterfaceReactivePolicy end

"Current pilot policy: interface reactive power is zero for every active-power value."
struct UnityPowerFactor <: InterfaceReactivePolicy end

const UNITY_POWER_FACTOR = UnityPowerFactor()

"One physical TVPP interface and its active-to-reactive power policy."
struct InterfaceDefinition
    id::Symbol
    bus_id::Int
    reactive_policy::InterfaceReactivePolicy

    function InterfaceDefinition(
        id,
        bus_id::Integer,
        reactive_policy::InterfaceReactivePolicy=UNITY_POWER_FACTOR,
    )
        interface_id = Symbol(id)
        isempty(String(interface_id)) && throw(ArgumentError("interface id must not be empty"))
        bus = Int(bus_id)
        bus > 0 || throw(ArgumentError("interface bus id must be positive"))
        return new(interface_id, bus, reactive_policy)
    end
end

function _validated_interface_definitions(interfaces)
    values = InterfaceDefinition[interface for interface in interfaces]
    isempty(values) && throw(ArgumentError("at least one interface is required"))
    ids = [interface.id for interface in values]
    length(unique(ids)) == length(ids) ||
        throw(ArgumentError("interface ids must be unique"))
    return values
end

function _validated_coordinate_values(values, label::AbstractString)
    result = Float64.(collect(values))
    all(isfinite, result) || throw(ArgumentError("$label must contain only finite values"))
    return result
end

"Fixed timestamp and absolute-PCC baseline used to translate incremental commands."
struct InterfaceOperatingPoint
    timestamp::DateTime
    interfaces::Vector{InterfaceDefinition}
    p_pcc_base_kw::Vector{Float64}

    function InterfaceOperatingPoint(timestamp::DateTime, interfaces, p_pcc_base_kw)
        definitions = _validated_interface_definitions(interfaces)
        base = _validated_coordinate_values(p_pcc_base_kw, "P_PCC baseline")
        length(base) == length(definitions) || throw(DimensionMismatch(
            "P_PCC baseline has $(length(base)) values for $(length(definitions)) interfaces",
        ))
        return new(timestamp, definitions, base)
    end
end

"Incremental experimental active-power command in explicitly ordered kW coordinates."
struct CommandInjection
    interface_ids::Vector{Symbol}
    bus_ids::Vector{Int}
    p_command_kw::Vector{Float64}

    function CommandInjection(interface_ids, bus_ids, p_command_kw)
        ids = Symbol.(collect(interface_ids))
        buses = Int.(collect(bus_ids))
        values = _validated_coordinate_values(p_command_kw, "P_command")
        length(ids) == length(buses) == length(values) || throw(DimensionMismatch(
            "command interface ids, bus ids, and values must have equal lengths",
        ))
        isempty(ids) && throw(ArgumentError("at least one command interface is required"))
        length(unique(ids)) == length(ids) ||
            throw(ArgumentError("command interface ids must be unique"))
        all(>(0), buses) || throw(ArgumentError("command bus ids must be positive"))
        return new(ids, buses, values)
    end
end

function CommandInjection(interfaces, p_command_kw)
    definitions = _validated_interface_definitions(interfaces)
    return CommandInjection(
        [interface.id for interface in definitions],
        [interface.bus_id for interface in definitions],
        p_command_kw,
    )
end

"Absolute physical TVPP interface P/Q injection, excluding passive DSO background load."
struct AbsolutePCCInjection
    interface_ids::Vector{Symbol}
    bus_ids::Vector{Int}
    p_pcc_abs_kw::Vector{Float64}
    q_pcc_kvar::Vector{Float64}

    function AbsolutePCCInjection(interface_ids, bus_ids, p_pcc_abs_kw, q_pcc_kvar)
        ids = Symbol.(collect(interface_ids))
        buses = Int.(collect(bus_ids))
        p_values = _validated_coordinate_values(p_pcc_abs_kw, "absolute P_PCC")
        q_values = _validated_coordinate_values(q_pcc_kvar, "absolute Q_PCC")
        length(ids) == length(buses) == length(p_values) == length(q_values) ||
            throw(DimensionMismatch(
                "absolute-PCC interface ids, bus ids, P values, and Q values must have equal lengths",
            ))
        isempty(ids) && throw(ArgumentError("at least one absolute-PCC interface is required"))
        length(unique(ids)) == length(ids) ||
            throw(ArgumentError("absolute-PCC interface ids must be unique"))
        all(>(0), buses) || throw(ArgumentError("absolute-PCC bus ids must be positive"))
        return new(ids, buses, p_values, q_values)
    end
end

"Future resource-derived aggregate power; intentionally distinct from command and PCC power."
struct AggregateResourcePower
    interface_ids::Vector{Symbol}
    bus_ids::Vector{Int}
    p_agg_kw::Vector{Float64}

    function AggregateResourcePower(interface_ids, bus_ids, p_agg_kw)
        ids = Symbol.(collect(interface_ids))
        buses = Int.(collect(bus_ids))
        values = _validated_coordinate_values(p_agg_kw, "P_agg")
        length(ids) == length(buses) == length(values) || throw(DimensionMismatch(
            "aggregate-power interface ids, bus ids, and values must have equal lengths",
        ))
        isempty(ids) && throw(ArgumentError("at least one aggregate-power interface is required"))
        length(unique(ids)) == length(ids) ||
            throw(ArgumentError("aggregate-power interface ids must be unique"))
        all(>(0), buses) || throw(ArgumentError("aggregate-power bus ids must be positive"))
        return new(ids, buses, values)
    end
end

"Deterministic translation between command and absolute-PCC coordinates."
struct InterfaceCoordinateTransform
    operating_point::InterfaceOperatingPoint
end

reactive_policy_name(::UnityPowerFactor) = "UNITY_POWER_FACTOR"

function interface_reactive_power_kvar(::UnityPowerFactor, p_pcc_abs_kw::Real)
    isfinite(Float64(p_pcc_abs_kw)) ||
        throw(ArgumentError("absolute P_PCC must be finite"))
    return 0.0
end

function _validate_coordinate_layout(transform::InterfaceCoordinateTransform, ids, buses)
    interfaces = transform.operating_point.interfaces
    expected_ids = [interface.id for interface in interfaces]
    expected_buses = [interface.bus_id for interface in interfaces]
    length(ids) == length(expected_ids) || throw(DimensionMismatch(
        "coordinate vector has $(length(ids)) interfaces; expected $(length(expected_ids))",
    ))
    ids == expected_ids || throw(ArgumentError(
        "interface id/order mismatch: received $(join(ids, ',')); expected $(join(expected_ids, ','))",
    ))
    buses == expected_buses || throw(ArgumentError(
        "bus/interface mapping mismatch: received $(join(buses, ',')); expected $(join(expected_buses, ','))",
    ))
    return nothing
end

"Translate P_command to absolute P_PCC and resolve Q_PCC from each interface policy."
function command_to_absolute(
    transform::InterfaceCoordinateTransform,
    command::CommandInjection,
)
    _validate_coordinate_layout(transform, command.interface_ids, command.bus_ids)
    operating_point = transform.operating_point
    p_absolute = operating_point.p_pcc_base_kw .+ command.p_command_kw
    q_absolute = [
        interface_reactive_power_kvar(interface.reactive_policy, p_absolute[index])
        for (index, interface) in pairs(operating_point.interfaces)
    ]
    return AbsolutePCCInjection(
        command.interface_ids,
        command.bus_ids,
        p_absolute,
        q_absolute,
    )
end

"Translate absolute P_PCC back to P_command when the fixed baseline is known."
function absolute_to_command(
    transform::InterfaceCoordinateTransform,
    absolute::AbsolutePCCInjection;
    reactive_tolerance_kvar::Real=1e-9,
)
    reactive_tolerance_kvar >= 0 ||
        throw(ArgumentError("reactive tolerance must be nonnegative"))
    _validate_coordinate_layout(transform, absolute.interface_ids, absolute.bus_ids)
    interfaces = transform.operating_point.interfaces
    expected_q = [
        interface_reactive_power_kvar(interface.reactive_policy, absolute.p_pcc_abs_kw[index])
        for (index, interface) in pairs(interfaces)
    ]
    all(
        isapprox(absolute.q_pcc_kvar[index], expected_q[index];
                 atol=Float64(reactive_tolerance_kvar), rtol=0.0)
        for index in eachindex(expected_q)
    ) || throw(ArgumentError("absolute Q_PCC values do not match the interface reactive policies"))
    return CommandInjection(
        absolute.interface_ids,
        absolute.bus_ids,
        absolute.p_pcc_abs_kw .- transform.operating_point.p_pcc_base_kw,
    )
end

function _validated_bus_mapping(mapping, label::AbstractString)
    result = Dict{Int,Float64}()
    for (raw_bus, raw_value) in pairs(mapping)
        bus = Int(raw_bus)
        bus > 0 || throw(ArgumentError("$label bus ids must be positive"))
        value = Float64(raw_value)
        isfinite(value) || throw(ArgumentError("$label values must be finite"))
        result[bus] = value
    end
    return result
end

"Assemble p_net = passive DSO load - absolute PCC export - other DSO injections."
function assemble_bus_net_active_demand_kw(
    passive_dso_load_by_bus_kw,
    absolute::AbsolutePCCInjection;
    other_nonload_dso_injection_by_bus_kw=Dict{Int,Float64}(),
)
    passive = _validated_bus_mapping(passive_dso_load_by_bus_kw, "passive DSO active load")
    other = _validated_bus_mapping(
        other_nonload_dso_injection_by_bus_kw,
        "other nonload DSO active injection",
    )
    buses = sort!(unique!(vcat(
        collect(keys(passive)),
        absolute.bus_ids,
        collect(keys(other)),
    )))
    result = Dict{Int,Float64}()
    for bus in buses
        pcc_export = sum(
            absolute.p_pcc_abs_kw[index]
            for index in eachindex(absolute.bus_ids)
            if absolute.bus_ids[index] == bus;
            init=0.0,
        )
        result[bus] = get(passive, bus, 0.0) - pcc_export - get(other, bus, 0.0)
    end
    return result
end

"Assemble q_net without ever folding passive DSO reactive load into Q_PCC."
function assemble_bus_net_reactive_demand_kvar(
    passive_dso_load_by_bus_kvar,
    absolute::AbsolutePCCInjection;
    other_nonload_dso_injection_by_bus_kvar=Dict{Int,Float64}(),
)
    passive = _validated_bus_mapping(passive_dso_load_by_bus_kvar, "passive DSO reactive load")
    other = _validated_bus_mapping(
        other_nonload_dso_injection_by_bus_kvar,
        "other nonload DSO reactive injection",
    )
    buses = sort!(unique!(vcat(
        collect(keys(passive)),
        absolute.bus_ids,
        collect(keys(other)),
    )))
    result = Dict{Int,Float64}()
    for bus in buses
        pcc_export = sum(
            absolute.q_pcc_kvar[index]
            for index in eachindex(absolute.bus_ids)
            if absolute.bus_ids[index] == bus;
            init=0.0,
        )
        result[bus] = get(passive, bus, 0.0) - pcc_export - get(other, bus, 0.0)
    end
    return result
end

const AUDITED_PCC_TIMESTAMP = DateTime(2012, 10, 15, 13, 0, 0)
const AUDITED_REFERENCE_PV_CAPACITY_KW = 850.0
const AUDITED_REFERENCE_PV_FACTOR = 0.9149568739021162
const AUDITED_REFERENCE_PV_INJECTION_KW =
    AUDITED_REFERENCE_PV_CAPACITY_KW * AUDITED_REFERENCE_PV_FACTOR
const REFERENCE_PV_OWNERSHIP = :REFERENCE_PV_850_KW_IS_TVPP_OWNED
const REFERENCE_PV_CAPACITY_ACCOUNTING_STATUS =
    :REFERENCE_PV_CAPACITY_ACCOUNTING_REQUIRES_FINAL_HC_FORMULATION_DECISION
const BUS_13_CASE_LOAD_OWNERSHIP = :BUS_13_CASE_LOAD_IS_DSO_BACKGROUND
const BUS_30_CASE_LOAD_OWNERSHIP = :BUS_30_CASE_LOAD_IS_DSO_BACKGROUND

"Return the locked two-interface transform without changing the historical pilot API."
function audited_pilot_interface_transform()
    interfaces = [
        InterfaceDefinition(:PCC_13, 13, UNITY_POWER_FACTOR),
        InterfaceDefinition(:PCC_30, 30, UNITY_POWER_FACTOR),
    ]
    operating_point = InterfaceOperatingPoint(
        AUDITED_PCC_TIMESTAMP,
        interfaces,
        [AUDITED_REFERENCE_PV_INJECTION_KW, 0.0],
    )
    return InterfaceCoordinateTransform(operating_point)
end
