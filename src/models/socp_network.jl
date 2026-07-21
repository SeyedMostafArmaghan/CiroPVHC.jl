using JuMP

struct RadialTopology
    root_bus::Int
    bus_ids::Vector{Int}
    branch_ids::Vector{Int}
    from_bus::Dict{Int,Int}
    to_bus::Dict{Int,Int}
    incoming_branch::Dict{Int,Int}
    outgoing_branches::Dict{Int,Vector{Int}}
end

struct SOCPNetworkVariables
    Pij::Any
    Qij::Any
    v::Any
    ell::Any
    topology::RadialTopology
    r_pu::Dict{Int,Float64}
    x_pu::Dict{Int,Float64}
    smax_pu::Dict{Int,Float64}
end

function _base_power_kw(data::CaseData)
    return data.base_mva * 1000.0
end

function _build_radial_topology(data::CaseData; root_bus::Int=1)
    check_radial_network(data.buses, data.branches)

    bus_ids = [bus.id for bus in data.buses]
    branch_ids = [branch.id for branch in data.branches]
    bus_id_set = Set(bus_ids)
    _require(root_bus in bus_id_set, "root bus must exist")

    adjacency = Dict(id => Tuple{Int,Int}[] for id in bus_ids)
    for branch in data.branches
        push!(adjacency[branch.from_bus], (branch.to_bus, branch.id))
        push!(adjacency[branch.to_bus], (branch.from_bus, branch.id))
    end

    from_bus = Dict{Int,Int}()
    to_bus = Dict{Int,Int}()
    incoming_branch = Dict{Int,Int}()
    outgoing_branches = Dict(id => Int[] for id in bus_ids)

    visited = Set([root_bus])
    queue = [root_bus]
    head = 1

    while head <= length(queue)
        current = queue[head]
        head += 1

        for (neighbor, branch_id) in adjacency[current]
            if neighbor in visited
                continue
            end

            push!(visited, neighbor)
            push!(queue, neighbor)
            from_bus[branch_id] = current
            to_bus[branch_id] = neighbor
            incoming_branch[neighbor] = branch_id
            push!(outgoing_branches[current], branch_id)
        end
    end

    _require(length(visited) == length(bus_ids), "network must be connected from the root bus")

    return RadialTopology(
        root_bus,
        bus_ids,
        branch_ids,
        from_bus,
        to_bus,
        incoming_branch,
        outgoing_branches,
    )
end

function _branch_pu_parameters(data::CaseData, topology::RadialTopology)
    bus_by_id = Dict(bus.id => bus for bus in data.buses)
    branch_by_id = Dict(branch.id => branch for branch in data.branches)

    r_pu = Dict{Int,Float64}()
    x_pu = Dict{Int,Float64}()
    smax_pu = Dict{Int,Float64}()

    for branch_id in topology.branch_ids
        branch = branch_by_id[branch_id]
        base_kv = bus_by_id[topology.from_bus[branch_id]].base_kv
        zbase_ohm = base_kv^2 / data.base_mva

        r_pu[branch_id] = branch.r_ohm / zbase_ohm
        x_pu[branch_id] = branch.x_ohm / zbase_ohm
        smax_pu[branch_id] = branch.smax_kva / _base_power_kw(data)
    end

    return r_pu, x_pu, smax_pu
end

function _series_value_by_bus(series_by_bus::Dict, bus_id::Int, t::Int)
    values = get(series_by_bus, bus_id, nothing)
    return values === nothing ? 0.0 : values[t]
end

