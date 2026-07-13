include(joinpath(@__DIR__, "..", "src", "CiroPVHC.jl"))

using .CiroPVHC
using JuMP
using Printf

const PAPER_VMIN_PU = 0.95
const PAPER_VMAX_PU = 1.05
const PAPER_SYNTHETIC_SMAX_KVA = 4000.0
const PAPER_PV_LIMIT_KW = 20000.0
const PAPER_ALPHA_CUR = 0.05
const PAPER_BETA_LOSS = 0.10
const HC_TOL_KW = 1e-2
const HC_SEARCH_TOL_KW = 0.10
const BINDING_TOL = 1e-4
const NO_EXPORT_TOL_KW = 1e-3

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
    return solve_s1_pv_only_paper_model(data; alpha_cur=PAPER_ALPHA_CUR, beta_loss=PAPER_BETA_LOSS)
end

function solve_stage2(data::CaseData, stage1_hc_kw::Float64)
    model, pv_vars, network_vars, policy = build_s1_pv_only_paper_model(
        data;
        alpha_cur=PAPER_ALPHA_CUR,
        beta_loss=PAPER_BETA_LOSS,
    )
    @constraint(model, total_capacity_expr(data, pv_vars) >= stage1_hc_kw - HC_TOL_KW)
    @objective(model, Min, loss_expr(network_vars))
    optimize!(model)
    return model, pv_vars, network_vars, policy
end

function root_active_power_kw(data::CaseData, network_vars)
    base_kw = data.base_mva * 1000.0
    root = network_vars.topology.root_bus
    outgoing = network_vars.topology.outgoing_branches[root]
    return sum(value(network_vars.Pij[branch_id, 1]) for branch_id in outgoing; init=0.0) * base_kw
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

function print_pv_unit_table(data::CaseData, pv_vars)
    println("pv_unit_dispatch_table:")
    @printf(
        "%-10s %-5s %20s %23s %18s %18s %22s\n",
        "pv_unit_id",
        "bus",
        "accepted_capacity_kw",
        "available_power_kw",
        "injected_power_kw",
        "curtailed_power_kw",
        "curtailment_percentage",
    )

    for pv in data.pv_units
        accepted_capacity_kw = value(pv_vars.capacity_kw[pv.id])
        available_power_kw = value(pv_vars.available_kw[pv.id, 1])
        injected_power_kw = value(pv_vars.injection_kw[pv.id, 1])
        curtailed_power_kw = value(pv_vars.curtailment_kw[pv.id, 1])
        curtailment_percentage = available_power_kw <= 0.0 ? 0.0 : 100.0 * curtailed_power_kw / available_power_kw

        @printf(
            "%-10d %-5d %20.4f %23.4f %18.4f %18.4f %22.4f\n",
            pv.id,
            pv.bus,
            accepted_capacity_kw,
            available_power_kw,
            injected_power_kw,
            curtailed_power_kw,
            curtailment_percentage,
        )
    end
end

function classify_result(; p_sub_kw, curtailment_percentage, implied_loss_percentage, line_loading, ell_loading, voltage_min, voltage_max)
    bindings = String[]
    if isapprox(p_sub_kw, 0.0; atol=NO_EXPORT_TOL_KW)
        push!(bindings, "no-export-limited")
    end
    if isapprox(curtailment_percentage, 100.0 * PAPER_ALPHA_CUR; atol=1e-3)
        push!(bindings, "curtailment-budget-limited")
    end
    if isapprox(implied_loss_percentage, 100.0 * PAPER_BETA_LOSS; atol=1e-3)
        push!(bindings, "loss-sanity-limited")
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

