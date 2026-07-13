using JuMP
using Clarabel

function _build_s2_unmanaged_ev_paper_case(config::S2UnmanagedEVConfig=S2UnmanagedEVConfig())
    full_day = _build_s1_pv_only_paper_case(
        pv_limit_kw=config.pv_limit_kw,
        synthetic_smax_kva=config.synthetic_smax_kva,
        vmin_pu=config.vmin_pu,
        vmax_pu=config.vmax_pu,
    )
    _require(
        config.selected_time_index <= full_day.timeseries.T,
        "selected_time_index must be inside the default time-series horizon",
    )

    selected_t = config.selected_time_index
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

function _build_s2_unmanaged_ev_model(
    data::CaseData=_build_s2_unmanaged_ev_paper_case();
    config::S2UnmanagedEVConfig=S2UnmanagedEVConfig(),
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
)
    check_data_consistency(data)
    ev_load = _unmanaged_ev_load_by_bus(data; ev_penetration_scale=config.ev_penetration_scale)

    model, pv_vars, network_vars, policy = _build_s1_pv_only_paper_model(
        data;
        alpha_cur=config.alpha_cur,
        beta_loss=config.beta_loss,
        optimizer=optimizer,
        silent=silent,
        root_bus=root_bus,
        p_load_adder_by_bus_kw=ev_load.p_by_bus_kw,
        q_load_adder_by_bus_kvar=ev_load.q_by_bus_kvar,
    )

    return model, pv_vars, network_vars, policy, ev_load
end

function _s2_total_capacity_expr(data::CaseData, pv_vars::PVHostingVariables)
    return sum((pv_vars.capacity_kw[pv.id] for pv in data.pv_units); init=0.0)
end

function _s2_loss_expr(network_vars::SOCPNetworkVariables)
    return sum(
        network_vars.r_pu[branch_id] * network_vars.ell[branch_id, 1]
        for branch_id in network_vars.topology.branch_ids;
        init=0.0,
    )
end

function _s2_has_primal_solution(model::JuMP.Model)
    return try
        JuMP.has_values(model)
    catch
        false
    end
end

function _s2_root_power(data::CaseData, network_vars::SOCPNetworkVariables)
    base_kw = _base_power_kw(data)
    root = network_vars.topology.root_bus
    outgoing = network_vars.topology.outgoing_branches[root]

    p_kw = sum(JuMP.value(network_vars.Pij[branch_id, 1]) for branch_id in outgoing; init=0.0) * base_kw
    q_kvar = sum(JuMP.value(network_vars.Qij[branch_id, 1]) for branch_id in outgoing; init=0.0) * base_kw
    return p_kw, q_kvar
end

function _s2_voltage_extrema(data::CaseData, network_vars::SOCPNetworkVariables)
    min_voltage = Inf
    max_voltage = -Inf
    min_bus = 0
    max_bus = 0

    for bus in data.buses
        voltage = sqrt(max(0.0, JuMP.value(network_vars.v[bus.id, 1])))
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

function _s2_line_and_current_loading(data::CaseData, network_vars::SOCPNetworkVariables)
    max_line = -Inf
    max_line_branch = 0
    max_current = -Inf
    max_current_branch = 0

    for branch in data.branches
        if branch.smax_kva <= 0.0
            continue
        end

        line_loading = hypot(
            JuMP.value(network_vars.Pij[branch.id, 1]),
            JuMP.value(network_vars.Qij[branch.id, 1]),
        ) / network_vars.smax_pu[branch.id]
        current_loading = JuMP.value(network_vars.ell[branch.id, 1]) / network_vars.smax_pu[branch.id]^2

        if line_loading > max_line
            max_line = line_loading
            max_line_branch = branch.id
        end
        if current_loading > max_current
            max_current = current_loading
            max_current_branch = branch.id
        end
    end

    if max_line == -Inf
        return NaN, 0, NaN, 0
    end
    return max_line, max_line_branch, max_current, max_current_branch
end

