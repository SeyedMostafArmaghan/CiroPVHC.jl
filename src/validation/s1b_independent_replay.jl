"""
Detailed result from an independent radial AC replay of one S1-B interval.

The replay is deliberately implemented without JuMP expressions, optimization
variables, or the S0 residual/power-flow helpers. Power residuals are in per
unit, voltage-drop and current-power residuals are in squared per unit, and the
phasor residual is in per unit voltage.
"""
struct S1BIndependentReplayState
    converged::Bool
    iterations::Int
    voltage_complex_pu::Vector{ComplexF64}
    voltage_pu::Vector{Float64}
    branch_p_pu::Vector{Float64}
    branch_q_pu::Vector{Float64}
    branch_ell_pu2::Vector{Float64}
    substation_p_kw::Float64
    substation_q_kvar::Float64
    active_losses_kw::Float64
    reactive_losses_kvar::Float64
    maximum_equation_residual::Float64
    maximum_scaled_residual::Float64
    active_balance_residual_pu::Float64
    active_balance_scaled_residual::Float64
    active_balance_bus::Int
    reactive_balance_residual_pu::Float64
    reactive_balance_scaled_residual::Float64
    reactive_balance_bus::Int
    voltage_drop_residual_pu2::Float64
    voltage_drop_scaled_residual::Float64
    voltage_drop_branch::Int
    current_power_residual_pu2::Float64
    current_power_scaled_residual::Float64
    current_power_branch::Int
    phasor_residual_pu::Float64
    phasor_scaled_residual::Float64
    phasor_residual_branch::Int
    root_voltage_residual_pu::Float64
    minimum_voltage_pu::Float64
    minimum_voltage_bus::Int
    maximum_voltage_pu::Float64
    maximum_voltage_bus::Int
    voltage_limits_satisfied::Bool
    phasor_recoverable::Bool
end

struct _S1BReplayTopology
    root_bus::Int
    parent_bus::Vector{Int}
    parent_branch::Vector{Int}
    child_branches::Vector{Vector{Int}}
    order::Vector{Int}
    branch_from::Vector{Int}
    branch_to::Vector{Int}
end

function _s1b_replay_topology(buses, branches; root_bus::Int=1)
    bus_ids = sort([bus.id for bus in buses])
    branch_ids = sort([branch.id for branch in branches])
    bus_ids == collect(1:length(buses)) ||
        throw(ArgumentError("independent replay requires contiguous bus ids"))
    branch_ids == collect(1:length(branches)) ||
        throw(ArgumentError("independent replay requires contiguous branch ids"))
    length(branches) == length(buses) - 1 ||
        throw(ArgumentError("independent replay requires a radial feeder"))
    root_bus in bus_ids || throw(ArgumentError("independent replay root bus is absent"))

    adjacency = [Tuple{Int,Int}[] for _ in buses]
    for branch in branches
        branch.from_bus in bus_ids && branch.to_bus in bus_ids ||
            throw(ArgumentError("independent replay branch endpoint is absent"))
        push!(adjacency[branch.from_bus], (branch.to_bus, branch.id))
        push!(adjacency[branch.to_bus], (branch.from_bus, branch.id))
    end

    parent_bus = zeros(Int, length(buses))
    parent_branch = zeros(Int, length(buses))
    child_branches = [Int[] for _ in buses]
    branch_from = zeros(Int, length(branches))
    branch_to = zeros(Int, length(branches))
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
            if visited[neighbor]
                neighbor == parent_bus[bus] ||
                    throw(ArgumentError("independent replay detected a feeder cycle"))
                continue
            end
            visited[neighbor] = true
            parent_bus[neighbor] = bus
            parent_branch[neighbor] = branch_id
            push!(child_branches[bus], branch_id)
            branch_from[branch_id] = bus
            branch_to[branch_id] = neighbor
            push!(queue, neighbor)
        end
    end
    all(visited) || throw(ArgumentError("independent replay feeder is disconnected"))
    return _S1BReplayTopology(
        root_bus, parent_bus, parent_branch, child_branches, order, branch_from, branch_to,
    )
