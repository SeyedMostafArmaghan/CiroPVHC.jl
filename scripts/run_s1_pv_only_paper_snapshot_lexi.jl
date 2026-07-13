include(joinpath(@__DIR__, "..", "src", "CiroPVHC.jl"))

using .CiroPVHC
using JuMP

const PAPER_VMIN_PU = 0.95
const PAPER_VMAX_PU = 1.05
const PAPER_SYNTHETIC_SMAX_KVA = 4000.0
const PAPER_PV_LIMIT_KW = 20000.0
const PAPER_ALPHA_CUR = 0.05
const HC_TOL_KW = 1e-2
const BINDING_TOL = 1e-4
const SOC_SLACK_TOL = 1e-4
const LOSS_PERCENT_TOL = 25.0
const NO_EXPORT_TOL_KW = 1e-3
const LIMIT_TOL = 1e-4

function selected_max_pv_time(data::CaseData)
    return argmax(data.timeseries.pv_profile)
end

function build_snapshot_case(selected_t::Int)
    full_day = build_s1_pv_only_paper_case(
        pv_limit_kw=PAPER_PV_LIMIT_KW,
        synthetic_smax_kva=PAPER_SYNTHETIC_SMAX_KVA,
        vmin_pu=PAPER_VMIN_PU,
        vmax_pu=PAPER_VMAX_PU,
    )
    ts = full_day.timeseries
    snapshot_timeseries = TimeSeries(
        1,
        ts.dt_hours,
        [ts.load_multiplier[selected_t]],
        [ts.pv_profile[selected_t]],
        [ts.ev_availability[selected_t]],
        [ts.unmanaged_ev_profile[selected_t]],
    )

    return CaseData(
        full_day.buses,
        full_day.branches,
        full_day.pv_units,
        full_day.evcs_units,
        full_day.bess_units,
        nothing,
        snapshot_timeseries,
        full_day.base_mva,
        full_day.vmin_pu,
        full_day.vmax_pu,
    )
end

function total_capacity_expr(data::CaseData, pv_vars)
    return sum((pv_vars.capacity_kw[pv.id] for pv in data.pv_units); init=0.0)
end

function loss_expr(network_vars)
    return sum(
        network_vars.r_pu[branch_id] * network_vars.ell[branch_id, 1]
        for branch_id in network_vars.topology.branch_ids;
        init=0.0,
    )
end

function solve_stage1(data::CaseData)
    return solve_s1_pv_only_paper_model(data; alpha_cur=PAPER_ALPHA_CUR)
end

function solve_stage2(data::CaseData, stage1_hc_kw::Float64)
    model, pv_vars, network_vars, policy = build_s1_pv_only_paper_model(data; alpha_cur=PAPER_ALPHA_CUR)
    @constraint(model, total_capacity_expr(data, pv_vars) >= stage1_hc_kw - HC_TOL_KW)
    @objective(model, Min, loss_expr(network_vars))
    optimize!(model)
    return model, pv_vars, network_vars, policy
end

function root_active_power_kw(data::CaseData, network_vars)
    base_kw = data.base_mva * 1000.0
    root = network_vars.topology.root_bus
    outgoing = network_vars.topology.outgoing_branches[root]
    return sum(value(network_vars.Pij[branch_id, 1]) for branch_id in outgoing) * base_kw
end

function voltage_extrema(data::CaseData, network_vars)
    min_voltage = Inf
    max_voltage = -Inf
    min_bus = 0
    max_bus = 0

    for bus in data.buses
        voltage = sqrt(max(0.0, value(network_vars.v[bus.id, 1])))
        if voltage < min_voltage
            min_voltage = voltage
            min_bus = bus.id
        end
        if voltage > max_voltage
            max_voltage = voltage
            max_bus = bus.id
        end
    end

    return min_voltage, min_bus, max_voltage, max_bus
end

function line_and_ell_loading(data::CaseData, network_vars)
    max_line = -Inf
    max_line_branch = 0
    max_ell = -Inf
    max_ell_branch = 0

    for branch in data.branches
        if branch.smax_kva <= 0.0
            continue
        end

        line_loading = hypot(value(network_vars.Pij[branch.id, 1]), value(network_vars.Qij[branch.id, 1])) /
                       network_vars.smax_pu[branch.id]
        ell_loading = value(network_vars.ell[branch.id, 1]) / network_vars.smax_pu[branch.id]^2

        if line_loading > max_line
            max_line = line_loading
            max_line_branch = branch.id
        end
        if ell_loading > max_ell
            max_ell = ell_loading
            max_ell_branch = branch.id
        end
    end

    if max_line == -Inf
        return NaN, 0, NaN, 0
    end
    return max_line, max_line_branch, max_ell, max_ell_branch
end