function _s2_soc_gap_extrema(data::CaseData, network_vars::SOCPNetworkVariables)
    max_positive_gap = -Inf
    most_negative_gap = Inf

    for branch in data.branches
        i = network_vars.topology.from_bus[branch.id]
        p = JuMP.value(network_vars.Pij[branch.id, 1])
        q = JuMP.value(network_vars.Qij[branch.id, 1])
        v_i = JuMP.value(network_vars.v[i, 1])
        ell = JuMP.value(network_vars.ell[branch.id, 1])
        gap = p^2 + q^2 - v_i * ell
        max_positive_gap = max(max_positive_gap, gap)
        most_negative_gap = min(most_negative_gap, gap)
    end

    return max_positive_gap, most_negative_gap
end

function _s2_total_pv_available_kw(data::CaseData, pv_vars::PVHostingVariables)
    return sum(JuMP.value(pv_vars.available_kw[pv.id, 1]) for pv in data.pv_units; init=0.0)
end

function _s2_total_pv_injected_kw(data::CaseData, pv_vars::PVHostingVariables)
    return sum(JuMP.value(pv_vars.injection_kw[pv.id, 1]) for pv in data.pv_units; init=0.0)
end

function _s2_total_pv_curtailed_kw(data::CaseData, pv_vars::PVHostingVariables)
    return sum(JuMP.value(pv_vars.curtailment_kw[pv.id, 1]) for pv in data.pv_units; init=0.0)
end

function _s2_base_load_kw(data::CaseData)
    return sum(bus.pd_kw * data.timeseries.load_multiplier[1] for bus in data.buses; init=0.0)
end

function _s2_load_adder_total(load_by_bus::Dict{Int,Vector{Float64}})
    return sum(series[1] for series in values(load_by_bus); init=0.0)
end

function _s2_active_limiting_constraints(config::S2UnmanagedEVConfig, metrics)
    constraints = String[]

    if isapprox(metrics.substation_active_power_kw, 0.0; atol=config.no_export_tol_kw)
        push!(constraints, "no-export-limited")
    end
    if isapprox(metrics.pv_curtailment_percentage, 100.0 * config.alpha_cur; atol=1e-3)
        push!(constraints, "curtailment-budget-limited")
    end
    if isapprox(metrics.loss_percentage, 100.0 * config.beta_loss; atol=1e-3)
        push!(constraints, "loss-sanity-limited")
    end
    if !isnan(metrics.max_line_loading) && isapprox(metrics.max_line_loading, 1.0; atol=config.binding_tol)
        push!(constraints, "line-limited")
    end
    if !isnan(metrics.max_current_loading) && isapprox(metrics.max_current_loading, 1.0; atol=config.binding_tol)
        push!(constraints, "current-limited")
    end
    if isapprox(metrics.voltage_min, config.vmin_pu; atol=config.binding_tol) ||
       isapprox(metrics.voltage_max, config.vmax_pu; atol=config.binding_tol)
        push!(constraints, "voltage-limited")
    end

    return constraints
end

