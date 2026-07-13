include(joinpath(@__DIR__, "..", "src", "CiroPVHC.jl"))

using .CiroPVHC
using JuMP

const PAPER_VMIN_PU = 0.95
const PAPER_VMAX_PU = 1.05
const PAPER_SYNTHETIC_SMAX_KVA = 4000.0
const PAPER_PV_LIMIT_KW = 20000.0
const PAPER_ALPHA_CUR = 0.05
const BINDING_TOL = 1e-4

function root_power_kw(data::CaseData, network_vars, t::Int)
    base_kw = data.base_mva * 1000.0
    root = network_vars.topology.root_bus
    outgoing = network_vars.topology.outgoing_branches[root]
    return sum(value(network_vars.Pij[branch_id, t]) for branch_id in outgoing) * base_kw
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

function max_line_loading(data::CaseData, network_vars)
    constrained_branches = [branch for branch in data.branches if branch.smax_kva > 0.0]
    if isempty(constrained_branches)
        return NaN, 0, 0
    end

    best_loading = -Inf
    best_branch = 0
    best_t = 0
    for branch in constrained_branches, t in 1:data.timeseries.T
        loading = hypot(value(network_vars.Pij[branch.id, t]), value(network_vars.Qij[branch.id, t])) /
                  network_vars.smax_pu[branch.id]
        if loading > best_loading
            best_loading = loading
            best_branch = branch.id
            best_t = t
        end
    end

    return best_loading, best_branch, best_t
end

function soc_gap_extrema(data::CaseData, network_vars)
    max_positive_gap = -Inf
    most_negative_gap = Inf
    max_positive_branch = 0
    most_negative_branch = 0

    for branch in data.branches, t in 1:data.timeseries.T
        i = network_vars.topology.from_bus[branch.id]
        p = value(network_vars.Pij[branch.id, t])
        q = value(network_vars.Qij[branch.id, t])
        v_i = value(network_vars.v[i, t])
        ell = value(network_vars.ell[branch.id, t])
        gap = p^2 + q^2 - v_i * ell

        if gap > max_positive_gap
            max_positive_gap = gap
            max_positive_branch = branch.id
        end
        if gap < most_negative_gap
            most_negative_gap = gap
            most_negative_branch = branch.id
        end
    end

    return max_positive_gap, max_positive_branch, most_negative_gap, most_negative_branch
end

function total_available_energy_kwh(data::CaseData, pv_vars)
    return sum(
        value(pv_vars.available_kw[pv.id, t]) * data.timeseries.dt_hours
        for pv in data.pv_units
        for t in 1:data.timeseries.T;
        init=0.0,
    )
end

function total_curtailed_energy_kwh(data::CaseData, pv_vars)
    return sum(
        value(pv_vars.curtailment_kw[pv.id, t]) * data.timeseries.dt_hours
        for pv in data.pv_units
        for t in 1:data.timeseries.T;
        init=0.0,
    )
end

function print_binding_summary(;
    total_pv_capacity_kw,
    candidate_limit_kw,
    curtailment_percentage,
    p_sub_min_kw,
    voltage_min,
    voltage_max,
    line_loading,
)
    println("binding_constraints_summary:")
    println("  candidate_cap_binding: $(isapprox(total_pv_capacity_kw, candidate_limit_kw; atol=1e-3))")
    println("  no_export_binding: $(isapprox(p_sub_min_kw, 0.0; atol=1e-3))")
    println("  curtailment_budget_binding: $(isapprox(curtailment_percentage, 100.0 * PAPER_ALPHA_CUR; atol=1e-3))")
    println("  voltage_lower_binding: $(isapprox(voltage_min, PAPER_VMIN_PU; atol=BINDING_TOL))")
    println("  voltage_upper_binding: $(isapprox(voltage_max, PAPER_VMAX_PU; atol=BINDING_TOL))")
    println("  line_limit_binding: $(!isnan(line_loading) && isapprox(line_loading, 1.0; atol=BINDING_TOL))")
end

function print_zero_pv_base_feeder_check()
    zero_pv_data = build_s1_pv_only_paper_case(
        pv_limit_kw=0.0,
        synthetic_smax_kva=PAPER_SYNTHETIC_SMAX_KVA,
        vmin_pu=PAPER_VMIN_PU,
        vmax_pu=PAPER_VMAX_PU,
    )
    zero_pv_model, _, _, _ = solve_s1_pv_only_paper_model(zero_pv_data; alpha_cur=PAPER_ALPHA_CUR)
    zero_pv_status = string(termination_status(zero_pv_model))
    zero_pv_feasible = zero_pv_status in ("OPTIMAL", "ALMOST_OPTIMAL")
    println("zero_pv_base_feeder_check:")
    println("  termination_status: $(zero_pv_status)")
    println("  feasible_under_0.95_1.05: $(zero_pv_feasible)")
    println("  note: this check sets all PV candidate limits to zero while keeping the paper voltage bounds and synthetic line ratings.")
end

data = build_s1_pv_only_paper_case(
    pv_limit_kw=PAPER_PV_LIMIT_KW,
    synthetic_smax_kva=PAPER_SYNTHETIC_SMAX_KVA,
    vmin_pu=PAPER_VMIN_PU,
    vmax_pu=PAPER_VMAX_PU,
)
model, pv_vars, network_vars, policy = solve_s1_pv_only_paper_model(data; alpha_cur=PAPER_ALPHA_CUR)