function soc_gap_extrema(data::CaseData, network_vars)
    max_positive_gap = -Inf
    most_negative_gap = Inf

    for branch in data.branches
        i = network_vars.topology.from_bus[branch.id]
        p = value(network_vars.Pij[branch.id, 1])
        q = value(network_vars.Qij[branch.id, 1])
        v_i = value(network_vars.v[i, 1])
        ell = value(network_vars.ell[branch.id, 1])
        gap = p^2 + q^2 - v_i * ell
        max_positive_gap = max(max_positive_gap, gap)
        most_negative_gap = min(most_negative_gap, gap)
    end

    return max_positive_gap, most_negative_gap
end

function total_pv_injected_kw(data::CaseData, pv_vars)
    return sum(value(pv_vars.injection_kw[pv.id, 1]) for pv in data.pv_units; init=0.0)
end

function total_pv_curtailed_kw(data::CaseData, pv_vars)
    return sum(value(pv_vars.curtailment_kw[pv.id, 1]) for pv in data.pv_units; init=0.0)
end

function total_pv_available_kw(data::CaseData, pv_vars)
    return sum(value(pv_vars.available_kw[pv.id, 1]) for pv in data.pv_units; init=0.0)
end

function model_losses_kw(data::CaseData, network_vars)
    return value(loss_expr(network_vars)) * data.base_mva * 1000.0
end

function classify_result(; p_sub_kw, curtailment_percentage, line_loading, ell_loading, voltage_min, voltage_max)
    bindings = String[]
    if isapprox(p_sub_kw, 0.0; atol=NO_EXPORT_TOL_KW)
        push!(bindings, "no-export-limited")
    end
    if isapprox(curtailment_percentage, 100.0 * PAPER_ALPHA_CUR; atol=1e-3)
        push!(bindings, "curtailment-budget-limited")
    end
    if !isnan(line_loading) && isapprox(line_loading, 1.0; atol=BINDING_TOL)
        push!(bindings, "line-limited")
    end
    if !isnan(ell_loading) && isapprox(ell_loading, 1.0; atol=BINDING_TOL)
        push!(bindings, "current-limited")
    end
    if isapprox(voltage_min, PAPER_VMIN_PU; atol=BINDING_TOL) ||
       isapprox(voltage_max, PAPER_VMAX_PU; atol=BINDING_TOL)
        push!(bindings, "voltage-limited")
    end

    return isempty(bindings) ? "no binding policy/network limit identified" : join(bindings, ", ")
end

function physical_validity_flag(;
    most_negative_gap,
    implied_loss_percentage,
    p_sub_kw,
    voltage_min,
    voltage_max,
    line_loading,
    ell_loading,
)
    soc_materially_slack = most_negative_gap < -SOC_SLACK_TOL
    losses_unrealistic = implied_loss_percentage > LOSS_PERCENT_TOL
    no_export_violated = p_sub_kw < -NO_EXPORT_TOL_KW
    voltage_violated = voltage_min < PAPER_VMIN_PU - LIMIT_TOL || voltage_max > PAPER_VMAX_PU + LIMIT_TOL
    line_violated = !isnan(line_loading) && line_loading > 1.0 + LIMIT_TOL
    current_violated = !isnan(ell_loading) && ell_loading > 1.0 + LIMIT_TOL

    return !(soc_materially_slack || losses_unrealistic || no_export_violated || voltage_violated || line_violated || current_violated)
end

base_data = build_case33_data()
selected_t = selected_max_pv_time(base_data)
data = build_snapshot_case(selected_t)

stage1_model, stage1_pv_vars, _, _ = solve_stage1(data)
stage1_status = string(termination_status(stage1_model))
stage1_hc_kw = stage1_status in ("OPTIMAL", "ALMOST_OPTIMAL") && has_values(stage1_model) ?
               sum(value(stage1_pv_vars.capacity_kw[pv.id]) for pv in data.pv_units; init=0.0) :
               NaN

stage2_model, stage2_pv_vars, stage2_network_vars, _ = solve_stage2(data, stage1_hc_kw)
stage2_status = string(termination_status(stage2_model))

println("CiroPVHC S1 PV-only paper-policy lexicographic snapshot")
println("benchmark_data: MATPOWER case33bw loads/impedances; raw MATPOWER branch ratings remain unchanged and missing.")
println("paper_study_assumptions:")
println("  selected_time_rule: maximum PV profile")
println("  voltage_bounds_pu: [$(PAPER_VMIN_PU), $(PAPER_VMAX_PU)]")
println("  synthetic_active_branch_smax_kva: $(PAPER_SYNTHETIC_SMAX_KVA)")
println("  synthetic_current_limit: ell <= (Smax/baseMVA)^2 at nominal 1.0 pu voltage")
println("  pv_candidate_limit_kw_per_unit: $(PAPER_PV_LIMIT_KW)")
println("  no_upstream_export: true")
println("  curtailment_budget_alpha: $(PAPER_ALPHA_CUR)")
println("  stage2_loss_objective: minimize sum(r_ij * ell_ij)")
println("selected_time_index: $(selected_t)")
println("load_multiplier: $(round(data.timeseries.load_multiplier[1]; digits=5))")
println("pv_profile_value: $(round(data.timeseries.pv_profile[1]; digits=5))")
println("stage1_termination_status: $(stage1_status)")
println("stage1_hc_kw: $(round(stage1_hc_kw; digits=4))")
println("stage2_termination_status: $(stage2_status)")

