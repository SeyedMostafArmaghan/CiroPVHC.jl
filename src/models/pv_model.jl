using JuMP

struct PVHostingVariables
    capacity_kw::Any
    available_kw::Any
    injection_kw::Any
    curtailment_kw::Any
    injection_by_bus_kw::Dict{Int,Vector{JuMP.AffExpr}}
end

function add_pv_hosting_variables!(
    model::JuMP.Model,
    data::CaseData;
    curtailment_mode::Symbol=:none,
)
    _require(curtailment_mode in (:none, :free), "curtailment_mode must be :none or :free")

    pv_ids = [pv.id for pv in data.pv_units]
    times = 1:data.timeseries.T
    capacity_limit_kw = Dict(pv.id => min(pv.pmax_kw, pv.smax_kva) for pv in data.pv_units)

    @variable(
        model,
        0 <= pv_capacity_kw[pv_id in pv_ids] <= capacity_limit_kw[pv_id],
        base_name = "pv_capacity_kw"
    )
    @variable(model, 0 <= pv_available_kw[pv_id in pv_ids, t in times], base_name = "pv_available_kw")
    @variable(model, 0 <= pv_injection_kw[pv_id in pv_ids, t in times], base_name = "pv_injection_kw")
    @variable(model, 0 <= pv_curtailment_kw[pv_id in pv_ids, t in times], base_name = "pv_curtailment_kw")

    for pv in data.pv_units, t in times
        @constraint(model, pv_available_kw[pv.id, t] == data.timeseries.pv_profile[t] * pv_capacity_kw[pv.id])
        @constraint(model, pv_injection_kw[pv.id, t] + pv_curtailment_kw[pv.id, t] == pv_available_kw[pv.id, t])
        if curtailment_mode == :none
            @constraint(model, pv_curtailment_kw[pv.id, t] == 0.0)
        end
    end

    injection_by_bus_kw = Dict(
        bus.id => [JuMP.AffExpr(0.0) for _ in times]
        for bus in data.buses
    )

    for pv in data.pv_units, t in times
        injection_by_bus_kw[pv.bus][t] = injection_by_bus_kw[pv.bus][t] + pv_injection_kw[pv.id, t]
    end

    return PVHostingVariables(pv_capacity_kw, pv_available_kw, pv_injection_kw, pv_curtailment_kw, injection_by_bus_kw)
end
