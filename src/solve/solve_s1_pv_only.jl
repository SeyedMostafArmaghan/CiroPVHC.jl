using JuMP
using Clarabel

function _build_s1_pv_only_model(
    data::CaseData=build_case33_data();
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
    curtailment_mode::Symbol=:none,
    p_load_adder_by_bus_kw::Union{Nothing,Dict}=nothing,
    q_load_adder_by_bus_kvar::Union{Nothing,Dict}=nothing,
)
    check_data_consistency(data)

    model = JuMP.Model(optimizer)
    if silent
        JuMP.set_silent(model)
    end

    pv_vars = add_pv_hosting_variables!(model, data; curtailment_mode=curtailment_mode)
    network_vars = add_socp_branch_flow_constraints!(
        model,
        data,
        pv_vars.injection_by_bus_kw;
        p_load_adder_by_bus_kw=p_load_adder_by_bus_kw,
        q_load_adder_by_bus_kvar=q_load_adder_by_bus_kvar,
        root_bus=root_bus,
    )

    @objective(model, Max, sum((pv_vars.capacity_kw[pv.id] for pv in data.pv_units); init=0.0))

    return model, pv_vars, network_vars
end

function _has_primal_solution(model::JuMP.Model)
    return try
        JuMP.has_values(model)
    catch
        false
    end
end

function _extract_s1_pv_only_result(
    model::JuMP.Model,
    data::CaseData,
    pv_vars::PVHostingVariables,
    network_vars::SOCPNetworkVariables,
)
    termination_status = string(JuMP.termination_status(model))

    if !_has_primal_solution(model)
        return S1PVOnlyResult(
            termination_status,
            NaN,
            Dict{Int,Float64}(),
            NaN,
            NaN,
            NaN,
            NaN,
        )
    end

    times = 1:data.timeseries.T
    pv_capacity_by_unit = Dict(
        pv.id => Float64(JuMP.value(pv_vars.capacity_kw[pv.id]))
        for pv in data.pv_units
    )

    voltage_values = [
        sqrt(max(0.0, JuMP.value(network_vars.v[bus.id, t])))
        for bus in data.buses
        for t in times
    ]

    constrained_branches = [branch for branch in data.branches if branch.smax_kva > 0.0]
    line_loading_values = [
        hypot(
            JuMP.value(network_vars.Pij[branch.id, t]),
            JuMP.value(network_vars.Qij[branch.id, t]),
        ) / network_vars.smax_pu[branch.id]
        for branch in constrained_branches
        for t in times
    ]

    total_pv_capacity_kw = sum(values(pv_capacity_by_unit))

    return S1PVOnlyResult(
        termination_status,
        Float64(JuMP.objective_value(model)),
        pv_capacity_by_unit,
        minimum(voltage_values),
        maximum(voltage_values),
        isempty(line_loading_values) ? NaN : maximum(line_loading_values),
        total_pv_capacity_kw,
    )
end

function _solve_s1_pv_only(
    data::CaseData=build_case33_data();
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
    curtailment_mode::Symbol=:none,
)
    model, pv_vars, network_vars = _build_s1_pv_only_model(
        data;
        optimizer=optimizer,
        silent=silent,
        root_bus=root_bus,
        curtailment_mode=curtailment_mode,
    )
    JuMP.optimize!(model)
    return _extract_s1_pv_only_result(model, data, pv_vars, network_vars)
end

function _build_s1_pv_only_paper_case(;
    pv_limit_kw::Float64=20000.0,
    synthetic_smax_kva::Float64=4000.0,
    vmin_pu::Float64=0.95,
    vmax_pu::Float64=1.05,
)
    benchmark = build_case33_data()

    # Paper-study assumption: MATPOWER case33bw has missing thermal ratings
    # encoded as zero. For this policy run, assign synthetic active-branch
    # ratings explicitly while leaving raw benchmark data unchanged.
    branches = [
        Branch(
            branch.id,
            branch.from_bus,
            branch.to_bus,
            branch.r_ohm,
            branch.x_ohm,
            synthetic_smax_kva,
        )
        for branch in benchmark.branches
    ]

    # Paper-study assumption: use large candidate limits so hosting capacity
    # is set by network/policy constraints rather than by candidate caps.
    pv_units = [PVUnit(pv.id, pv.bus, pv_limit_kw, pv_limit_kw) for pv in benchmark.pv_units]

    return CaseData(
        benchmark.buses,
        branches,
        pv_units,
        benchmark.evcs_units,
        benchmark.bess_units,
        benchmark.doe,
        benchmark.timeseries,
        benchmark.base_mva,
        vmin_pu,
        vmax_pu,
    )
