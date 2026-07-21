struct S0UnconstrainedBranchResult
    branch_id::Int
    from_bus::Int
    to_bus::Int
    active_power_kw::Float64
    reactive_power_kvar::Float64
    apparent_power_kva::Float64
    current_pu::Float64
    current_a::Float64
end

struct S0UnconstrainedResult
    root_voltage_pu::Float64
    load_multiplier::Float64
    converged::Bool
    iterations::Int
    voltage_pu::Vector{ComplexF64}
    voltage_magnitudes_pu::Vector{Float64}
    branches::Vector{S0UnconstrainedBranchResult}
    total_active_load_kw::Float64
    total_reactive_load_kvar::Float64
    substation_active_power_kw::Float64
    substation_reactive_power_kvar::Float64
    active_losses_kw::Float64
    reactive_losses_kvar::Float64
    active_balance_residual_kw::Float64
    reactive_balance_residual_kvar::Float64
    maximum_voltage_equation_residual_pu::Float64
    maximum_kcl_residual_pu::Float64
    final_fixed_point_update_pu::Float64
    pv_capacity_kw::Float64
    ev_load_kw::Float64
    bess_charge_kw::Float64
    bess_discharge_kw::Float64
    voltage_limits_applied::Bool
    thermal_limits_applied::Bool
end

struct _S0UnconstrainedTopology
    root_bus::Int
    parent_bus::Vector{Int}
    parent_branch::Vector{Int}
    children::Vector{Vector{Int}}
    order::Vector{Int}
    branch_from::Vector{Int}
    branch_to::Vector{Int}
end

function _s0_unconstrained_topology(buses, branches; root_bus::Int=1)
    check_radial_network(buses, branches)
    bus_ids = sort([bus.id for bus in buses])
    branch_ids = sort([branch.id for branch in branches])
    bus_ids == collect(1:length(buses)) || throw(ArgumentError("S0 AC bus ids must be contiguous"))
    branch_ids == collect(1:length(branches)) || throw(ArgumentError("S0 AC branch ids must be contiguous"))

    adjacency = [Tuple{Int,Int}[] for _ in buses]
    branch_from = zeros(Int, length(branches))
    branch_to = zeros(Int, length(branches))
    for branch in branches
        push!(adjacency[branch.from_bus], (branch.to_bus, branch.id))
        push!(adjacency[branch.to_bus], (branch.from_bus, branch.id))
    end

    parent_bus = zeros(Int, length(buses))
    parent_branch = zeros(Int, length(buses))
    children = [Int[] for _ in buses]
    order = Int[]
    visited = falses(length(buses))
    visited[root_bus] = true
    queue = [root_bus]
    head = 1
    while head <= length(queue)
        bus = queue[head]
        head += 1
        push!(order, bus)
        for (neighbor, branch_id) in sort(adjacency[bus]; by=first)
            visited[neighbor] && continue
            visited[neighbor] = true
            parent_bus[neighbor] = bus
            parent_branch[neighbor] = branch_id
            branch_from[branch_id] = bus
            branch_to[branch_id] = neighbor
            push!(children[bus], neighbor)
            push!(queue, neighbor)
        end
    end
    all(visited) || throw(ArgumentError("S0 AC network is disconnected"))
    return _S0UnconstrainedTopology(
        root_bus,
        parent_bus,
        parent_branch,
        children,
        order,
        branch_from,
        branch_to,
    )
end

function _s0_unconstrained_branch_currents(
    topology::_S0UnconstrainedTopology,
    voltage_pu::Vector{ComplexF64},
    load_power_pu::Vector{ComplexF64},
)
    local_current_pu = zeros(ComplexF64, length(voltage_pu))
    for bus in topology.order
        bus == topology.root_bus && continue
        abs(voltage_pu[bus]) > 1e-10 || return nothing
        local_current_pu[bus] = conj(load_power_pu[bus] / voltage_pu[bus])
    end

    accumulated_current_pu = copy(local_current_pu)
    branch_current_pu = zeros(ComplexF64, length(topology.branch_from))
    for bus in reverse(topology.order)
        bus == topology.root_bus && continue
        branch_id = topology.parent_branch[bus]
        branch_current_pu[branch_id] = accumulated_current_pu[bus]
        accumulated_current_pu[topology.parent_bus[bus]] += branch_current_pu[branch_id]
    end
    return branch_current_pu, local_current_pu