function snapshot_metrics(data::CaseData, pv_vars, network_vars)
    stage2_hc_kw = sum(value(pv_vars.capacity_kw[pv.id]) for pv in data.pv_units; init=0.0)
    total_load_kw = sum(bus.pd_kw * data.timeseries.load_multiplier[1] for bus in data.buses; init=0.0)
    total_injected_kw = total_pv_injected_kw(data, pv_vars)
    total_curtailed_kw = total_pv_curtailed_kw(data, pv_vars)
    total_available_kw = total_pv_available_kw(data, pv_vars)
    curtailment_percentage = total_available_kw <= 0.0 ? 0.0 : 100.0 * total_curtailed_kw / total_available_kw
    p_sub_kw = root_active_power_kw(data, network_vars)
    implied_losses_kw = p_sub_kw + total_injected_kw - total_load_kw
    implied_loss_percentage = implied_losses_kw / total_load_kw * 100.0
    voltage_min, min_bus, voltage_max, max_bus = voltage_extrema(data, network_vars)
    line_loading, line_branch, ell_loading, ell_branch = line_and_ell_loading(data, network_vars)
    max_positive_gap, most_negative_gap = soc_gap_extrema(data, network_vars)
    classification = classify_result(
        p_sub_kw=p_sub_kw,
        curtailment_percentage=curtailment_percentage,
        implied_loss_percentage=implied_loss_percentage,
        line_loading=line_loading,
        ell_loading=ell_loading,
        voltage_min=voltage_min,
        voltage_max=voltage_max,
    )

    return (
        stage2_hc_kw=stage2_hc_kw,
        total_load_kw=total_load_kw,
        total_injected_kw=total_injected_kw,
        total_curtailed_kw=total_curtailed_kw,
        curtailment_percentage=curtailment_percentage,
        p_sub_kw=p_sub_kw,
        implied_losses_kw=implied_losses_kw,
        implied_loss_percentage=implied_loss_percentage,
        voltage_min=voltage_min,
        min_bus=min_bus,
        voltage_max=voltage_max,
        max_bus=max_bus,
        line_loading=line_loading,
        line_branch=line_branch,
        ell_loading=ell_loading,
        ell_branch=ell_branch,
        max_positive_gap=max_positive_gap,
        most_negative_gap=most_negative_gap,
        classification=classification,
    )
end

function snapshot_physical_validity(stage1_status::AbstractString, stage2_status::AbstractString, metrics)
    return CiroPVHC._s1_paper_snapshot_physical_validity_flag(
        stage1_status=stage1_status,
        stage2_status=stage2_status,
        p_sub_kw=metrics.p_sub_kw,
        curtailment_percentage=metrics.curtailment_percentage,
        alpha_cur=PAPER_ALPHA_CUR,
        implied_loss_percentage=metrics.implied_loss_percentage,
        beta_loss=PAPER_BETA_LOSS,
        voltage_min=metrics.voltage_min,
        voltage_max=metrics.voltage_max,
        vmin_pu=PAPER_VMIN_PU,
        vmax_pu=PAPER_VMAX_PU,
        line_loading=metrics.line_loading,
        ell_loading=metrics.ell_loading,
        soc_gap_max_positive=metrics.max_positive_gap,
        soc_gap_most_negative=metrics.most_negative_gap,
    )
end

function solve_stage2_physical_acceptance(data::CaseData, stage1_status::AbstractString, stage1_hc_kw::Float64)
    lower_hc_kw = 0.0
    upper_hc_kw = stage1_hc_kw
    best_result = nothing

    while upper_hc_kw - lower_hc_kw > HC_SEARCH_TOL_KW
        target_hc_kw = 0.5 * (lower_hc_kw + upper_hc_kw)
        model, pv_vars, network_vars, policy = solve_stage2(data, target_hc_kw)
        status = string(termination_status(model))

        if status == "OPTIMAL" && has_values(model)
            metrics = snapshot_metrics(data, pv_vars, network_vars)
            physical_valid = snapshot_physical_validity(stage1_status, status, metrics)

            if physical_valid
                best_result = (
                    model=model,
                    pv_vars=pv_vars,
                    network_vars=network_vars,
                    policy=policy,
                    status=status,
                    metrics=metrics,
                )
                lower_hc_kw = target_hc_kw
            else
                upper_hc_kw = target_hc_kw
            end
        else
            upper_hc_kw = target_hc_kw
        end
    end

    return best_result
end

base_data = build_case33_data()
selected_t = selected_max_pv_time(base_data)
data = build_snapshot_case(selected_t)

stage1_model, stage1_pv_vars, _, _ = solve_stage1(data)
stage1_status = string(termination_status(stage1_model))
stage1_hc_kw = stage1_status == "OPTIMAL" && has_values(stage1_model) ?
               sum(value(stage1_pv_vars.capacity_kw[pv.id]) for pv in data.pv_units; init=0.0) :
               NaN

stage2_model = nothing
stage2_pv_vars = nothing
stage2_network_vars = nothing
stage2_metrics = nothing
stage2_status = "NOT_RUN"

if stage1_status == "OPTIMAL" && isfinite(stage1_hc_kw)
    global stage2_model, stage2_pv_vars, stage2_network_vars, stage2_metrics, stage2_status
    stage2_result = solve_stage2_physical_acceptance(data, stage1_status, stage1_hc_kw)
    if stage2_result === nothing
        stage2_status = "NO_PHYSICAL_SOLUTION"
    else
        stage2_model = stage2_result.model
        stage2_pv_vars = stage2_result.pv_vars
        stage2_network_vars = stage2_result.network_vars
        stage2_metrics = stage2_result.metrics
        stage2_status = stage2_result.status
    end
