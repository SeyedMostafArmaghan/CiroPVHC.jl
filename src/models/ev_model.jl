function _ev_reactive_multiplier(evcs::EVCS)
    if evcs.reactive_power_convention == :unity || isapprox(evcs.charging_power_factor, 1.0; atol=eps(Float64))
        return 0.0
    end

    magnitude = tan(acos(evcs.charging_power_factor))
    sign = evcs.reactive_power_convention == :lagging ? 1.0 : -1.0
    return sign * magnitude
end

function _unmanaged_ev_active_power_kw(
    evcs::EVCS,
    timeseries::TimeSeries,
    t::Integer;
    ev_penetration_scale::Real=1.0,
)
    _require(1 <= t <= timeseries.T, "time index must be inside the time-series horizon")
    _check_finite_nonnegative(Float64(ev_penetration_scale), "EV penetration scale")

    return evcs.pmax_kw *
           timeseries.unmanaged_ev_profile[Int(t)] *
           evcs.unmanaged_profile_scale *
           evcs.ev_penetration_scale *
           Float64(ev_penetration_scale)
end

function _unmanaged_ev_reactive_power_kvar(
    evcs::EVCS,
    timeseries::TimeSeries,
    t::Integer;
    ev_penetration_scale::Real=1.0,
)
    return _unmanaged_ev_active_power_kw(evcs, timeseries, t; ev_penetration_scale=ev_penetration_scale) *
           _ev_reactive_multiplier(evcs)
end

function _unmanaged_ev_load_by_bus(
    data::CaseData;
    ev_penetration_scale::Real=1.0,
)
    _check_finite_nonnegative(Float64(ev_penetration_scale), "EV penetration scale")

    times = 1:data.timeseries.T
    p_by_bus_kw = Dict(bus.id => zeros(Float64, data.timeseries.T) for bus in data.buses)
    q_by_bus_kvar = Dict(bus.id => zeros(Float64, data.timeseries.T) for bus in data.buses)

    for evcs in data.evcs_units, t in times
        p_ev_kw = _unmanaged_ev_active_power_kw(
            evcs,
            data.timeseries,
            t;
            ev_penetration_scale=ev_penetration_scale,
        )
        q_ev_kvar = p_ev_kw * _ev_reactive_multiplier(evcs)

        p_by_bus_kw[evcs.bus][t] += p_ev_kw
        q_by_bus_kvar[evcs.bus][t] += q_ev_kvar
    end

    return (
        p_by_bus_kw=p_by_bus_kw,
        q_by_bus_kvar=q_by_bus_kvar,
    )
end