end

function _s0_unconstrained_forward_voltage(
    topology::_S0UnconstrainedTopology,
    impedance_pu::Vector{ComplexF64},
    branch_current_pu::Vector{ComplexF64},
    root_voltage_pu::Float64,
)
    voltage_pu = fill(complex(root_voltage_pu, 0.0), length(topology.parent_bus))
    for bus in topology.order
        bus == topology.root_bus && continue
        branch_id = topology.parent_branch[bus]
        voltage_pu[bus] = voltage_pu[topology.parent_bus[bus]] -
                          impedance_pu[branch_id] * branch_current_pu[branch_id]
    end
    return voltage_pu
end

"""
Solve the zero-DER IEEE 33-bus snapshot with an exact radial AC backward/forward sweep.

This calculation has no voltage band, branch-current bound, apparent-power rating,
transformer rating, export policy, or loss cap. The only fixed voltage is the ideal
root-source magnitude requested by `root_voltage_pu`.
"""
function solve_s0_unconstrained_snapshot(
    load_multiplier::Real,
    root_voltage_pu::Real;
    tolerance_pu::Real=1e-12,
    maximum_iterations::Integer=2000,
    damping::Real=0.70,
)
    multiplier = Float64(load_multiplier)
    root_voltage = Float64(root_voltage_pu)
    isfinite(multiplier) && multiplier >= 0.0 || throw(ArgumentError("load multiplier must be finite and nonnegative"))
    isfinite(root_voltage) && root_voltage > 0.0 || throw(ArgumentError("root voltage must be finite and positive"))
    0.0 < damping <= 1.0 || throw(ArgumentError("damping must lie in (0, 1]"))
    tolerance_pu >= 0.0 || throw(ArgumentError("power-flow tolerance must be nonnegative"))
    maximum_iterations > 0 || throw(ArgumentError("maximum iterations must be positive"))

    buses, branches = build_ieee33_network()
    topology = _s0_unconstrained_topology(buses, branches; root_bus=1)
    base_mva = 10.0
    base_power_kw = base_mva * 1000.0
    bus_by_id = Dict(bus.id => bus for bus in buses)
    branch_by_id = Dict(branch.id => branch for branch in branches)
    load_power_pu = zeros(ComplexF64, length(buses))
    for bus in buses
        load_power_pu[bus.id] = complex(bus.pd_kw, bus.qd_kvar) * multiplier / base_power_kw
    end

    impedance_pu = zeros(ComplexF64, length(branches))
    for branch_id in eachindex(impedance_pu)
        branch = branch_by_id[branch_id]
        from_bus = topology.branch_from[branch_id]
        zbase_ohm = bus_by_id[from_bus].base_kv^2 / base_mva
        impedance_pu[branch_id] = complex(branch.r_ohm, branch.x_ohm) / zbase_ohm
    end

    voltage_pu = fill(complex(root_voltage, 0.0), length(buses))
    converged = false
    iterations = 0
    final_update = Inf
    for iteration in 1:Int(maximum_iterations)
        iterations = iteration
        currents = _s0_unconstrained_branch_currents(topology, voltage_pu, load_power_pu)
        currents === nothing && break
        branch_current_pu, _ = currents
        fixed_point_voltage = _s0_unconstrained_forward_voltage(
            topology,
            impedance_pu,
            branch_current_pu,
            root_voltage,
        )
        final_update = maximum(abs.(fixed_point_voltage .- voltage_pu))
        voltage_pu .= Float64(damping) .* fixed_point_voltage .+
                      (1.0 - Float64(damping)) .* voltage_pu
        voltage_pu[topology.root_bus] = complex(root_voltage, 0.0)
        if final_update <= Float64(tolerance_pu)
            voltage_pu .= fixed_point_voltage
            converged = true
            break
        end
    end

    converged || return S0UnconstrainedResult(
        root_voltage, multiplier, false, iterations, voltage_pu, abs.(voltage_pu),
        S0UnconstrainedBranchResult[], NaN, NaN, NaN, NaN, NaN, NaN, NaN, NaN,
        NaN, NaN, final_update, 0.0, 0.0, 0.0, 0.0, false, false,
    )

    branch_current_pu, local_current_pu = something(
        _s0_unconstrained_branch_currents(topology, voltage_pu, load_power_pu),
    )
    fixed_point_voltage = _s0_unconstrained_forward_voltage(
        topology,
        impedance_pu,
        branch_current_pu,
        root_voltage,
    )
    maximum_voltage_residual = maximum(abs.(fixed_point_voltage .- voltage_pu))
    final_update = maximum_voltage_residual

    branch_results = S0UnconstrainedBranchResult[]
    active_losses_kw = 0.0
    reactive_losses_kvar = 0.0
    for branch_id in eachindex(branch_current_pu)
        from_bus = topology.branch_from[branch_id]
        to_bus = topology.branch_to[branch_id]
        sending_power_kva = voltage_pu[from_bus] * conj(branch_current_pu[branch_id]) * base_power_kw
        branch_loss_kva = impedance_pu[branch_id] * abs2(branch_current_pu[branch_id]) * base_power_kw
        active_losses_kw += real(branch_loss_kva)
        reactive_losses_kvar += imag(branch_loss_kva)
        base_current_a = base_mva * 1e6 / (sqrt(3.0) * bus_by_id[from_bus].base_kv * 1e3)
        push!(branch_results, S0UnconstrainedBranchResult(
            branch_id,
            from_bus,
            to_bus,
            real(sending_power_kva),
            imag(sending_power_kva),
            abs(sending_power_kva),
            abs(branch_current_pu[branch_id]),
            abs(branch_current_pu[branch_id]) * base_current_a,
        ))
    end

    root_branch_ids = [topology.parent_branch[child] for child in topology.children[topology.root_bus]]
    substation_active_power_kw = sum(branch_results[id].active_power_kw for id in root_branch_ids)
    substation_reactive_power_kvar = sum(branch_results[id].reactive_power_kvar for id in root_branch_ids)
    total_active_load_kw = sum(real, load_power_pu) * base_power_kw
    total_reactive_load_kvar = sum(imag, load_power_pu) * base_power_kw
    active_balance_residual_kw = substation_active_power_kw - total_active_load_kw - active_losses_kw
    reactive_balance_residual_kvar = substation_reactive_power_kvar - total_reactive_load_kvar - reactive_losses_kvar

    maximum_kcl_residual_pu = 0.0
    for bus in topology.order
        bus == topology.root_bus && continue
        incoming = branch_current_pu[topology.parent_branch[bus]]
        outgoing = sum(
            branch_current_pu[topology.parent_branch[child]]
            for child in topology.children[bus];
            init=0.0 + 0.0im,
        )
        maximum_kcl_residual_pu = max(
            maximum_kcl_residual_pu,
            abs(incoming - local_current_pu[bus] - outgoing),
        )
    end

    return S0UnconstrainedResult(
        root_voltage,
        multiplier,
        true,
        iterations,
        voltage_pu,
        abs.(voltage_pu),
        branch_results,
        total_active_load_kw,
        total_reactive_load_kvar,
        substation_active_power_kw,
        substation_reactive_power_kvar,
        active_losses_kw,
        reactive_losses_kvar,
        active_balance_residual_kw,
        reactive_balance_residual_kvar,
        maximum_voltage_residual,
        maximum_kcl_residual_pu,
        final_update,
        0.0,
        0.0,
        0.0,
        0.0,
        false,
        false,
    )
end
