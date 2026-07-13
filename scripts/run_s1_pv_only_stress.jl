include(joinpath(@__DIR__, "..", "src", "CiroPVHC.jl"))

using .CiroPVHC
using JuMP

const DIAGNOSTIC_PV_LIMIT_KW = 20000.0
const BINDING_TOL = 1e-4
const CURTAILMENT_MODE = :none

function build_stress_case(; pv_limit_kw::Float64=DIAGNOSTIC_PV_LIMIT_KW)
    data = build_case33_data()
    pv_units = [
        PVUnit(pv.id, pv.bus, pv_limit_kw, pv_limit_kw)
        for pv in data.pv_units
    ]

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

function voltage_extrema(data::CaseData, network_vars)
    min_voltage = Inf
    max_voltage = -Inf
    min_bus = nothing
    max_bus = nothing
    min_t = nothing
    max_t = nothing

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

function line_loading(data::CaseData, network_vars)
    constrained_branches = [branch for branch in data.branches if branch.smax_kva > 0.0]
    if isempty(constrained_branches)
        return NaN
    end

    return maximum(
        hypot(
            value(network_vars.Pij[branch.id, t]),
            value(network_vars.Qij[branch.id, t]),
        ) / network_vars.smax_pu[branch.id]
        for branch in constrained_branches
        for t in 1:data.timeseries.T
    )
end

function classify_result(data::CaseData, total_pv_capacity_kw::Float64, voltage_min::Float64, voltage_max::Float64)
    candidate_limit_kw = sum(min(pv.pmax_kw, pv.smax_kva) for pv in data.pv_units)
    candidate_cap_limited = isapprox(total_pv_capacity_kw, candidate_limit_kw; atol=1e-3)
    voltage_limited =
        isapprox(voltage_min, data.vmin_pu; atol=BINDING_TOL) ||
        isapprox(voltage_max, data.vmax_pu; atol=BINDING_TOL)
    missing_line_ratings = all(branch.smax_kva <= 0.0 for branch in data.branches)

    if candidate_cap_limited
        return "candidate-cap-limited"
    elseif voltage_limited
        return "voltage-limited"
    elseif missing_line_ratings
        return "unconstrained by network due to missing line ratings"
    else
        return "network-limited by modeled constraints"
    end
end

data = build_stress_case()
model, pv_vars, network_vars = build_s1_pv_only_model(data; curtailment_mode=CURTAILMENT_MODE)
optimize!(model)

termination = string(termination_status(model))

println("CiroPVHC S1 PV-only SOCP stress diagnostic")
println("diagnostic_pv_limit_kw_per_unit: $(DIAGNOSTIC_PV_LIMIT_KW)")
println("curtailment_mode: $(CURTAILMENT_MODE)")
println("note: PVUnit pmax_kw and smax_kva are both raised in this script so old inverter ratings do not remain the active cap.")
println("line_rating_note: MATPOWER case33bw has smax_kva = 0.0 for every active branch, so thermal line-rating constraints are skipped.")
println("termination_status: $(termination)")

if has_values(model)
    pv_capacity_by_unit = Dict(
        pv.id => Float64(value(pv_vars.capacity_kw[pv.id]))
        for pv in data.pv_units
    )
    total_pv_capacity_kw = sum(values(pv_capacity_by_unit))
    voltage_min, min_bus, min_t, voltage_max, max_bus, max_t = voltage_extrema(data, network_vars)
    max_line_loading = line_loading(data, network_vars)
    classification = classify_result(data, total_pv_capacity_kw, voltage_min, voltage_max)

    println("objective_value: $(round(objective_value(model); digits=4))")
    println("total_pv_capacity_kw: $(round(total_pv_capacity_kw; digits=4))")
    println("pv_capacity_by_unit:")
    for (id, capacity_kw) in sort(collect(pv_capacity_by_unit); by=first)
        println("  PV$(id): $(round(capacity_kw; digits=4)) kW")
    end
    println("voltage_min: $(round(voltage_min; digits=5))")
    println("voltage_min_bus: $(min_bus)")
    println("voltage_min_time_index: $(min_t)")
    println("voltage_max: $(round(voltage_max; digits=5))")
    println("voltage_max_bus: $(max_bus)")
    println("voltage_max_time_index: $(max_t)")
    println("max_line_loading: $(isnan(max_line_loading) ? "NaN (no specified line ratings)" : string(round(max_line_loading; digits=5)))")
    println("result_classification: $(classification)")
else
    println("objective_value: NaN")
    println("total_pv_capacity_kw: NaN")
    println("pv_capacity_by_unit: unavailable")
    println("voltage_min: unavailable")
    println("voltage_max: unavailable")
    println("voltage_min_bus: unavailable")
    println("voltage_max_bus: unavailable")
    println("max_line_loading: unavailable")
    println("result_classification: unavailable because no primal solution was returned")
end