function add_socp_branch_flow_constraints!(
    model::JuMP.Model,
    data::CaseData,
    p_injection_by_bus_kw::Dict;
    q_injection_by_bus_kvar::Union{Nothing,Dict}=nothing,
    p_load_adder_by_bus_kw::Union{Nothing,Dict}=nothing,
    q_load_adder_by_bus_kvar::Union{Nothing,Dict}=nothing,
    root_bus::Int=1,
    root_voltage_pu::Real=1.0,
    load_multiplier_by_time::Union{Nothing,AbstractVector}=nothing,
)
    topology = _build_radial_topology(data; root_bus=root_bus)
    r_pu, x_pu, smax_pu = _branch_pu_parameters(data, topology)

    times = 1:data.timeseries.T
    bus_by_id = Dict(bus.id => bus for bus in data.buses)
    base_power_kw = _base_power_kw(data)
    root_voltage = Float64(root_voltage_pu)
    _require(isfinite(root_voltage), "root voltage must be finite")
    _require(data.vmin_pu <= root_voltage <= data.vmax_pu, "root voltage must lie inside model voltage bounds")
    if load_multiplier_by_time !== nothing
        _require(length(load_multiplier_by_time) == data.timeseries.T, "load-multiplier override length must match T")
    end

    if q_injection_by_bus_kvar === nothing
        q_injection_by_bus_kvar = Dict(
            bus.id => [JuMP.AffExpr(0.0) for _ in times]
            for bus in data.buses
        )
    end
    if p_load_adder_by_bus_kw === nothing
        p_load_adder_by_bus_kw = Dict(bus.id => zeros(Float64, data.timeseries.T) for bus in data.buses)
    end
    if q_load_adder_by_bus_kvar === nothing
        q_load_adder_by_bus_kvar = Dict(bus.id => zeros(Float64, data.timeseries.T) for bus in data.buses)
    end

    @variable(model, Pij[branch_id in topology.branch_ids, t in times], base_name = "Pij")
    @variable(model, Qij[branch_id in topology.branch_ids, t in times], base_name = "Qij")
    @variable(
        model,
        data.vmin_pu^2 <= v[bus_id in topology.bus_ids, t in times] <= data.vmax_pu^2,
        base_name = "v"
    )
    @variable(model, ell[branch_id in topology.branch_ids, t in times] >= 0, base_name = "ell")

    for t in times
        @constraint(model, v[topology.root_bus, t] == root_voltage^2)
    end

    for branch_id in topology.branch_ids, t in times
        i = topology.from_bus[branch_id]
        j = topology.to_bus[branch_id]
        r = r_pu[branch_id]
        x = x_pu[branch_id]

        @constraint(
            model,
            v[j, t] == v[i, t] - 2.0 * (r * Pij[branch_id, t] + x * Qij[branch_id, t]) +
                       (r^2 + x^2) * ell[branch_id, t]
        )
        # In MATPOWER data, rateA = 0 means the thermal rating is missing.
        # Skip the apparent-power limit in that case instead of forcing zero flow.
        if smax_pu[branch_id] > 0.0
            @constraint(model, [smax_pu[branch_id], Pij[branch_id, t], Qij[branch_id, t]] in SecondOrderCone())
            # Paper-study assumption for synthetic line ratings: interpret the
            # same nominal apparent-power rating as an ampacity at 1.0 pu voltage.
            # This is not raw MATPOWER data; it prevents the relaxation from
            # creating artificial losses through unbounded current-squared ell.
            @constraint(model, ell[branch_id, t] <= smax_pu[branch_id]^2)
        end
        @constraint(model, [v[i, t] / 2.0, ell[branch_id, t], Pij[branch_id, t], Qij[branch_id, t]] in RotatedSecondOrderCone())
    end

    for bus_id in topology.bus_ids
        if bus_id == topology.root_bus
            continue
        end

        incoming = topology.incoming_branch[bus_id]
        child_branches = topology.outgoing_branches[bus_id]
        bus = bus_by_id[bus_id]

        for t in times
            child_p = isempty(child_branches) ? 0.0 : sum(Pij[child, t] for child in child_branches)
            child_q = isempty(child_branches) ? 0.0 : sum(Qij[child, t] for child in child_branches)

            load_multiplier = load_multiplier_by_time === nothing ?
                              data.timeseries.load_multiplier[t] : load_multiplier_by_time[t]
            p_load_kw = bus.pd_kw * load_multiplier +
                        _series_value_by_bus(p_load_adder_by_bus_kw, bus_id, t)
            q_load_kvar = bus.qd_kvar * load_multiplier +
                          _series_value_by_bus(q_load_adder_by_bus_kvar, bus_id, t)
            p_inj_kw = _series_value_by_bus(p_injection_by_bus_kw, bus_id, t)
            q_inj_kvar = _series_value_by_bus(q_injection_by_bus_kvar, bus_id, t)

            @constraint(
                model,
                Pij[incoming, t] - r_pu[incoming] * ell[incoming, t] - child_p ==
                (p_load_kw - p_inj_kw) / base_power_kw
            )
            @constraint(
                model,
                Qij[incoming, t] - x_pu[incoming] * ell[incoming, t] - child_q ==
                (q_load_kvar - q_inj_kvar) / base_power_kw
            )
        end
    end

    return SOCPNetworkVariables(Pij, Qij, v, ell, topology, r_pu, x_pu, smax_pu)
end