end

function _add_s1_no_export_constraints!(model::JuMP.Model, data::CaseData, network_vars::SOCPNetworkVariables)
    times = 1:data.timeseries.T
    root_bus = network_vars.topology.root_bus
    root_outgoing = network_vars.topology.outgoing_branches[root_bus]

    return @constraint(model, [t in times], sum(network_vars.Pij[branch_id, t] for branch_id in root_outgoing) >= 0.0)
end

function _add_s1_curtailment_budget!(
    model::JuMP.Model,
    data::CaseData,
    pv_vars::PVHostingVariables;
    alpha_cur::Float64=0.05,
)
    _require(0.0 <= alpha_cur <= 1.0, "alpha_cur must be in [0, 1]")

    times = 1:data.timeseries.T
    dt = data.timeseries.dt_hours
    available_energy_kwh = sum(
        pv_vars.available_kw[pv.id, t] * dt
        for pv in data.pv_units
        for t in times;
        init=0.0,
    )
    curtailed_energy_kwh = sum(
        pv_vars.curtailment_kw[pv.id, t] * dt
        for pv in data.pv_units
        for t in times;
        init=0.0,
    )

    constraint = @constraint(model, curtailed_energy_kwh <= alpha_cur * available_energy_kwh)
    return (
        available_energy_kwh=available_energy_kwh,
        curtailed_energy_kwh=curtailed_energy_kwh,
        constraint=constraint,
    )
end

function _s1_network_loss_expr(network_vars::SOCPNetworkVariables, t::Int)
    return sum(
        network_vars.r_pu[branch_id] * network_vars.ell[branch_id, t]
        for branch_id in network_vars.topology.branch_ids;
        init=0.0,
    )
end

function _add_s1_loss_sanity_constraints!(
    model::JuMP.Model,
    data::CaseData,
    network_vars::SOCPNetworkVariables;
    beta_loss::Float64=0.10,
    p_load_adder_by_bus_kw::Union{Nothing,Dict}=nothing,
)
    _require(0.0 <= beta_loss <= 1.0, "beta_loss must be in [0, 1]")

    # Paper-study physical-validity assumption: cap modeled network losses as
    # a fraction of active load. This is not MATPOWER raw branch-rating data.
    times = 1:data.timeseries.T
    base_kw = _base_power_kw(data)
    if p_load_adder_by_bus_kw === nothing
        p_load_adder_by_bus_kw = Dict(bus.id => zeros(Float64, data.timeseries.T) for bus in data.buses)
    end
    total_load_kw = Dict(
        t => sum(
            bus.pd_kw * data.timeseries.load_multiplier[t] +
            _series_value_by_bus(p_load_adder_by_bus_kw, bus.id, t)
            for bus in data.buses;
            init=0.0,
        )
        for t in times
    )
    total_network_losses_kw = Dict(
        t => base_kw * _s1_network_loss_expr(network_vars, t)
        for t in times
    )
    constraints = Dict(
        t => @constraint(model, total_network_losses_kw[t] <= beta_loss * total_load_kw[t])
        for t in times
    )

    return (
        beta_loss=beta_loss,
        total_load_kw=total_load_kw,
        total_network_losses_kw=total_network_losses_kw,
        constraints=constraints,
    )
end