if stage2_status in ("OPTIMAL", "ALMOST_OPTIMAL") && has_values(stage2_model)
    stage2_hc_kw = sum(value(stage2_pv_vars.capacity_kw[pv.id]) for pv in data.pv_units; init=0.0)
    total_load_kw = sum(bus.pd_kw * data.timeseries.load_multiplier[1] for bus in data.buses)
    total_injected_kw = total_pv_injected_kw(data, stage2_pv_vars)
    total_curtailed_kw = total_pv_curtailed_kw(data, stage2_pv_vars)
    total_available_kw = total_pv_available_kw(data, stage2_pv_vars)
    curtailment_percentage = total_available_kw <= 0.0 ? 0.0 : 100.0 * total_curtailed_kw / total_available_kw
    p_sub_kw = root_active_power_kw(data, stage2_network_vars)
    implied_losses_kw = p_sub_kw + total_injected_kw - total_load_kw
    implied_loss_percentage = implied_losses_kw / total_load_kw * 100.0
    modeled_losses_kw = model_losses_kw(data, stage2_network_vars)
    loss_mismatch_kw = implied_losses_kw - modeled_losses_kw
    voltage_min, min_bus, voltage_max, max_bus = voltage_extrema(data, stage2_network_vars)
    line_loading, line_branch, ell_loading, ell_branch = line_and_ell_loading(data, stage2_network_vars)
    max_positive_gap, most_negative_gap = soc_gap_extrema(data, stage2_network_vars)
    classification = classify_result(
        p_sub_kw=p_sub_kw,
        curtailment_percentage=curtailment_percentage,
        line_loading=line_loading,
        ell_loading=ell_loading,
        voltage_min=voltage_min,
        voltage_max=voltage_max,
    )
    physical_valid = physical_validity_flag(
        most_negative_gap=most_negative_gap,
        implied_loss_percentage=implied_loss_percentage,
        p_sub_kw=p_sub_kw,
        voltage_min=voltage_min,
        voltage_max=voltage_max,
        line_loading=line_loading,
        ell_loading=ell_loading,
    )

    println("stage2_accepted_hc_kw: $(round(stage2_hc_kw; digits=4))")
    println("total_load_kw: $(round(total_load_kw; digits=4))")
    println("total_pv_injected_kw: $(round(total_injected_kw; digits=4))")
    println("substation_active_power_kw: $(round(p_sub_kw; digits=4))")
    println("implied_losses_kw: $(round(implied_losses_kw; digits=4))")
    println("implied_loss_percentage: $(round(implied_loss_percentage; digits=4))")
    println("model_losses_kw: $(round(modeled_losses_kw; digits=4))")
    println("loss_mismatch_kw: $(round(loss_mismatch_kw; digits=6))")
    println("total_curtailed_power_kw: $(round(total_curtailed_kw; digits=4))")
    println("curtailment_percentage: $(round(curtailment_percentage; digits=4))")
    println("voltage_min: $(round(voltage_min; digits=5))")
    println("voltage_min_bus: $(min_bus)")
    println("voltage_max: $(round(voltage_max; digits=5))")
    println("voltage_max_bus: $(max_bus)")
    println("max_line_loading: $(round(line_loading; digits=5))")
    println("max_line_loading_branch: $(line_branch)")
    println("max_ell_loading: $(round(ell_loading; digits=5))")
    println("max_ell_loading_branch: $(ell_branch)")
    println("soc_gap_max_positive: $(round(max_positive_gap; digits=10))")
    println("soc_gap_most_negative: $(round(most_negative_gap; digits=10))")
    println("result_classification: $(classification)")
    println("physical_validity_flag: $(physical_valid)")
else
    println("stage2_accepted_hc_kw: unavailable")
    println("total_load_kw: unavailable")
    println("total_pv_injected_kw: unavailable")
    println("substation_active_power_kw: unavailable")
    println("implied_losses_kw: unavailable")
    println("implied_loss_percentage: unavailable")
    println("model_losses_kw: unavailable")
    println("voltage_min: unavailable")
    println("voltage_max: unavailable")
    println("max_line_loading: unavailable")
    println("max_ell_loading: unavailable")
    println("soc_gap_max_positive: unavailable")
    println("soc_gap_most_negative: unavailable")
    println("result_classification: unavailable")
    println("physical_validity_flag: false")
end