end

println("CiroPVHC S1 PV-only paper-policy final snapshot")
println("benchmark_data: MATPOWER case33bw loads/impedances; raw MATPOWER branch ratings remain unchanged and missing.")
println("paper_study_assumptions:")
println("  selected_time_rule: maximum PV profile")
println("  voltage_bounds_pu: [$(PAPER_VMIN_PU), $(PAPER_VMAX_PU)]")
println("  synthetic_active_branch_smax_kva: $(PAPER_SYNTHETIC_SMAX_KVA)")
println("  synthetic_current_limit: ell <= (Smax/baseMVA)^2 at nominal 1.0 pu voltage")
println("  pv_candidate_limit_kw_per_unit: $(PAPER_PV_LIMIT_KW)")
println("  no_upstream_export: true")
println("  curtailment_budget_alpha: $(PAPER_ALPHA_CUR)")
println("  beta_loss: $(PAPER_BETA_LOSS)")
println("  loss_sanity_constraint: total_network_losses_kw <= beta_loss * total_load_kw")
println("  loss_sanity_context: paper-study physical-validity assumption; not MATPOWER raw data")
println("  stage2_acceptance_rule: highest accepted HC passing the physical validity gate")
println("  stage2_loss_objective: minimize sum(r_ij * ell_ij) at each accepted-HC trial")
println("selected_time_index: $(selected_t)")
println("load_multiplier: $(round(data.timeseries.load_multiplier[1]; digits=5))")
println("pv_profile_value: $(round(data.timeseries.pv_profile[1]; digits=5))")
println("stage1_termination_status: $(stage1_status)")
println("stage1_hc_kw: $(round(stage1_hc_kw; digits=4))")
println("stage2_termination_status: $(stage2_status)")

if stage2_status == "OPTIMAL" && has_values(stage2_model)
    metrics = stage2_metrics
    physical_valid = snapshot_physical_validity(stage1_status, stage2_status, metrics)

    println("stage2_accepted_hc_kw: $(round(metrics.stage2_hc_kw; digits=4))")
    println("total_load_kw: $(round(metrics.total_load_kw; digits=4))")
    println("total_pv_injected_kw: $(round(metrics.total_injected_kw; digits=4))")
    println("substation_active_power_kw: $(round(metrics.p_sub_kw; digits=4))")
    println("implied_losses_kw: $(round(metrics.implied_losses_kw; digits=4))")
    println("implied_loss_percentage: $(round(metrics.implied_loss_percentage; digits=4))")
    println("beta_loss: $(PAPER_BETA_LOSS)")
    println("total_curtailed_power_kw: $(round(metrics.total_curtailed_kw; digits=4))")
    println("curtailment_percentage: $(round(metrics.curtailment_percentage; digits=4))")
    print_pv_unit_table(data, stage2_pv_vars)
    println("voltage_min: $(round(metrics.voltage_min; digits=5))")
    println("voltage_min_bus: $(metrics.min_bus)")
    println("voltage_max: $(round(metrics.voltage_max; digits=5))")
    println("voltage_max_bus: $(metrics.max_bus)")
    println("max_line_loading: $(round(metrics.line_loading; digits=5))")
    println("max_line_loading_branch: $(metrics.line_branch)")
    println("max_ell_loading: $(round(metrics.ell_loading; digits=5))")
    println("max_ell_loading_branch: $(metrics.ell_branch)")
    println("soc_gap_max_positive: $(round(metrics.max_positive_gap; digits=10))")
    println("soc_gap_most_negative: $(round(metrics.most_negative_gap; digits=10))")
    println("result_classification: $(metrics.classification)")
    println("physical_validity_flag: $(physical_valid)")
else
    println("stage2_accepted_hc_kw: unavailable")
    println("total_load_kw: unavailable")
    println("total_pv_injected_kw: unavailable")
    println("substation_active_power_kw: unavailable")
    println("implied_losses_kw: unavailable")
    println("implied_loss_percentage: unavailable")
    println("beta_loss: $(PAPER_BETA_LOSS)")
    println("total_curtailed_power_kw: unavailable")
    println("curtailment_percentage: unavailable")
    println("voltage_min: unavailable")
    println("voltage_min_bus: unavailable")
    println("voltage_max: unavailable")
    println("voltage_max_bus: unavailable")
    println("max_line_loading: unavailable")
    println("max_line_loading_branch: unavailable")
    println("max_ell_loading: unavailable")
    println("max_ell_loading_branch: unavailable")
    println("soc_gap_max_positive: unavailable")
    println("soc_gap_most_negative: unavailable")
    println("result_classification: unavailable")
    println("physical_validity_flag: false")
end