termination = string(termination_status(model))

println("CiroPVHC S1 PV-only full-day feasibility/policy check")
println("benchmark_data: MATPOWER case33bw bus loads and branch impedances; raw MATPOWER branch ratings remain missing.")
println("paper_study_assumptions:")
println("  voltage_bounds_pu: [$(PAPER_VMIN_PU), $(PAPER_VMAX_PU)]")
println("  synthetic_active_branch_smax_kva: $(PAPER_SYNTHETIC_SMAX_KVA)")
println("  pv_candidate_limit_kw_per_unit: $(PAPER_PV_LIMIT_KW)")
println("  no_upstream_export: true")
println("  curtailment_budget_alpha: $(PAPER_ALPHA_CUR)")
print_zero_pv_base_feeder_check()
println("termination_status: $(termination)")

if termination in ("OPTIMAL", "ALMOST_OPTIMAL") && has_values(model)
    pv_capacity_by_unit = Dict(pv.id => Float64(value(pv_vars.capacity_kw[pv.id])) for pv in data.pv_units)
    total_pv_capacity_kw = sum(values(pv_capacity_by_unit))
    total_load_kw = sum(bus.pd_kw for bus in data.buses)
    hc_load_ratio = total_pv_capacity_kw / total_load_kw
    available_energy_kwh = total_available_energy_kwh(data, pv_vars)
    curtailed_energy_kwh = total_curtailed_energy_kwh(data, pv_vars)
    curtailment_percentage = available_energy_kwh <= 0.0 ? 0.0 : 100.0 * curtailed_energy_kwh / available_energy_kwh
    p_sub_values = [root_power_kw(data, network_vars, t) for t in 1:data.timeseries.T]
    p_sub_min_kw = minimum(p_sub_values)
    p_sub_max_kw = maximum(p_sub_values)
    voltage_min, min_bus, min_t, voltage_max, max_bus, max_t = voltage_extrema(data, network_vars)
    line_loading, line_branch, line_t = max_line_loading(data, network_vars)
    max_positive_gap, max_positive_branch, most_negative_gap, most_negative_branch = soc_gap_extrema(data, network_vars)
    candidate_limit_kw = sum(min(pv.pmax_kw, pv.smax_kva) for pv in data.pv_units)

    println("total_pv_capacity_kw: $(round(total_pv_capacity_kw; digits=4))")
    println("pv_capacity_by_unit_kw:")
    for (id, capacity_kw) in sort(collect(pv_capacity_by_unit); by=first)
        println("  PV$(id): $(round(capacity_kw; digits=4))")
    end
    println("total_load_kw: $(round(total_load_kw; digits=4))")
    println("hc_load_ratio: $(round(hc_load_ratio; digits=4))")
    println("total_curtailed_energy_kwh: $(round(curtailed_energy_kwh; digits=4))")
    println("curtailment_percentage: $(round(curtailment_percentage; digits=4))")
    println("substation_active_power_min_kw: $(round(p_sub_min_kw; digits=4))")
    println("substation_active_power_max_kw: $(round(p_sub_max_kw; digits=4))")
    println("voltage_min: $(round(voltage_min; digits=5))")
    println("voltage_min_location: bus $(min_bus), time $(min_t)")
    println("voltage_max: $(round(voltage_max; digits=5))")
    println("voltage_max_location: bus $(max_bus), time $(max_t)")
    println("max_line_loading: $(round(line_loading; digits=5))")
    println("max_line_loading_location: branch $(line_branch), time $(line_t)")
    println("soc_gap_max_positive: $(round(max_positive_gap; digits=10))")
    println("soc_gap_max_positive_branch: $(max_positive_branch)")
    println("soc_gap_most_negative: $(round(most_negative_gap; digits=10))")
    println("soc_gap_most_negative_branch: $(most_negative_branch)")

    print_binding_summary(
        total_pv_capacity_kw=total_pv_capacity_kw,
        candidate_limit_kw=candidate_limit_kw,
        curtailment_percentage=curtailment_percentage,
        p_sub_min_kw=p_sub_min_kw,
        voltage_min=voltage_min,
        voltage_max=voltage_max,
        line_loading=line_loading,
    )
else
    println("paper_policy_status: no accepted primal optimum")
    println("paper_policy_note: With the requested full-day S1 policy settings, infeasibility can occur because PV-only S1 has no voltage-control device during high-load low-PV hours, and the synthetic line ratings are active.")
    println("total_pv_capacity_kw: unavailable")
    println("total_load_kw: $(round(sum(bus.pd_kw for bus in data.buses); digits=4))")
    println("hc_load_ratio: unavailable")
    println("total_curtailed_energy_kwh: unavailable")
    println("curtailment_percentage: unavailable")
    println("substation_active_power_min_kw: unavailable")
    println("substation_active_power_max_kw: unavailable")
    println("voltage_min: unavailable")
    println("voltage_max: unavailable")
    println("max_line_loading: unavailable")
    println("soc_gap_max_positive: unavailable")
    println("soc_gap_most_negative: unavailable")
    println("binding_constraints_summary: unavailable")
end