function _s2_snapshot_metrics(
    data::CaseData,
    pv_vars::PVHostingVariables,
    network_vars::SOCPNetworkVariables,
    ev_load,
    config::S2UnmanagedEVConfig,
)
    stage2_hc_kw = sum(JuMP.value(pv_vars.capacity_kw[pv.id]) for pv in data.pv_units; init=0.0)
    base_load_kw = _s2_base_load_kw(data)
    unmanaged_ev_load_kw = _s2_load_adder_total(ev_load.p_by_bus_kw)
    total_ev_reactive_power_kvar = _s2_load_adder_total(ev_load.q_by_bus_kvar)
    total_load_kw = base_load_kw + unmanaged_ev_load_kw

    total_pv_available_kw = _s2_total_pv_available_kw(data, pv_vars)
    total_pv_injected_kw = _s2_total_pv_injected_kw(data, pv_vars)
    total_pv_curtailed_kw = _s2_total_pv_curtailed_kw(data, pv_vars)
    pv_curtailment_percentage = total_pv_available_kw <= 0.0 ?
                                0.0 :
                                100.0 * total_pv_curtailed_kw / total_pv_available_kw

    substation_active_power_kw, substation_reactive_power_kvar = _s2_root_power(data, network_vars)
    network_losses_kw = substation_active_power_kw + total_pv_injected_kw - total_load_kw
    loss_percentage = total_load_kw <= 0.0 ? NaN : network_losses_kw / total_load_kw * 100.0

    voltage_min, voltage_min_bus, voltage_max, voltage_max_bus = _s2_voltage_extrema(data, network_vars)
    max_line_loading, max_line_loading_branch, max_current_loading, max_current_loading_branch =
        _s2_line_and_current_loading(data, network_vars)
    soc_gap_max_positive, soc_gap_most_negative = _s2_soc_gap_extrema(data, network_vars)

    raw_metrics = (
        stage2_hc_kw=stage2_hc_kw,
        base_load_kw=base_load_kw,
        unmanaged_ev_load_kw=unmanaged_ev_load_kw,
        total_load_kw=total_load_kw,
        total_ev_reactive_power_kvar=total_ev_reactive_power_kvar,
        total_pv_available_kw=total_pv_available_kw,
        total_pv_injected_kw=total_pv_injected_kw,
        total_pv_curtailed_kw=total_pv_curtailed_kw,
        pv_curtailment_percentage=pv_curtailment_percentage,
        substation_active_power_kw=substation_active_power_kw,
        substation_reactive_power_kvar=substation_reactive_power_kvar,
        network_losses_kw=network_losses_kw,
        loss_percentage=loss_percentage,
        voltage_min=voltage_min,
        voltage_max=voltage_max,
        voltage_min_bus=voltage_min_bus,
        voltage_max_bus=voltage_max_bus,
        max_line_loading=max_line_loading,
        max_line_loading_branch=max_line_loading_branch,
        max_current_loading=max_current_loading,
        max_current_loading_branch=max_current_loading_branch,
        soc_gap_max_positive=soc_gap_max_positive,
        soc_gap_most_negative=soc_gap_most_negative,
    )
    active_constraints = _s2_active_limiting_constraints(config, raw_metrics)
    classification = isempty(active_constraints) ?
                     "no binding policy/network limit identified" :
                     join(active_constraints, ", ")

    return merge(raw_metrics, (
        active_limiting_constraints=active_constraints,
        result_classification=classification,
    ))
end

function _s2_physical_validity_flag(
    config::S2UnmanagedEVConfig,
    stage1_status::AbstractString,
    stage2_status::AbstractString,
    metrics,
)
    return _s1_paper_snapshot_physical_validity_flag(
        stage1_status=stage1_status,
        stage2_status=stage2_status,
        p_sub_kw=metrics.substation_active_power_kw,
        curtailment_percentage=metrics.pv_curtailment_percentage,
        alpha_cur=config.alpha_cur,
        implied_loss_percentage=metrics.loss_percentage,
        beta_loss=config.beta_loss,
        voltage_min=metrics.voltage_min,
        voltage_max=metrics.voltage_max,
        vmin_pu=config.vmin_pu,
        vmax_pu=config.vmax_pu,
        line_loading=metrics.max_line_loading,
        ell_loading=metrics.max_current_loading,
        soc_gap_max_positive=metrics.soc_gap_max_positive,
        soc_gap_most_negative=metrics.soc_gap_most_negative,
        no_export_tol_kw=config.no_export_tol_kw,
        limit_tol=config.binding_tol,
    )
end