end

_s1b_scaled_residual(residual, terms...) =
    abs(residual) / max(maximum(abs, terms), 1e-12)

function _s1b_failed_replay(bus_count::Int, branch_count::Int, iterations::Int, voltage)
    nan_branch = fill(NaN, branch_count)
    magnitudes = abs.(voltage)
    return S1BIndependentReplayState(
        false, iterations, voltage, magnitudes, nan_branch, nan_branch, nan_branch,
        NaN, NaN, NaN, NaN, Inf, Inf,
        Inf, Inf, 0, Inf, Inf, 0, Inf, Inf, 0, Inf, Inf, 0, Inf, Inf, 0,
        Inf, minimum(magnitudes), argmin(magnitudes), maximum(magnitudes),
        argmax(magnitudes), false, false,
    )
end

"""
    replay_s1b_interval(buses, branches, load_multiplier, pv_availability, capacities_kw; ...)

Solve and audit one balanced radial-feeder interval independently of the S1-B
optimization model. Positive `substation_p_kw` means import and negative means
upstream export. PV operates at unity power factor with no curtailment:
`P_pv(bus) = capacities_kw[bus] * pv_availability`.
"""
function replay_s1b_interval(
    buses,
    branches,
    load_multiplier::Real,
    pv_availability::Real,
    capacities_kw::AbstractDict{Int,<:Real};
    base_mva::Real=10.0,
    root_bus::Integer=1,
    root_voltage_pu::Real=1.0,
    vmin_pu::Real=0.90,
    vmax_pu::Real=1.05,
    tolerance_pu::Real=1e-12,
    voltage_tolerance_pu::Real=1e-5,
    residual_tolerance_pu::Real=1e-10,
    maximum_iterations::Integer=4000,
    damping::Real=0.70,
)
    load_scale = Float64(load_multiplier)
    pv_factor = Float64(pv_availability)
    base_power_kw = 1000.0 * Float64(base_mva)
    root_voltage = Float64(root_voltage_pu)
    isfinite(load_scale) && load_scale >= 0.0 ||
        throw(ArgumentError("load multiplier must be finite and nonnegative"))
    isfinite(pv_factor) && pv_factor >= 0.0 ||
        throw(ArgumentError("PV availability must be finite and nonnegative"))
    base_power_kw > 0.0 || throw(ArgumentError("base MVA must be positive"))
    root_voltage > 0.0 || throw(ArgumentError("root voltage must be positive"))
    0.0 < damping <= 1.0 || throw(ArgumentError("damping must lie in (0, 1]"))
    maximum_iterations > 0 || throw(ArgumentError("maximum iterations must be positive"))

    topology = _s1b_replay_topology(buses, branches; root_bus=Int(root_bus))
    bus_by_id = Dict(bus.id => bus for bus in buses)
    branch_by_id = Dict(branch.id => branch for branch in branches)
    net_demand_pu = zeros(ComplexF64, length(buses))
    for bus in buses
        pv_kw = Float64(get(capacities_kw, bus.id, 0.0)) * pv_factor
        net_demand_pu[bus.id] = complex(
            bus.pd_kw * load_scale - pv_kw,
            bus.qd_kvar * load_scale,
        ) / base_power_kw
    end

    impedance_pu = zeros(ComplexF64, length(branches))
    for branch_id in eachindex(branches)
        branch = branch_by_id[branch_id]
        from_bus = topology.branch_from[branch_id]
        zbase_ohm = bus_by_id[from_bus].base_kv^2 / Float64(base_mva)
        impedance_pu[branch_id] = complex(branch.r_ohm, branch.x_ohm) / zbase_ohm
    end

    voltage = fill(complex(root_voltage, 0.0), length(buses))
    branch_current = zeros(ComplexF64, length(branches))
    local_current = zeros(ComplexF64, length(buses))
    converged = false
    iterations = 0
    for iteration in 1:Int(maximum_iterations)
        iterations = iteration
        for bus in topology.order
            bus == topology.root_bus && continue
            abs(voltage[bus]) > 1e-10 ||
                return _s1b_failed_replay(length(buses), length(branches), iterations, voltage)
            local_current[bus] = conj(net_demand_pu[bus] / voltage[bus])
        end
        accumulated = copy(local_current)
        for bus in reverse(topology.order)
            bus == topology.root_bus && continue
            branch_id = topology.parent_branch[bus]
            branch_current[branch_id] = accumulated[bus]
            accumulated[topology.parent_bus[bus]] += branch_current[branch_id]
        end
        fixed_voltage = fill(complex(root_voltage, 0.0), length(buses))
        for bus in topology.order
            bus == topology.root_bus && continue
            branch_id = topology.parent_branch[bus]
            fixed_voltage[bus] = fixed_voltage[topology.parent_bus[bus]] -
                                 impedance_pu[branch_id] * branch_current[branch_id]
        end
        update = maximum(abs.(fixed_voltage .- voltage))
        isfinite(update) ||
            return _s1b_failed_replay(length(buses), length(branches), iterations, voltage)
        voltage .= damping .* fixed_voltage .+ (1.0 - damping) .* voltage
        voltage[topology.root_bus] = complex(root_voltage, 0.0)
        if update <= tolerance_pu
            voltage .= fixed_voltage
            converged = true
            break
        end
    end
    converged || return _s1b_failed_replay(length(buses), length(branches), iterations, voltage)

    # Recompute currents at the converged phasors instead of retaining an
    # iteration-side value. This makes every reported equation check explicit.
    fill!(local_current, 0.0 + 0.0im)
    for bus in topology.order
        bus == topology.root_bus && continue
        local_current[bus] = conj(net_demand_pu[bus] / voltage[bus])
    end
    accumulated = copy(local_current)
    for bus in reverse(topology.order)
        bus == topology.root_bus && continue
        branch_id = topology.parent_branch[bus]
        branch_current[branch_id] = accumulated[bus]
        accumulated[topology.parent_bus[bus]] += branch_current[branch_id]
    end

    branch_p = zeros(length(branches))
    branch_q = zeros(length(branches))
    branch_ell = abs2.(branch_current)
    for branch_id in eachindex(branches)
        sending_bus = topology.branch_from[branch_id]
        sending_power = voltage[sending_bus] * conj(branch_current[branch_id])
        branch_p[branch_id] = real(sending_power)
        branch_q[branch_id] = imag(sending_power)
    end

    p_abs, p_scaled, p_bus = -Inf, -Inf, 0
    q_abs, q_scaled, q_bus = -Inf, -Inf, 0
    for bus in topology.order
        bus == topology.root_bus && continue
        incoming = topology.parent_branch[bus]
        child_p = sum(branch_p[branch] for branch in topology.child_branches[bus]; init=0.0)
        child_q = sum(branch_q[branch] for branch in topology.child_branches[bus]; init=0.0)
        p_after_loss = branch_p[incoming] - real(impedance_pu[incoming]) * branch_ell[incoming]
        q_after_loss = branch_q[incoming] - imag(impedance_pu[incoming]) * branch_ell[incoming]
        p_residual = p_after_loss - child_p - real(net_demand_pu[bus])
        q_residual = q_after_loss - child_q - imag(net_demand_pu[bus])
        p_relative = _s1b_scaled_residual(
            p_residual, p_after_loss, child_p, real(net_demand_pu[bus]),
        )
        q_relative = _s1b_scaled_residual(
            q_residual, q_after_loss, child_q, imag(net_demand_pu[bus]),
        )
        if abs(p_residual) > p_abs
            p_abs, p_scaled, p_bus = abs(p_residual), p_relative, bus
        end
        if abs(q_residual) > q_abs
            q_abs, q_scaled, q_bus = abs(q_residual), q_relative, bus
        end
    end

    vd_abs, vd_scaled, vd_branch = -Inf, -Inf, 0
    cp_abs, cp_scaled, cp_branch = -Inf, -Inf, 0
    ph_abs, ph_scaled, ph_branch = -Inf, -Inf, 0
    for branch_id in eachindex(branches)
        i = topology.branch_from[branch_id]
        j = topology.branch_to[branch_id]
        r = real(impedance_pu[branch_id])
        x = imag(impedance_pu[branch_id])
        vi, vj = abs2(voltage[i]), abs2(voltage[j])
        p, q, ell = branch_p[branch_id], branch_q[branch_id], branch_ell[branch_id]
        drop = vi - 2.0 * (r * p + x * q) + (r^2 + x^2) * ell
        vd_residual = vj - drop
        cp_residual = p^2 + q^2 - vi * ell
        recovered_vj = voltage[i] - impedance_pu[branch_id] * conj(complex(p, q) / voltage[i])
        ph_residual = voltage[j] - recovered_vj
        vd_relative = _s1b_scaled_residual(
            vd_residual, vj, vi, 2.0 * (r * p + x * q), (r^2 + x^2) * ell,
        )
        cp_relative = _s1b_scaled_residual(cp_residual, p^2 + q^2, vi * ell)
        ph_relative = _s1b_scaled_residual(
            ph_residual, voltage[j], voltage[i], impedance_pu[branch_id] * branch_current[branch_id],
        )
        if abs(vd_residual) > vd_abs
            vd_abs, vd_scaled, vd_branch = abs(vd_residual), vd_relative, branch_id
        end
        if abs(cp_residual) > cp_abs
            cp_abs, cp_scaled, cp_branch = abs(cp_residual), cp_relative, branch_id
        end
        if abs(ph_residual) > ph_abs
            ph_abs, ph_scaled, ph_branch = abs(ph_residual), ph_relative, branch_id
        end
    end

    root_residual = abs(voltage[topology.root_bus] - complex(root_voltage, 0.0))
    voltage_magnitudes = abs.(voltage)
    minimum_voltage, minimum_bus = findmin(voltage_magnitudes)
    maximum_voltage, maximum_bus = findmax(voltage_magnitudes)
    voltage_limits_satisfied = minimum_voltage >= Float64(vmin_pu) - voltage_tolerance_pu &&
                               maximum_voltage <= Float64(vmax_pu) + voltage_tolerance_pu
    maximum_absolute = maximum((p_abs, q_abs, vd_abs, cp_abs, ph_abs, root_residual))
    maximum_scaled = maximum((p_scaled, q_scaled, vd_scaled, cp_scaled, ph_scaled))
    phasor_recoverable = all(isfinite, voltage) && minimum_voltage > 1e-10 &&
                           ph_abs <= residual_tolerance_pu
    root_branches = topology.child_branches[topology.root_bus]
    substation_p = sum(branch_p[root_branches]) * base_power_kw
    substation_q = sum(branch_q[root_branches]) * base_power_kw
    active_losses = sum(real.(impedance_pu) .* branch_ell) * base_power_kw
    reactive_losses = sum(imag.(impedance_pu) .* branch_ell) * base_power_kw

    return S1BIndependentReplayState(
        true, iterations, voltage, voltage_magnitudes, branch_p, branch_q, branch_ell,
        substation_p, substation_q, active_losses, reactive_losses,
        maximum_absolute, maximum_scaled,
        p_abs, p_scaled, p_bus, q_abs, q_scaled, q_bus,
        vd_abs, vd_scaled, vd_branch, cp_abs, cp_scaled, cp_branch,
        ph_abs, ph_scaled, ph_branch, root_residual,
        minimum_voltage, minimum_bus, maximum_voltage, maximum_bus,
        voltage_limits_satisfied, phasor_recoverable,
    )
end