function _s1_paper_snapshot_physical_validity_flag(;
    stage1_status::AbstractString,
    stage2_status::AbstractString,
    p_sub_kw::Real,
    curtailment_percentage::Real,
    alpha_cur::Real,
    implied_loss_percentage::Real,
    beta_loss::Real,
    voltage_min::Real,
    voltage_max::Real,
    vmin_pu::Real,
    vmax_pu::Real,
    line_loading::Real,
    ell_loading::Real,
    soc_gap_max_positive::Real,
    soc_gap_most_negative::Real,
    no_export_tol_kw::Real=1e-3,
    curtailment_tol_percent::Real=1e-3,
    loss_tol_percent::Real=1e-3,
    limit_tol::Real=1e-4,
    soc_gap_tol::Real=1e-4,
)
    finite_metrics = all(
        isfinite,
        Float64[
            p_sub_kw,
            curtailment_percentage,
            alpha_cur,
            implied_loss_percentage,
            beta_loss,
            voltage_min,
            voltage_max,
            vmin_pu,
            vmax_pu,
            line_loading,
            ell_loading,
            soc_gap_max_positive,
            soc_gap_most_negative,
        ],
    )

    return finite_metrics &&
           stage1_status == "OPTIMAL" &&
           stage2_status == "OPTIMAL" &&
           p_sub_kw >= -no_export_tol_kw &&
           curtailment_percentage <= 100.0 * alpha_cur + curtailment_tol_percent &&
           implied_loss_percentage <= 100.0 * beta_loss + loss_tol_percent &&
           voltage_min >= vmin_pu - limit_tol &&
           voltage_max <= vmax_pu + limit_tol &&
           line_loading <= 1.0 + limit_tol &&
           ell_loading <= 1.0 + limit_tol &&
           soc_gap_max_positive <= soc_gap_tol &&
           soc_gap_most_negative >= -soc_gap_tol
end

function _build_s1_pv_only_paper_model(
    data::CaseData=_build_s1_pv_only_paper_case();
    alpha_cur::Float64=0.05,
    beta_loss::Float64=0.10,
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
    p_load_adder_by_bus_kw::Union{Nothing,Dict}=nothing,
    q_load_adder_by_bus_kvar::Union{Nothing,Dict}=nothing,
)
    model, pv_vars, network_vars = _build_s1_pv_only_model(
        data;
        optimizer=optimizer,
        silent=silent,
        root_bus=root_bus,
        curtailment_mode=:free,
        p_load_adder_by_bus_kw=p_load_adder_by_bus_kw,
        q_load_adder_by_bus_kvar=q_load_adder_by_bus_kvar,
    )
    no_export_constraints = _add_s1_no_export_constraints!(model, data, network_vars)
    curtailment_budget = _add_s1_curtailment_budget!(model, data, pv_vars; alpha_cur=alpha_cur)
    loss_sanity = _add_s1_loss_sanity_constraints!(
        model,
        data,
        network_vars;
        beta_loss=beta_loss,
        p_load_adder_by_bus_kw=p_load_adder_by_bus_kw,
    )

    return model, pv_vars, network_vars, (
        no_export_constraints=no_export_constraints,
        curtailment_budget=curtailment_budget,
        loss_sanity=loss_sanity,
        alpha_cur=alpha_cur,
        beta_loss=beta_loss,
    )
end

function _solve_s1_pv_only_paper_model(
    data::CaseData=_build_s1_pv_only_paper_case();
    alpha_cur::Float64=0.05,
    beta_loss::Float64=0.10,
    optimizer=Clarabel.Optimizer,
    silent::Bool=true,
    root_bus::Int=1,
    p_load_adder_by_bus_kw::Union{Nothing,Dict}=nothing,
    q_load_adder_by_bus_kvar::Union{Nothing,Dict}=nothing,
)
    model, pv_vars, network_vars, policy = _build_s1_pv_only_paper_model(
        data;
        alpha_cur=alpha_cur,
        beta_loss=beta_loss,
        optimizer=optimizer,
        silent=silent,
        root_bus=root_bus,
        p_load_adder_by_bus_kw=p_load_adder_by_bus_kw,
        q_load_adder_by_bus_kvar=q_load_adder_by_bus_kvar,
    )
    JuMP.optimize!(model)
    return model, pv_vars, network_vars, policy
end