function _solve_s2_stage2_trial(
    data::CaseData,
    config::S2UnmanagedEVConfig,
    target_hc_kw::Float64;
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
)
    model, pv_vars, network_vars, policy, ev_load = _build_s2_unmanaged_ev_model(
        data;
        config=config,
        optimizer=optimizer,
        silent=silent,
        root_bus=root_bus,
    )
    JuMP.@constraint(model, _s2_total_capacity_expr(data, pv_vars) >= target_hc_kw - config.hc_tol_kw)
    JuMP.@objective(model, Min, _s2_loss_expr(network_vars))
    JuMP.optimize!(model)

    return (
        model=model,
        pv_vars=pv_vars,
        network_vars=network_vars,
        policy=policy,
        ev_load=ev_load,
    )
end

function _solve_s2_physical_acceptance(
    data::CaseData,
    config::S2UnmanagedEVConfig,
    stage1_status::AbstractString,
    stage1_hc_kw::Float64;
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
)
    lower_hc_kw = 0.0
    upper_hc_kw = stage1_hc_kw
    best_result = nothing

    while upper_hc_kw - lower_hc_kw > config.hc_search_tol_kw
        target_hc_kw = 0.5 * (lower_hc_kw + upper_hc_kw)
        trial = _solve_s2_stage2_trial(
            data,
            config,
            target_hc_kw;
            optimizer=optimizer,
            silent=silent,
            root_bus=root_bus,
        )
        status = string(JuMP.termination_status(trial.model))

        if status == "OPTIMAL" && _s2_has_primal_solution(trial.model)
            metrics = _s2_snapshot_metrics(data, trial.pv_vars, trial.network_vars, trial.ev_load, config)
            physical_valid = _s2_physical_validity_flag(config, stage1_status, status, metrics)

            if physical_valid
                best_result = merge(trial, (
                    status=status,
                    metrics=metrics,
                    physical_validity_flag=physical_valid,
                ))
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

function _solve_s2_unmanaged_ev_core(
    data::CaseData,
    config::S2UnmanagedEVConfig;
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
)
    model, pv_vars, network_vars, policy, ev_load = _build_s2_unmanaged_ev_model(
        data;
        config=config,
        optimizer=optimizer,
        silent=silent,
        root_bus=root_bus,
    )
    JuMP.optimize!(model)

    stage1_status = string(JuMP.termination_status(model))
    stage1_hc_kw = stage1_status == "OPTIMAL" && _s2_has_primal_solution(model) ?
                   sum(JuMP.value(pv_vars.capacity_kw[pv.id]) for pv in data.pv_units; init=0.0) :
                   NaN

    stage2_result = nothing
    stage2_status = "NOT_RUN"
    if stage1_status == "OPTIMAL" && isfinite(stage1_hc_kw)
        stage2_result = _solve_s2_physical_acceptance(
            data,
            config,
            stage1_status,
            stage1_hc_kw;
            optimizer=optimizer,
            silent=silent,
            root_bus=root_bus,
        )
        stage2_status = stage2_result === nothing ? "NO_PHYSICAL_SOLUTION" : stage2_result.status
    end

    return (
        stage1_status=stage1_status,
        stage1_hc_kw=stage1_hc_kw,
        stage2_status=stage2_status,
        stage2_result=stage2_result,
        stage1_model=model,
        stage1_pv_vars=pv_vars,
        stage1_network_vars=network_vars,
        stage1_policy=policy,
        ev_load=ev_load,
    )
end

function _s2_zero_ev_config(config::S2UnmanagedEVConfig)
    return S2UnmanagedEVConfig(
        scenario_name=:S1,
        selected_time_index=config.selected_time_index,
        ev_penetration_scale=0.0,
        pv_limit_kw=config.pv_limit_kw,
        synthetic_smax_kva=config.synthetic_smax_kva,
        vmin_pu=config.vmin_pu,
        vmax_pu=config.vmax_pu,
        alpha_cur=config.alpha_cur,
        beta_loss=config.beta_loss,
        hc_tol_kw=config.hc_tol_kw,
        hc_search_tol_kw=config.hc_search_tol_kw,
        no_export_tol_kw=config.no_export_tol_kw,
        binding_tol=config.binding_tol,
        s1_hc_baseline_kw=config.s1_hc_baseline_kw,
    )
end

