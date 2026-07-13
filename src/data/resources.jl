function build_default_pv_units()
    return [
        PVUnit(1, 6, 350.0, 390.0),
        PVUnit(2, 14, 450.0, 500.0),
        PVUnit(3, 25, 600.0, 660.0),
        PVUnit(4, 30, 500.0, 550.0),
        PVUnit(5, 32, 300.0, 330.0),
    ]
end

function build_default_evcs_units()
    return [
        EVCS(
            id=1,
            bus=18,
            pmax_kw=300.0,
            eta=0.95,
            required_energy_kwh=900.0,
            charger_count=10,
            charging_power_factor=0.95,
            reactive_power_convention=:lagging,
            unmanaged_profile_scale=1.0,
            ev_penetration_scale=1.0,
        ),
        EVCS(
            id=2,
            bus=22,
            pmax_kw=250.0,
            eta=0.95,
            required_energy_kwh=700.0,
            charger_count=8,
            charging_power_factor=0.95,
            reactive_power_convention=:lagging,
            unmanaged_profile_scale=1.0,
            ev_penetration_scale=1.0,
        ),
        EVCS(
            id=3,
            bus=25,
            pmax_kw=500.0,
            eta=0.95,
            required_energy_kwh=1500.0,
            charger_count=16,
            charging_power_factor=0.95,
            reactive_power_convention=:lagging,
            unmanaged_profile_scale=1.0,
            ev_penetration_scale=1.0,
        ),
        EVCS(
            id=4,
            bus=33,
            pmax_kw=350.0,
            eta=0.95,
            required_energy_kwh=1000.0,
            charger_count=12,
            charging_power_factor=0.95,
            reactive_power_convention=:lagging,
            unmanaged_profile_scale=1.0,
            ev_penetration_scale=1.0,
        ),
    ]
end

function build_default_bess_units()
    return [
        BESS(1, 14, 250.0, 250.0, 100.0, 1000.0, 500.0, 0.95, 0.95, 300.0),
        BESS(2, 30, 300.0, 300.0, 120.0, 1200.0, 600.0, 0.95, 0.95, 360.0),
    ]
end

function build_default_doe(T::Integer)
    _require(T > 0, "T must be positive")

    n_steps = Int(T)
    dt_hours = 24.0 / Float64(n_steps)
    hours = [dt_hours * (t - 1) for t in 1:n_steps]

    p_import_max_kw = [
        clamp(3200.0 + 500.0 * exp(-((hour - 20.0) / 4.5)^2), 0.0, 3800.0)
        for hour in hours
    ]
    p_export_max_kw = [
        clamp(900.0 + 900.0 * exp(-((hour - 12.0) / 4.0)^2), 0.0, 1800.0)
        for hour in hours
    ]

    return DOE(1, Float64.(p_import_max_kw), Float64.(p_export_max_kw))
end

function build_case33_data()
    buses, branches = build_ieee33_network()
    timeseries = build_default_timeseries()

    return CaseData(
        buses,
        branches,
        build_default_pv_units(),
        build_default_evcs_units(),
        build_default_bess_units(),
        build_default_doe(timeseries.T),
        timeseries,
        10.0,
        0.90,
        1.10,
    )
end
