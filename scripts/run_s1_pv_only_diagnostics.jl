include(joinpath(@__DIR__, "..", "src", "CiroPVHC.jl"))

using .CiroPVHC
using JuMP

const DIAGNOSTIC_PV_LIMIT_KW = 20000.0
const CURTAILMENT_MODE = :none
const BINDING_TOL = 1e-4
const SOC_GAP_TOL = 1e-6

function build_diagnostic_case(; pv_limit_kw::Float64=DIAGNOSTIC_PV_LIMIT_KW)
    data = build_case33_data()
    pv_units = [PVUnit(pv.id, pv.bus, pv_limit_kw, pv_limit_kw) for pv in data.pv_units]

    return CaseData(
        data.buses,
        data.branches,
        pv_units,
        data.evcs_units,
        data.bess_units,
        data.doe,
        data.timeseries,
        data.base_mva,
        data.vmin_pu,
        data.vmax_pu,
    )
end

function round5(x)
    return round(x; digits=5)
end

function voltage_extrema(data::CaseData, network_vars)
    min_voltage = Inf
    max_voltage = -Inf
    min_bus = 0
    max_bus = 0
    min_t = 0
    max_t = 0

    for bus in data.buses, t in 1:data.timeseries.T
        voltage = sqrt(max(0.0, value(network_vars.v[bus.id, t])))
        if voltage < min_voltage
            min_voltage = voltage
            min_bus = bus.id
            min_t = t
        end
        if voltage > max_voltage
            max_voltage = voltage
            max_bus = bus.id
            max_t = t
        end
    end

    return min_voltage, min_bus, min_t, max_voltage, max_bus, max_t
end

function pv_capacity_by_unit(data::CaseData, pv_vars)
    return Dict(pv.id => Float64(value(pv_vars.capacity_kw[pv.id])) for pv in data.pv_units)
end

function total_pv_injection_kw(data::CaseData, pv_vars, t::Int)
    return sum(value(pv_vars.injection_kw[pv.id, t]) for pv in data.pv_units)
end

function load_totals(data::CaseData, t::Int)
    multiplier = data.timeseries.load_multiplier[t]
    return (
        sum(bus.pd_kw * multiplier for bus in data.buses),
        sum(bus.qd_kvar * multiplier for bus in data.buses),
    )
end

function root_power_kw(data::CaseData, network_vars, t::Int)
    base_kw = data.base_mva * 1000.0
    root = network_vars.topology.root_bus
    outgoing = network_vars.topology.outgoing_branches[root]
    p_kw = sum(value(network_vars.Pij[branch_id, t]) for branch_id in outgoing) * base_kw
    q_kvar = sum(value(network_vars.Qij[branch_id, t]) for branch_id in outgoing) * base_kw
    return p_kw, q_kvar
end

function voltage_by_bus(data::CaseData, network_vars, t::Int)
    return [(bus.id, sqrt(max(0.0, value(network_vars.v[bus.id, t])))) for bus in data.buses]
end

function branch_rows(data::CaseData, network_vars, t::Int)
    base_kw = data.base_mva * 1000.0
    rows = NamedTuple[]

    for branch in data.branches
        i = network_vars.topology.from_bus[branch.id]
        j = network_vars.topology.to_bus[branch.id]
        p_pu = value(network_vars.Pij[branch.id, t])
        q_pu = value(network_vars.Qij[branch.id, t])
        ell = value(network_vars.ell[branch.id, t])
        v_i = value(network_vars.v[i, t])
        soc_gap = p_pu^2 + q_pu^2 - v_i * ell
        push!(
            rows,
            (
                id=branch.id,
                from=i,
                to=j,
                p_kw=p_pu * base_kw,
                q_kvar=q_pu * base_kw,
                ell=ell,
                soc_gap=soc_gap,
            ),
        )
    end

    return rows
end

function classify_result(data::CaseData, total_capacity_kw::Float64, voltage_min::Float64, voltage_max::Float64)
    candidate_limit_kw = sum(min(pv.pmax_kw, pv.smax_kva) for pv in data.pv_units)
    candidate_cap_limited = isapprox(total_capacity_kw, candidate_limit_kw; atol=1e-3)
    voltage_limited =
        isapprox(voltage_min, data.vmin_pu; atol=BINDING_TOL) ||
        isapprox(voltage_max, data.vmax_pu; atol=BINDING_TOL)

    if candidate_cap_limited
        return "candidate-cap-limited"
    elseif voltage_limited
        return "voltage-limited"
    else
        return "not candidate-cap-limited; active network limiter not identified"
    end
end