function _s2_s1_comparison_baseline_and_core(
    data::CaseData,
    config::S2UnmanagedEVConfig;
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
)
    baseline_core = _solve_s2_unmanaged_ev_core(
        data,
        _s2_zero_ev_config(config);
        optimizer=optimizer,
        silent=silent,
        root_bus=root_bus,
    )

    if baseline_core.stage2_result === nothing
        return S1ComparisonBaseline(config.s1_hc_baseline_kw, NaN, NaN, NaN), baseline_core
    end

    metrics = baseline_core.stage2_result.metrics
    return (
        S1ComparisonBaseline(
            config.s1_hc_baseline_kw,
            metrics.network_losses_kw,
            metrics.voltage_min,
            metrics.max_line_loading,
        ),
        baseline_core,
    )
end

function _s2_s1_comparison_baseline(
    data::CaseData,
    config::S2UnmanagedEVConfig;
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
)
    baseline, _ = _s2_s1_comparison_baseline_and_core(
        data,
        config;
        optimizer=optimizer,
        silent=silent,
        root_bus=root_bus,
    )
    return baseline
end

function _s2_unavailable_classification(core)
    if occursin("INFEASIBLE", core.stage1_status) || occursin("INFEASIBLE", core.stage2_status)
        return "infeasible"
    elseif core.stage2_status == "NO_PHYSICAL_SOLUTION"
        return "no physical solution"
    elseif core.stage1_status == "SOLVER_ERROR"
        return "solver-error"
    end
    return "unavailable"
end

function _s2_nan_result(
    data::CaseData,
    config::S2UnmanagedEVConfig,
    core,
    comparison_baseline::S1ComparisonBaseline,
    ; classification::Union{Nothing,AbstractString}=nothing,
)
    base_load_kw = _s2_base_load_kw(data)
    unmanaged_ev_load_kw = _s2_load_adder_total(core.ev_load.p_by_bus_kw)
    total_ev_reactive_power_kvar = _s2_load_adder_total(core.ev_load.q_by_bus_kvar)

    unavailable_classification = classification === nothing ?
                                 _s2_unavailable_classification(core) :
                                 String(classification)

    return S2UnmanagedEVResult(
        config.scenario_name,
        config.selected_time_index,
        base_load_kw,
        unmanaged_ev_load_kw,
        base_load_kw + unmanaged_ev_load_kw,
        total_ev_reactive_power_kvar,
        sort(unique(evcs.bus for evcs in data.evcs_units)),
        config.ev_penetration_scale,
        core.stage1_status,
        core.stage2_status,
        core.stage1_hc_kw,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
        0,
        0,
        NaN,
        0,
        NaN,
        0,
        String[],
        unavailable_classification,
        false,
        comparison_baseline.hc_kw,
        comparison_baseline.network_losses_kw,
        comparison_baseline.voltage_min,
        comparison_baseline.max_line_loading,
        NaN,
        NaN,
        NaN,
        NaN,
        NaN,
    )
end

function _assemble_s2_result(
    data::CaseData,
    config::S2UnmanagedEVConfig,
    core,
    comparison_baseline::S1ComparisonBaseline,
)
    if core.stage2_result === nothing
        return _s2_nan_result(data, config, core, comparison_baseline)
    end

    metrics = core.stage2_result.metrics
    physical_validity_flag = _s2_physical_validity_flag(config, core.stage1_status, core.stage2_status, metrics)
    delta_hc_kw = metrics.stage2_hc_kw - comparison_baseline.hc_kw
    delta_hc_percent = 100.0 * delta_hc_kw / comparison_baseline.hc_kw

    return S2UnmanagedEVResult(
        config.scenario_name,
        config.selected_time_index,
        metrics.base_load_kw,
        metrics.unmanaged_ev_load_kw,
        metrics.total_load_kw,
        metrics.total_ev_reactive_power_kvar,
        sort(unique(evcs.bus for evcs in data.evcs_units)),
        config.ev_penetration_scale,
        core.stage1_status,
        core.stage2_status,
        core.stage1_hc_kw,
        metrics.stage2_hc_kw,
        metrics.total_pv_available_kw,
        metrics.total_pv_injected_kw,
        metrics.total_pv_curtailed_kw,
        metrics.pv_curtailment_percentage,
        metrics.substation_active_power_kw,
        metrics.substation_reactive_power_kvar,
        metrics.network_losses_kw,
        metrics.loss_percentage,
        metrics.voltage_min,
        metrics.voltage_max,
        metrics.voltage_min_bus,
        metrics.voltage_max_bus,
        metrics.max_line_loading,
        metrics.max_line_loading_branch,
        metrics.max_current_loading,
        metrics.max_current_loading_branch,
        metrics.active_limiting_constraints,
        metrics.result_classification,
        physical_validity_flag,
        comparison_baseline.hc_kw,
        comparison_baseline.network_losses_kw,
        comparison_baseline.voltage_min,
        comparison_baseline.max_line_loading,
        delta_hc_kw,
        delta_hc_percent,
        metrics.network_losses_kw - comparison_baseline.network_losses_kw,
        metrics.voltage_min - comparison_baseline.voltage_min,
        metrics.max_line_loading - comparison_baseline.max_line_loading,
    )
end

function _solve_s2_unmanaged_ev(
    config::S2UnmanagedEVConfig=S2UnmanagedEVConfig();
    data::Union{Nothing,CaseData}=nothing,
    comparison_baseline::Union{Nothing,S1ComparisonBaseline}=nothing,
    compute_comparison_baseline::Bool=true,
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
)
    case_data = data === nothing ? _build_s2_unmanaged_ev_paper_case(config) : data
    core = _solve_s2_unmanaged_ev_core(
        case_data,
        config;
        optimizer=optimizer,
        silent=silent,
        root_bus=root_bus,
    )

    if comparison_baseline === nothing
        comparison_baseline = compute_comparison_baseline ?
                              _s2_s1_comparison_baseline(
                                  case_data,
                                  config;
                                  optimizer=optimizer,
                                  silent=silent,
                                  root_bus=root_bus,
                              ) :
                              S1ComparisonBaseline(config.s1_hc_baseline_kw, NaN, NaN, NaN)
    end

    return _assemble_s2_result(case_data, config, core, comparison_baseline)
end

function _s2_config_with_ev_penetration_scale(
    config::S2UnmanagedEVConfig,
    ev_penetration_scale::Real,
)
    return S2UnmanagedEVConfig(
        scenario_name=config.scenario_name,
        selected_time_index=config.selected_time_index,
        ev_penetration_scale=ev_penetration_scale,
        pv_limit_kw=config.pv_limit_kw,
        synthetic_smax_kva=config.synthetic_smax_kva,
        vmin_pu=config.vmin_pu,
        vmax_pu=config.vmax_pu,
        alpha_cur=config.alpha_cur,
        beta_loss=config.beta_loss,
        hc_tol_kw=config.hc_tol_kw,
        hc_search_tol_kw=config.hc_search_tol_kw,
        no_export_tol_kw=config.no_export_tol_kw,
        binding_tol=config.binding_tol,
        s1_hc_baseline_kw=config.s1_hc_baseline_kw,
    )
end

function _s2_validate_ev_sensitivity_scales(scales)
    requested_scales = Float64[]
    for scale in scales
        _check_finite_nonnegative(Float64(scale), "EV sensitivity scale")
        push!(requested_scales, Float64(scale))
    end
    _require(!isempty(requested_scales), "at least one EV sensitivity scale is required")
    return requested_scales
end

function _s2_solver_error_core(
    data::CaseData,
    config::S2UnmanagedEVConfig,
)
    return (
        stage1_status="SOLVER_ERROR",
        stage1_hc_kw=NaN,
        stage2_status="NOT_RUN",
        ev_load=_unmanaged_ev_load_by_bus(data; ev_penetration_scale=config.ev_penetration_scale),
    )