function print_binding_time_diagnostics(data::CaseData, pv_vars, network_vars, t::Int)
    total_load_kw, total_load_kvar = load_totals(data, t)
    total_pv_kw = total_pv_injection_kw(data, pv_vars, t)
    substation_p_kw, substation_q_kvar = root_power_kw(data, network_vars, t)
    rows = branch_rows(data, network_vars, t)
    reverse_rows = [row for row in rows if row.p_kw < -1e-3]
    soc_gaps = [row.soc_gap for row in rows]
    max_positive_gap = maximum(soc_gaps)
    most_negative_gap = minimum(soc_gaps)
    max_abs_gap = maximum(abs.(soc_gaps))

    println("")
    println("binding_time_index: $(t)")
    println("load_multiplier: $(round5(data.timeseries.load_multiplier[t]))")
    println("pv_profile: $(round5(data.timeseries.pv_profile[t]))")
    println("total_load_kw: $(round(total_load_kw; digits=3))")
    println("total_load_kvar: $(round(total_load_kvar; digits=3))")
    println("total_pv_injection_kw: $(round(total_pv_kw; digits=3))")
    println("substation_active_power_kw: $(round(substation_p_kw; digits=3))")
    println("substation_reactive_power_kvar: $(round(substation_q_kvar; digits=3))")
    println("substation_power_note: positive active power means import from the substation; negative means reverse export toward the substation.")

    println("")
    println("voltage_by_bus_pu:")
    for (bus_id, voltage) in voltage_by_bus(data, network_vars, t)
        println("  bus $(bus_id): $(round5(voltage))")
    end

    println("")
    println("branch_flows_and_soc_gaps:")
    println("  id from->to P_kW Q_kvar ell soc_gap")
    for row in rows
        println(
            "  $(row.id) $(row.from)->$(row.to) " *
            "$(round(row.p_kw; digits=3)) " *
            "$(round(row.q_kvar; digits=3)) " *
            "$(round(row.ell; digits=8)) " *
            "$(round(row.soc_gap; digits=8))"
        )
    end

    println("")
    println("reverse_power_flow_branches: $(isempty(reverse_rows) ? "none" : join(["$(row.id):$(row.from)->$(row.to)" for row in reverse_rows], ", "))")
    println("max_positive_soc_gap: $(round(max_positive_gap; digits=10))")
    println("most_negative_soc_gap: $(round(most_negative_gap; digits=10))")
    println("max_abs_soc_gap: $(round(max_abs_gap; digits=10))")
    println("soc_gap_note: gap is P^2 + Q^2 - v_i * ell; positive values indicate SOC violation, negative values indicate slack.")
    println("soc_gap_check: $(max_positive_gap <= SOC_GAP_TOL ? "no positive SOC violation above tolerance" : "positive SOC violation above tolerance")")
    println("power_flow_check: $(substation_p_kw < -1e-3 ? "downstream PV creates reverse active power flow at the substation" : "downstream PV reduces import but does not reverse the substation active flow")")
end

data = build_diagnostic_case()
model, pv_vars, network_vars = build_s1_pv_only_model(data; curtailment_mode=CURTAILMENT_MODE)
optimize!(model)

termination = string(termination_status(model))
println("CiroPVHC S1 PV-only physical diagnostics")
println("diagnostic_pv_limit_kw_per_unit: $(DIAGNOSTIC_PV_LIMIT_KW)")
println("curtailment_mode: $(CURTAILMENT_MODE)")
println("line_rating_note: MATPOWER case33bw has no specified active-branch thermal ratings; line apparent-power limits are skipped.")
println("termination_status: $(termination)")

if has_values(model)
    capacities = pv_capacity_by_unit(data, pv_vars)
    total_capacity_kw = sum(values(capacities))
    voltage_min, min_bus, min_t, voltage_max, max_bus, max_t = voltage_extrema(data, network_vars)
    classification = classify_result(data, total_capacity_kw, voltage_min, voltage_max)

    println("objective_value: $(round(objective_value(model); digits=4))")
    println("total_pv_capacity_kw: $(round(total_capacity_kw; digits=4))")
    println("pv_candidate_buses_and_capacity_kw:")
    for pv in data.pv_units
        println("  PV$(pv.id) bus $(pv.bus): $(round(capacities[pv.id]; digits=4))")
    end
    println("voltage_min: $(round5(voltage_min))")
    println("voltage_min_location: bus $(min_bus), time $(min_t)")
    println("voltage_max: $(round5(voltage_max))")
    println("voltage_max_location: bus $(max_bus), time $(max_t)")
    println("voltage_limit_check: lower_bound_binding=$(isapprox(voltage_min, data.vmin_pu; atol=BINDING_TOL)), upper_bound_binding=$(isapprox(voltage_max, data.vmax_pu; atol=BINDING_TOL))")
    println("result_classification: $(classification)")

    binding_times = unique([min_t, max_t])
    for t in binding_times
        print_binding_time_diagnostics(data, pv_vars, network_vars, t)
    end

    println("")
    println("voltage_rise_check: $(voltage_max > 1.0 + BINDING_TOL ? "voltage rise is present under high PV injection" : "no material voltage rise detected")")
    println("network_limit_check: $(classification)")
else
    println("No primal solution available; physical diagnostics unavailable.")
end