end

function _solve_s2_unmanaged_ev_sensitivity(
    scales=DEFAULT_S2_UNMANAGED_EV_SENSITIVITY_SCALES;
    config::S2UnmanagedEVConfig=S2UnmanagedEVConfig(),
    data::Union{Nothing,CaseData}=nothing,
    comparison_baseline::Union{Nothing,S1ComparisonBaseline}=nothing,
    compute_comparison_baseline::Bool=true,
    continue_on_solver_error::Bool=true,
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
)
    requested_scales = _s2_validate_ev_sensitivity_scales(scales)
    case_data = data === nothing ? _build_s2_unmanaged_ev_paper_case(config) : data
    baseline_core = nothing

    if comparison_baseline === nothing
        if compute_comparison_baseline
            comparison_baseline, baseline_core = _s2_s1_comparison_baseline_and_core(
                case_data,
                config;
                optimizer=optimizer,
                silent=silent,
                root_bus=root_bus,
            )
        else
            comparison_baseline = S1ComparisonBaseline(config.s1_hc_baseline_kw, NaN, NaN, NaN)
        end
    end

    results = S2UnmanagedEVResult[]
    for scale in requested_scales
        scale_config = _s2_config_with_ev_penetration_scale(config, scale)

        try
            core = scale == 0.0 && baseline_core !== nothing ?
                   baseline_core :
                   _solve_s2_unmanaged_ev_core(
                       case_data,
                       scale_config;
                       optimizer=optimizer,
                       silent=silent,
                       root_bus=root_bus,
                   )
            push!(results, _assemble_s2_result(case_data, scale_config, core, comparison_baseline))
        catch err
            if !continue_on_solver_error || err isa InterruptException
                rethrow()
            end
            error_core = _s2_solver_error_core(case_data, scale_config)
            push!(
                results,
                _s2_nan_result(
                    case_data,
                    scale_config,
                    error_core,
                    comparison_baseline;
                    classification="solver-error",
                ),
            )
        end
    end

    return results
end

const _S2_UNMANAGED_EV_SENSITIVITY_CSV_HEADERS = [
    "EV scale",
    "EV load kW",
    "Total load kW",
    "Accepted HC kW",
    "Delta HC vs S1 kW",
    "Delta HC vs S1 %",
    "Losses kW",
    "Loss %",
    "Vmin p.u.",
    "Vmax p.u.",
    "Max line loading %",
    "Max current loading %",
    "Curtailment %",
    "Physical validity",
    "Classification",
]

function _s2_sensitivity_csv_cell(value)
    rendered = value isa Real && !isfinite(Float64(value)) ? "" : string(value)
    return "\"" * replace(rendered, "\"" => "\"\"") * "\""
end

function _s2_sensitivity_csv_values(result::S2UnmanagedEVResult)
    return Any[
        result.ev_penetration_scale,
        result.unmanaged_ev_load_kw,
        result.total_load_kw,
        result.stage2_accepted_hc_kw,
        result.delta_HC_kw,
        result.delta_HC_percent,
        result.network_losses_kw,
        result.loss_percentage,
        result.voltage_min,
        result.voltage_max,
        100.0 * result.max_line_loading,
        100.0 * result.max_current_loading,
        result.pv_curtailment_percentage,
        result.physical_validity_flag,
        result.result_classification,
    ]
end

function _write_s2_unmanaged_ev_sensitivity_csv(
    output_path::AbstractString,
    results::AbstractVector{<:S2UnmanagedEVResult},
)
    output_directory = dirname(output_path)
    output_directory == "." || mkpath(output_directory)

    open(output_path, "w") do io
        println(io, join(_s2_sensitivity_csv_cell.( _S2_UNMANAGED_EV_SENSITIVITY_CSV_HEADERS), ","))
        for result in results
            println(io, join(_s2_sensitivity_csv_cell.(_s2_sensitivity_csv_values(result)), ","))
        end
    end

    return abspath(output_path)
end
